"""Widoki aplikacji accounts (login, logout, profile, employee management)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
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
from django_otp import devices_for_user
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_ratelimit.decorators import ratelimit

from core.pagination import PerPageMixin
from core.service_errors import add_form_errors

from .forms import (
    BilingualPasswordResetForm,
    PlanerAuthenticationForm,
    ProfileForm,
    RegisterEmployeeForm,
    VoicePinForm,
)
from .models import EmployeeProfile
from .services import (
    anonymize_employee,
    clear_voice_pin,
    register_employee,
    set_voice_pin,
    terminate_employee,
    update_profile,
)


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


# --- Reset hasła („zapomniałem hasła") — 4 kroki standardowego flow Django,
#     z firmowymi szablonami i dwujęzycznym mailem (BilingualPasswordResetForm).
#     Dostępne dla niezalogowanych (middleware 2FA nie dotyczy anonimowych).


@method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST", block=True),
    name="dispatch",
)
class PlanerPasswordResetView(PasswordResetView):
    """Krok 1: formularz adresu e-mail → wysyłka linku resetującego.

    Rate-limit 5 prób POST / godzinę per IP chroni przed nadużyciem wysyłki
    maili (i przed próbą enumeracji kont). Sama klasa bazowa nie ujawnia, czy
    adres istnieje — zawsze przekierowuje na stronę „wysłano".
    """

    template_name = "accounts/password_reset.html"
    form_class = BilingualPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class PlanerPasswordResetDoneView(PasswordResetDoneView):
    """Krok 2: potwierdzenie „jeśli konto istnieje, mail został wysłany"."""

    template_name = "accounts/password_reset_done.html"


class PlanerPasswordResetConfirmView(PasswordResetConfirmView):
    """Krok 3: ustawienie nowego hasła (po kliknięciu linku z maila)."""

    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PlanerPasswordResetCompleteView(PasswordResetCompleteView):
    """Krok 4: hasło zmienione — link do ponownego logowania."""

    template_name = "accounts/password_reset_complete.html"


@login_required
def profile(request):
    """Widok profilu zalogowanego użytkownika (podgląd + edycja podstawowych danych).

    Aktualizacja delegowana do ``update_profile`` (service layer) — daje spójne
    walidowanie i jeden punkt do podpięcia audytu / history.
    """
    # Sygnał ``post_save`` tworzy profil dla każdego usera — ale defensywnie
    # (spójnie z resztą widoków) obsługujemy konto bez profilu zamiast 500.
    employee_profile = getattr(request.user, "profile", None)
    if employee_profile is None:
        messages.error(request, _("Brak profilu pracownika dla tego konta."))
        return redirect("home")

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=employee_profile)
        if form.is_valid():
            update_profile(employee_profile, **form.cleaned_data)
            # Zmiana języka w profilu od razu przełącza UI (utrwalenie w cookie).
            response = redirect("accounts:profile")
            return _apply_language_cookie(response, employee_profile.preferred_language)
    else:
        form = ProfileForm(instance=employee_profile)

    has_2fa = any(
        isinstance(device, TOTPDevice) for device in devices_for_user(request.user, confirmed=True)
    )

    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "profile": employee_profile,
            "has_2fa": has_2fa,
            "has_voice_pin": bool(employee_profile.voice_pin_hash),
        },
    )


@login_required
@ratelimit(key="user", rate="10/h", method="POST", block=True)
def voice_pin_view(request):
    """Self-service: użytkownik ustawia lub zmienia własny PIN głosowy (DTMF).

    PIN jest drugim czynnikiem agenta telefonicznego (po caller-ID). Zapis
    delegowany do ``set_voice_pin`` (hash + reguły trywialności); nigdy nie
    przechowujemy ani nie renderujemy PIN-u jawnie.
    """
    profile = getattr(request.user, "profile", None)
    if profile is None:
        messages.error(request, _("Brak profilu pracownika dla tego konta."))
        return redirect("home")

    if request.method == "POST":
        form = VoicePinForm(request.POST)
        if form.is_valid():
            try:
                set_voice_pin(profile, form.cleaned_data["new_pin"], actor=request.user)
            except ValidationError as exc:
                form.add_error("new_pin", exc.messages[0])
            else:
                messages.success(request, _("PIN głosowy został zapisany."))
                return redirect("accounts:profile")
    else:
        form = VoicePinForm()

    return render(
        request,
        "accounts/voice_pin.html",
        {"form": form, "has_pin": bool(profile.voice_pin_hash)},
    )


