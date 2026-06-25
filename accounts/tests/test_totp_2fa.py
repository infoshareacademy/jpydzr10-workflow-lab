"""Testy wymuszenia i przepływu 2FA (TOTP) — django-otp.

Wszystkie testy flipują ``OTP_TESTING_BYPASS=False`` (reszta sufity polega na
domyślnym obejściu z ``settings/test.py``), więc weryfikują REALNE wymuszenie
bez dotykania pozostałych testów logujących przez ``force_login``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.middleware import is_totp_required_for_user
from accounts.models import EmployeeProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _enforce_2fa(settings):
    """Włącza realne wymuszenie 2FA dla całego modułu (reszta sufity je omija)."""
    settings.OTP_TESTING_BYPASS = False
    settings.OTP_ENFORCE_2FA = True


def _make_user(username, function):
    user = User.objects.create_user(username=username, password="secret-pw-123!")
    profile = user.profile
    profile.function = function
    profile.save(update_fields=["function", "updated_at"])
    return user


def _valid_totp(device: TOTPDevice) -> str:
    token = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
    return f"{token:0{device.digits}d}"


# -----------------------------------------------------------------------------
# Predykat wymogu
# -----------------------------------------------------------------------------


class TestRequirementPredicate:
    def test_required_roles(self):
        assert is_totp_required_for_user(_make_user("k", EmployeeProfile.Function.KIEROWNIK))
        assert is_totp_required_for_user(_make_user("m", EmployeeProfile.Function.MAGAZYNIER))

    def test_montazysta_exempt(self):
        assert not is_totp_required_for_user(_make_user("t", EmployeeProfile.Function.MONTAZYSTA))

    def test_superuser_required(self):
        admin = User.objects.create_superuser("admin", "a@a.test", "secret-pw-123!")
        assert is_totp_required_for_user(admin)


# -----------------------------------------------------------------------------
# Wymuszenie w middleware
# -----------------------------------------------------------------------------


class TestEnforcement:
    def test_required_user_without_device_redirected_to_setup(self, client):
        user = _make_user("kier1", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/maszyny/")
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_setup")

    def test_montazysta_not_redirected(self, client):
        user = _make_user("mont1", EmployeeProfile.Function.MONTAZYSTA)
        client.force_login(user)
        # Profil dostępny bez 2FA — montażysta jest zwolniony.
        response = client.get(reverse("accounts:profile"))
        assert response.status_code == 200

    def test_allow_listed_paths_reachable_without_2fa(self, client):
        user = _make_user("kier2", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        # Sama ścieżka setupu nie może wpadać w pętlę przekierowań.
        assert client.get(reverse("accounts:2fa_setup")).status_code == 200

    def test_bypass_flag_disables_enforcement(self, client):
        user = _make_user("kier3", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        with override_settings(OTP_TESTING_BYPASS=True):
            assert client.get("/maszyny/").status_code == 200


# -----------------------------------------------------------------------------
# Setup → confirm → recovery
# -----------------------------------------------------------------------------


class TestSetupFlow:
    def test_setup_confirms_device_and_issues_recovery_codes(self, client):
        user = _make_user("kier4", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        # GET tworzy niepotwierdzone urządzenie.
        client.get(reverse("accounts:2fa_setup"))
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        response = client.post(reverse("accounts:2fa_setup"), {"token": _valid_totp(device)})
        assert response.status_code == 200
        device.refresh_from_db()
        assert device.confirmed
        # 10 kodów zapasowych powstało.
        static_device = StaticDevice.objects.get(user=user, name="recovery")
        assert static_device.token_set.count() == 10
        # Po setupie sesja jest zweryfikowana — chroniona strona dostępna.
        assert client.get("/maszyny/").status_code == 200

    def test_setup_rejects_bad_token(self, client):
        user = _make_user("kier5", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        client.get(reverse("accounts:2fa_setup"))
        response = client.post(reverse("accounts:2fa_setup"), {"token": "000000"})
        assert response.status_code == 200
        assert not TOTPDevice.objects.get(user=user).confirmed


# -----------------------------------------------------------------------------
# Verify (TOTP + recovery)
# -----------------------------------------------------------------------------


class TestVerifyFlow:
    def test_verify_with_totp(self, client):
        user = _make_user("kier6", EmployeeProfile.Function.KIEROWNIK)
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        response = client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(device)})
        assert response.status_code == 302
        assert client.get("/maszyny/").status_code == 200

    def test_verify_with_recovery_code_one_time(self, client):
        user = _make_user("kier7", EmployeeProfile.Function.KIEROWNIK)
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        static_device = StaticDevice.objects.create(user=user, name="recovery")
        static_device.token_set.create(token="zapas1234")
        client.force_login(user)
        # Pierwsze użycie kodu zapasowego — sukces.
        response = client.post(reverse("accounts:2fa_verify"), {"token": "zapas1234"})
        assert response.status_code == 302
        # Drugie użycie tego samego kodu — odrzucone (jednorazowy).
        client.logout()
        client.force_login(user)
        response2 = client.post(reverse("accounts:2fa_verify"), {"token": "zapas1234"})
        assert response2.status_code == 200  # zostaje na stronie weryfikacji
