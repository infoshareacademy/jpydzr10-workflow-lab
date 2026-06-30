"""Wymuszenie 2FA (TOTP) dla kont uprzywilejowanych.

Po zalogowaniu administrator / kierownik / magazynier muszą przejść przez drugi
składnik (TOTP) zanim dostaną się do reszty aplikacji. Montażyści (rola
domyślna, read-only) są zwolnieni. Logika opiera się na FUNKCJI konta, nie na
fladze ``is_staff`` — ta ostatnia bywa nadawana niezależnie.
"""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django_otp import user_has_device

from accounts.models import EmployeeProfile

# Funkcje wymagające 2FA. Montażysta (read-only) nie jest tu wymieniony.
_TOTP_REQUIRED_FUNCTIONS = frozenset(
    {
        EmployeeProfile.Function.ADMIN,
        EmployeeProfile.Function.KIEROWNIK,
        EmployeeProfile.Function.MAGAZYNIER,
    }
)

# Ścieżki dostępne BEZ przejścia 2FA. Rozdzielone na dwa rodzaje, by ZAMKNĄĆ
# atak sufiksowy (``/accounts/login`` jako goły prefiks łapałby też hipotetyczne
# ``/accounts/loginAYZ``), zachowując jednocześnie realne trasy z ukośnikiem
# (``/accounts/login/``):
#
# * katalogi (kończą się ``/``) — dopasowanie prefiksowe obejmuje wszystkie
#   podścieżki (statyki, strony setupu/weryfikacji 2FA, i18n, narzędzia debug);
# * trasy (gołe) — dopasowanie KOTWICZONE: pełna równość albo ``trasa + "/"``.
#
# ``/media/`` świadomie NIE jest zwolnione: pliki przesłane (protokoły przeglądów)
# to zasób chroniony — uprawniony użytkownik bez 2FA nie powinien ich pobierać.
_ALLOWED_DIR_PREFIXES = (
    "/accounts/2fa/",
    "/static/",
    "/i18n/",
    "/jsi18n/",
    "/__debug__/",
)
_ALLOWED_EXACT_ROUTES = (
    "/accounts/login",
    "/accounts/logout",
    "/accounts/zablokowane",
    "/admin/login",
    "/admin/logout",
    "/healthz",
    "/debug/boom",
)


def is_totp_required_for_user(user) -> bool:
    """Czy dany użytkownik musi mieć włączone 2FA."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.function in _TOTP_REQUIRED_FUNCTIONS)


class TwoFactorEnforcementMiddleware:
    """Przekierowuje uprawnionych, niezweryfikowanych użytkowników do 2FA.

    Kolejność decyzji (tania → droga), wszystkie flagi czytane w czasie żądania:
    bypass testowy → wyłączone wymuszenie → niezalogowany → rola bez wymogu →
    już zweryfikowany (``is_verified`` z OTPMiddleware) → ścieżka z allow-listy →
    w przeciwnym razie redirect na weryfikację (gdy jest urządzenie) lub setup.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # URL strony głównej jest statyczny — rozwiązujemy go raz przy starcie
        # zamiast wołać ``reverse('home')`` w każdym żądaniu.
        self.home_url = reverse("home")

    def __call__(self, request):
        if self._enforcement_active(request):
            redirect_response = self._enforce(request)
            if redirect_response is not None:
                return redirect_response
        return self.get_response(request)

    @staticmethod
    def _enforcement_active(request) -> bool:
        # Czytane PRZY KAŻDYM żądaniu, żeby @override_settings działał w testach.
        if getattr(settings, "OTP_TESTING_BYPASS", False):
            return False
        return bool(getattr(settings, "OTP_ENFORCE_2FA", True))

    def _enforce(self, request):
        user = request.user
        if not is_totp_required_for_user(user):
            return None
        # OTPMiddleware ustawia ``is_verified`` na zweryfikowanym użytkowniku.
        if user.is_verified():
            return None
        if self._is_allowed_path(request.path):
            return None
        if user_has_device(user, confirmed=True):
            return redirect("accounts:2fa_verify")
        return redirect("accounts:2fa_setup")

    def _is_allowed_path(self, path: str) -> bool:
        if path == self.home_url or path.startswith(_ALLOWED_DIR_PREFIXES):
            return True
        # Trasy gołe: równość albo trasa zakończona ukośnikiem (np.
        # ``/accounts/login/``) — ale NIE ``/accounts/loginXYZ`` (atak sufiksowy).
        return any(path == route or path.startswith(route + "/") for route in _ALLOWED_EXACT_ROUTES)