def email_preferences_view(request):
    """Zarządzanie zgodami na nieobowiązkowe maile + obsługa „wypisz się".

    Tożsamość ustalana dwojako: (a) podpisany token z linku w mailu (działa bez
    logowania, dotyczy konkretnego konta), albo (b) zalogowany użytkownik
    zarządzający własnymi preferencjami. Bez żadnego z tych źródeł → przekierowanie
    na logowanie. Token jest re-walidowany przy POST (nie ufamy ukrytemu polu).
    """
    from core.email_optout import CATEGORY_LABELS, parse_unsubscribe_token

    user_model = get_user_model()
    token = request.POST.get("token") or request.GET.get("token") or ""
    focus_category = None
    target_user = None

    if token:
        parsed = parse_unsubscribe_token(token)
        if parsed is None:
            return render(request, "accounts/email_preferences.html", {"invalid_token": True})
        uid, focus_category = parsed
        target_user = user_model.objects.filter(pk=uid).select_related("profile").first()

    if target_user is None:
        if request.user.is_authenticated:
            target_user = request.user
            token = ""  # zalogowany zarządza sobą — token zbędny
        else:
            return redirect(f"{reverse_lazy('accounts:login')}?next={request.path}")

    profile = getattr(target_user, "profile", None)
    if profile is None:
        return render(request, "accounts/email_preferences.html", {"invalid_token": True})

    categories = list(CATEGORY_LABELS.items())

    if request.method == "POST":
        # Subskrybowane = zaznaczony checkbox „cat_<klucz>"; brak = rezygnacja.
        opted_out = [key for key, _label in categories if not request.POST.get(f"cat_{key}")]
        profile.email_opt_outs = opted_out
        profile.save(update_fields=["email_opt_outs"])
        messages.success(request, _("Zapisano preferencje e-mail."))
        # Po zapisie pokaż aktualny stan (zachowaj token w URL gdy anonimowo).
        url = reverse_lazy("accounts:email_preferences")
        return redirect(f"{url}?token={token}" if token else url)

    opt_outs = set(profile.email_opt_outs or [])
    rows = [
        {"key": key, "label": label, "subscribed": key not in opt_outs} for key, label in categories
    ]
    return render(
        request,
        "accounts/email_preferences.html",
        {
            "rows": rows,
            "token": token,
            "focus_category": focus_category,
            "focus_label": dict(CATEGORY_LABELS).get(focus_category),
            "account_label": target_user.get_username(),
        },
    )


@login_required
@require_POST
@ratelimit(key="user", rate="1/d", method="POST", block=True)
def data_export_view(request):
    """Eksport danych zalogowanego użytkownika (RODO Art. 20 — przenoszalność).

    Zwraca komplet danych usera w formacie JSON (do pobrania): konto, profil,
    rezerwacje utworzone przez niego oraz wpisy dziennika zdarzeń go dotyczące.
    Samoobsługowo — każdy widzi WYŁĄCZNIE własne dane.

    Tylko POST (CSRF + brak przypadkowego wyzwolenia przez prefetch/crawler na
    GET) oraz rate-limit 1×/dobę per użytkownik — eksport jest idempotentny
    (te same dane), a dzienna kadencja wystarcza dla prawa do przenoszalności.
    """
    from core.models import AuditLogEntry
    from reservations.models import Reservation

    user = request.user
    # Defensywnie (spójnie z resztą widoków) — konto bez profilu nie wywraca eksportu.
    profile = getattr(user, "profile", None)
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
            "function": profile.function if profile else None,
            "phone": profile.phone if profile else None,
            "employee_id": profile.employee_id if profile else None,
            "preferred_language": profile.preferred_language if profile else None,
            "theme_preference": profile.theme_preference if profile else None,
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


@login_required
@permission_required("accounts.change_employeeprofile", raise_exception=True)
@require_POST
def employee_clear_voice_pin_view(request: HttpRequest, pk: int) -> HttpResponse:
    """POST endpoint: admin czyści PIN głosowy pracownika (gdy pracownik go zapomniał).

    Nie ustawia nowego PIN (admin nie zna cudzego sekretu) — tylko kasuje hash;
    pracownik ustawia nowy sam w swoim profilu. To nie-destrukcyjna alternatywa
    dla anonimizacji. Zdarzenie trafia do dziennika (actor = admin, obiekt = profil)
    przez ``AuditLogMiddleware``; wartość hasha jest maskowana (``core.audit``).
    """
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)
    cleared = clear_voice_pin(profile, actor=request.user)

    name = profile.user.get_full_name() or profile.user.username
    if cleared:
        messages.success(
            request,
            _("PIN głosowy pracownika %(name)s wyczyszczony — może ustawić nowy w swoim profilu.")
            % {"name": name},
        )
    else:
        messages.info(
            request,
            _("Pracownik %(name)s nie miał ustawionego PIN głosowego.") % {"name": name},
        )
    return redirect("accounts:employee_list")
