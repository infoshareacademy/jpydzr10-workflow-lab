"""Testy karty „Bezpieczeństwo" w profilu — status 2FA i kody zapasowe.

Pokrywają realny stan karty bezpieczeństwa (aktywne vs nieaktywne 2FA),
przycisk regeneracji kodów zapasowych dla konta z potwierdzonym TOTP oraz
strażnik regeneracji bez urządzenia (przekierowanie na setup).

``OTP_TESTING_BYPASS`` pozostaje domyślnie ``True`` (z ``settings/test.py``),
więc middleware wymuszające 2FA nie przekierowuje na weryfikację — testujemy
samą kartę profilu, nie przepływ logowania.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.twofactor import RECOVERY_CODE_COUNT

User = get_user_model()

pytestmark = pytest.mark.django_db


def _make_user(username="user1"):
    return User.objects.create_user(username=username, password="secret-pw-123!")


def _confirm_totp(user):
    """Tworzy potwierdzone urządzenie TOTP dla użytkownika."""
    return TOTPDevice.objects.create(user=user, name="default", confirmed=True)


class TestProfileSecurityCard:
    def test_inactive_state_shows_setup_link(self, client):
        user = _make_user()
        client.force_login(user)

        response = client.get(reverse("accounts:profile"))

        assert response.status_code == 200
        assert response.context["has_2fa"] is False
        content = response.content.decode()
        assert "Nieaktywne" in content
        assert reverse("accounts:2fa_setup") in content

    def test_active_state_shows_regenerate_option(self, client):
        user = _make_user()
        _confirm_totp(user)
        client.force_login(user)

        response = client.get(reverse("accounts:profile"))

        assert response.status_code == 200
        assert response.context["has_2fa"] is True
        content = response.content.decode()
        assert "Aktywne" in content
        assert reverse("accounts:2fa_recovery_regenerate") in content

    def test_unconfirmed_totp_does_not_count_as_active(self, client):
        # Urządzenie istnieje, ale nie zostało potwierdzone kodem — karta musi
        # pokazywać stan nieaktywny, inaczej user myśli że ma 2FA gdy nie ma.
        user = _make_user()
        TOTPDevice.objects.create(user=user, name="default", confirmed=False)
        client.force_login(user)

        response = client.get(reverse("accounts:profile"))

        assert response.context["has_2fa"] is False


class TestRecoveryRegenerate:
    def test_regenerate_creates_fresh_tokens_and_invalidates_old(self, client):
        user = _make_user()
        _confirm_totp(user)
        client.force_login(user)

        # Stary zestaw kodów (inny StaticDevice token set), który ma zniknąć.
        old_device = StaticDevice.objects.create(user=user, name="recovery")
        old_device.token_set.create(token="OLD-CODE-001")
        old_tokens = {"OLD-CODE-001"}

        response = client.post(reverse("accounts:2fa_recovery_regenerate"))

        # Redirect na pobranie kodów TXT.
        assert response.status_code == 302
        assert response.url == reverse("accounts:2fa_recovery_download")

        device = StaticDevice.objects.get(user=user, name="recovery")
        new_tokens = set(device.token_set.values_list("token", flat=True))
        assert len(new_tokens) == RECOVERY_CODE_COUNT
        # Stary kod został unieważniony.
        assert new_tokens.isdisjoint(old_tokens)

        # Kody trafiły do sesji i są realnie pobieralne jako plik TXT.
        download = client.get(reverse("accounts:2fa_recovery_download"))
        assert download.status_code == 200
        assert download["Content-Type"].startswith("text/plain")
        body = download.content.decode().split()
        assert set(body) == new_tokens

    def test_regenerate_without_device_redirects_to_setup(self, client):
        user = _make_user()
        client.force_login(user)

        response = client.post(reverse("accounts:2fa_recovery_regenerate"))

        assert response.status_code == 302
        assert response.url == reverse("accounts:2fa_setup")
        # Bez urządzenia TOTP nie powstają żadne kody zapasowe.
        assert not StaticDevice.objects.filter(user=user, name="recovery").exists()

    def test_regenerate_rejects_get(self, client):
        user = _make_user()
        _confirm_totp(user)
        client.force_login(user)

        response = client.get(reverse("accounts:2fa_recovery_regenerate"))

        # @require_POST → 405 dla GET.
        assert response.status_code == 405
