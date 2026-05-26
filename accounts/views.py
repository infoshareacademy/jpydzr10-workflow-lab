"""Widoki aplikacji accounts (login, logout, profile)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from django_ratelimit.decorators import ratelimit

from core.service_errors import add_form_errors

from .forms import ProfileForm, RegisterEmployeeForm
from .services import register_employee, update_profile


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
    redirect_authenticated_user = True


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
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=employee_profile)

    return render(
        request,
        "accounts/profile.html",
        {"form": form, "profile": employee_profile},
    )


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
