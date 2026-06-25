"""Widoki konfiguracji i weryfikacji 2FA (TOTP) — django-otp.

Trzy ścieżki:

* :func:`two_factor_setup` — rejestracja urządzenia TOTP (QR + ręczny sekret),
  potwierdzenie kodem, wygenerowanie 10 kodów zapasowych.
* :func:`two_factor_verify` — weryfikacja drugiego składnika przy logowaniu
  (kod z aplikacji TOTP albo jednorazowy kod zapasowy).
* :func:`recovery_codes_download` — pobranie kodów zapasowych jako pliku TXT.
"""

from __future__ import annotations

import base64
import io

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

RECOVERY_CODE_COUNT = 10
_SESSION_RECOVERY_KEY = "_2fa_recovery_codes"


def _build_qr_data_uri(device: TOTPDevice) -> str:
    """Zwraca kod QR z ``otpauth://`` jako data-URI (base64 PNG) — działa pod CSP
    ``img-src 'self' data:`` bez dodatkowych żądań sieciowych."""
    img = qrcode.make(device.config_url)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _manual_secret(device: TOTPDevice) -> str:
    """Sekret base32 do ręcznego wpisania, gdy nie można zeskanować QR."""
    return base64.b32encode(device.bin_key).decode()


def _generate_recovery_codes(user, count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Tworzy świeży zestaw jednorazowych kodów zapasowych (StaticToken)."""
    static_device, _created = StaticDevice.objects.get_or_create(user=user, name="recovery")
    static_device.token_set.all().delete()
    codes: list[str] = []
    for _i in range(count):
        token = StaticToken.random_token()
        static_device.token_set.create(token=token)
        codes.append(token)
    return codes


@login_required
def two_factor_setup(request):
    """Rejestracja urządzenia TOTP. Potwierdzenie kodem → kody zapasowe."""
    user = request.user
    if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        # Urządzenie już potwierdzone — przejdź do weryfikacji sesji.
        return redirect("accounts:2fa_verify")

    device, _created = TOTPDevice.objects.get_or_create(user=user, name="default", confirmed=False)

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip()
        allowed, _meta = device.verify_is_allowed()
        if allowed and token and device.verify_token(token):
            device.confirmed = True
            device.save()
            otp_login(request, device)
            codes = _generate_recovery_codes(user)
            request.session[_SESSION_RECOVERY_KEY] = codes
            return render(request, "accounts/2fa_recovery.html", {"codes": codes})
        messages.error(request, _("Nieprawidłowy kod. Spróbuj ponownie."))

    return render(
        request,
        "accounts/2fa_setup.html",
        {"qr_data_uri": _build_qr_data_uri(device), "secret": _manual_secret(device)},
    )


@login_required
def two_factor_verify(request):
    """Weryfikacja drugiego składnika: kod TOTP albo kod zapasowy."""
    user = request.user
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        return redirect("accounts:2fa_setup")
    if user.is_verified():
        return redirect("home")

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip()
        allowed, _meta = device.verify_is_allowed()
        if allowed and token and device.verify_token(token):
            otp_login(request, device)
            return redirect("home")
        # Fallback: jednorazowy kod zapasowy ze StaticDevice.
        static_device = StaticDevice.objects.filter(user=user, name="recovery").first()
        if static_device and token and static_device.verify_token(token):
            otp_login(request, static_device)
            return redirect("home")
        messages.error(request, _("Nieprawidłowy kod uwierzytelniający lub zapasowy."))

    return render(request, "accounts/2fa_verify.html", {})


@login_required
def recovery_codes_download(request):
    """Pobranie wygenerowanych kodów zapasowych jako pliku TXT (jednorazowo)."""
    codes = request.session.get(_SESSION_RECOVERY_KEY)
    if not codes:
        return redirect("home")
    content = "\n".join(codes) + "\n"
    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kody-zapasowe-2fa.txt"'
    return response
