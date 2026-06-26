"""Widoki aplikacji accounts (login, logout, profile, employee management)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView
from django_ratelimit.decorators import ratelimit

from core.pagination import PerPageMixin
from core.service_errors import add_form_errors

from .forms import PlanerAuthenticationForm, ProfileForm, RegisterEmployeeForm
from .models import EmployeeProfile
from .services import anonymize_employee, register_employee, terminate_employee, update_profile


def _apply_language_cookie(response: HttpResponse, lang_code: str) -> HttpResponse:
    """Ustawia ciasteczko języka (mechanizm Django LocaleMiddleware) na odpowiedzi.

    Pozwala utrwalić wybór języka profilu (``preferred_language``) jako domyślny
    język UI — odczytywany przez ``LocaleMiddleware`` przy kolejnych żądaniach.
    Mirror logiki ``django.views.i18n.set_language``. Świadomie NIE wołamy
    ``translation.activate`` — odpowiedź to redirect (brak renderowanej treści),
    a aktywacja per-wątek wyciekałaby do kolejnych żądań/testów.
    """
    if lang_code:
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang_code,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
    return response


@method_decorator(
    ratelimit(key="ip", rate="20/h", method="POST", block=True),
    name="dispatch",
)
class PlanerLoginView(LoginView):
    """Widok logowania używający szablonu accounts/login.html.

    Druga warstwa ochrony przed brute-force (obok ``django-axes``):
    rate-limit IP 20 prób POST / godzinę. Axes blokuje po 5 nieudanych
    próbach per (username, ip), ratelimit chroni przed enumeracją wielu
    użytkowników z tego samego IP. ``block=True`` rzuca ``Ratelimited``,
    przechwytywane przez ``chatbot.middleware.RatelimitedMiddleware``
    i renderowane jako HTTP 429 z polskim komunikatem.
    """

    template_name = "accounts/login.html"
    authentication_form = PlanerAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        """Po zalogowaniu ustaw język UI na preferencję profilu użytkownika."""
        response = super().form_valid(form)
        profile = getattr(self.request.user, "profile", None)
        if profile is not None:
            _apply_language_cookie(response, profile.preferred_language)
        return response


class AxesLockedView(TemplateView):
    """Strona pokazywana po przekroczeniu limitu prób (``AXES_LOCKOUT_URL``).

    ``django-axes`` przekierowuje tutaj zamiast pokazywać białą stronę 403
    — daje spójny look z resztą UI i jasny komunikat po polsku.
    """

    template_name = "accounts/locked.html"


class PlanerLogoutView(LogoutView):
    """Widok wylogowania — przekierowuje na stronę główną."""

    next_page = reverse_lazy("home")


@login_required
def profile(request):
    """Widok profilu zalogowanego użytkownika (podgląd + edycja podstawowych danych).

    Aktualizacja delegowana do ``update_profile`` (service layer) — daje spójne
    walidowanie i jeden punkt do podpięcia audytu / history.
    """
    employee_profile = request.user.profile

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=employee_profile)
        if form.is_valid():
            update_profile(employee_profile, **form.cleaned_data)
            # Zmiana języka w profilu od razu przełącza UI (utrwalenie w cookie).
            response = redirect("accounts:profile")
            return _apply_language_cookie(response, employee_profile.preferred_language)
    else:
        form = ProfileForm(instance=employee_profile)

    return render(
        request,
        "accounts/profile.html",
        {"form": form, "profile": employee_profile},
    )


@login_required
def data_export_view(request):
    """Eksport danych zalogowanego użytkownika (RODO Art. 20 — przenoszalność).

    Zwraca komplet danych usera w formacie JSON (do pobrania): konto, profil,
    rezerwacje utworzone przez niego oraz wpisy dziennika zdarzeń go dotyczące.
    Samoobsługowo — każdy widzi WYŁĄCZNIE własne dane.
    """
    from core.models import AuditLogEntry
    from reservations.models import Reservation

    user = request.user
    profile = user.profile
    reservations = Reservation.objects.filter(created_by=user).select_related("machine", "site")
    audit = AuditLogEntry.objects.filter(user=user)

    payload = {
        "exported_at": timezone.now().isoformat(),
        "account": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "date_joined": user.date_joined.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
        },
        "profile": {
            "function": profile.function,
            "phone": profile.phone,
            "employee_id": profile.employee_id,
            "preferred_language": profile.preferred_language,
            "theme_preference": profile.theme_preference,
        },
        "reservations": [
            {
                "id": r.pk,
                "machine": r.machine.uid if r.machine_id else None,
                "site": r.site.project_number if r.site_id else None,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "status": r.status,
                "person": r.person,
            }
            for r in reservations
        ],
        "audit_log": [
            {
                "timestamp": a.timestamp.isoformat(),
                "action": a.action,
                "object_type": a.object_type,
                "object_id": a.object_id,
            }
            for a in audit
        ],
    }
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    filename = f"moje-dane-{user.username}-{timezone.now():%Y-%m-%d}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@permission_required("accounts.add_employeeprofile", raise_exception=True)
def employee_register_view(request):
    """Wave 14-F O-1: UI dla ``accounts.services.register_employee``.

    Audyt Wave 14-E O-1: service ``register_employee`` istniał ale nie miał
    żadnego front-endowego entry pointu. Operator chcąc utworzyć pracownika
    musiał używać ``/admin/auth/user/add/`` (raw Django form), co:

    * NIE waliduje hasła przez HIBP (Django admin tworzy ``User`` bez
      ``validate_password`` w pierwszym kroku — robi to dopiero w drugim
      kroku po set_password, ale to dwie strony admin'a → friction);
    * NIE pozwala ustawić ``EmployeeProfile.function`` w jednym kroku
      (signal post_save tworzy profil z domyślnym MONTAZYSTA — operator
      musi później kliknąć Profile i zmienić funkcję ręcznie);
    * NIE pozwala ustawić ``EmployeeProfile.phone`` (to samo).

    Ten view łączy wszystko w jeden formularz — od razu pełna walidacja
    hasła (HIBP), funkcja RBAC, telefon, dane osobowe (imię/nazwisko/email).

    Permission: ``accounts.add_employeeprofile`` (Django auto-permission
    z ``EmployeeProfile.Meta``). Brak permission → 403 (raise_exception).
    """
    if request.method == "POST":
        form = RegisterEmployeeForm(request.POST)
        if form.is_valid():
            try:
                profile = register_employee(
                    username=form.cleaned_data["username"],
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password1"],
                    function=form.cleaned_data["function"],
                    first_name=form.cleaned_data.get("first_name", ""),
                    last_name=form.cleaned_data.get("last_name", ""),
                    phone=form.cleaned_data.get("phone", ""),
                    actor=request.user,
                )
            except ValidationError as exc:
                # Hasło nie przeszło HIBP/min length etc. — przepisujemy
                # błędy z service layer na pole password1.
                add_form_errors(form, exc)
            else:
                full_name = profile.user.get_full_name() or profile.user.username
                messages.success(
                    request,
                    _("Pracownik zarejestrowany: %(name)s") % {"name": full_name},
                )
                # Redirect do admin user change (operator może od razu
                # dodać dodatkowe permisje per-user gdyby były potrzebne).
                return redirect("admin:auth_user_change", profile.user.pk)
    else:
        form = RegisterEmployeeForm()

    return render(
        request,
        "accounts/employee_register.html",
        {"form": form},
    )


# =============================================================================
# EMPLOYEE LIST + LIFECYCLE ACTIONS (terminate / anonymize)
# =============================================================================


class EmployeeListView(PerPageMixin, LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Lista pracowników z filtrami status (aktywni / zwolnieni / wszyscy) + funkcja.

    Filtry GET:
      * ``filter=active`` (default) — tylko aktywni (``is_active_employee=True``).
      * ``filter=terminated`` — zwolnieni (``is_active_employee=False`` lub
        ``termination_date IS NOT NULL``), wykluczając zanonimizowanych.
      * ``filter=anonymized`` — zanonimizowani (GDPR Art.17 erasure).
      * ``filter=all`` — wszyscy.
      * ``function`` — filtr po :class:`EmployeeProfile.Function`.
      * ``q`` — search po username / imię / nazwisko / email / phone.
    """

    model = EmployeeProfile
    template_name = "accounts/employee_list.html"
    context_object_name = "profiles"
    permission_required = "accounts.view_employeeprofile"
    raise_exception = True

    def get_queryset(self):
        qs = EmployeeProfile.objects.select_related("user").order_by(
            "-is_active_employee", "user__last_name", "user__username"
        )
        filter_value = self.request.GET.get("filter", "active")
        if filter_value == "active":
            qs = qs.filter(is_active_employee=True, is_anonymized=False)
        elif filter_value == "terminated":
            qs = qs.filter(is_active_employee=False, is_anonymized=False)
        elif filter_value == "anonymized":
            qs = qs.filter(is_anonymized=True)
        # "all" — bez filtra

        function = self.request.GET.get("function")
        if function:
            qs = qs.filter(function=function)

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(user__username__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__email__icontains=q)
                | Q(phone__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_filter"] = self.request.GET.get("filter", "active")
        ctx["current_function"] = self.request.GET.get("function", "")
        ctx["current_q"] = self.request.GET.get("q", "")
        ctx["function_choices"] = EmployeeProfile.Function.choices
        ctx["counts"] = {
            "active": EmployeeProfile.objects.filter(
                is_active_employee=True, is_anonymized=False
            ).count(),
            "terminated": EmployeeProfile.objects.filter(
                is_active_employee=False, is_anonymized=False
            ).count(),
            "anonymized": EmployeeProfile.objects.filter(is_anonymized=True).count(),
            "all": EmployeeProfile.objects.count(),
        }
        return ctx


@login_required
@permission_required("accounts.change_employeeprofile", raise_exception=True)
@require_POST
def employee_terminate_view(request: HttpRequest, pk: int) -> HttpResponse:
    """POST endpoint: kończy zatrudnienie pracownika (``terminate_employee`` service).

    Confirm w UI — template list ma 2-step button (Alpine confirming flag).
    Po sukcesie redirect do listy z filtrem ``terminated``.
    """
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)

    if profile.user == request.user:
        messages.error(request, _("Nie możesz zakończyć własnego zatrudnienia."))
        return redirect("accounts:employee_list")

    reason = (request.POST.get("reason") or "").strip()
    try:
        terminate_employee(profile, reason=reason, actor=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("accounts:employee_list")

    messages.success(
        request,
        _("Pracownik %(name)s zwolniony — sesje skasowane, grupy wyczyszczone.")
        % {"name": profile.user.get_full_name() or profile.user.username},
    )
    return redirect(reverse_lazy("accounts:employee_list") + "?filter=terminated")


@login_required
@permission_required("accounts.delete_employeeprofile", raise_exception=True)
@require_POST
def employee_anonymize_view(request: HttpRequest, pk: int) -> HttpResponse:
    """POST endpoint: anonimizuje pracownika (GDPR Art.17 erasure).

    Wymaga ``delete_employeeprofile`` permission (nie change_) — anonimizacja
    jest nieodwracalna. Wywołuje ``anonymize_employee`` service który najpierw
    terminate'uje konto jeśli aktywne, potem zamienia PII na hash.
    """
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)

    if profile.user == request.user:
        messages.error(request, _("Nie możesz zanonimizować własnego profilu."))
        return redirect("accounts:employee_list")

    try:
        anonymize_employee(profile, actor=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("accounts:employee_list")

    messages.success(
        request,
        _("Profil zanonimizowany zgodnie z RODO (Art.17 — prawo do bycia zapomnianym)."),
    )
    return redirect(reverse_lazy("accounts:employee_list") + "?filter=anonymized")
