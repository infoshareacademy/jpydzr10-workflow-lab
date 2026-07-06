"""Testy self-service UI PIN-u głosowego (widok ``voice_pin_view``).

Weryfikują pełny przepływ: dostęp tylko dla zalogowanych, poprawny zapis
(hash + verify), odrzucenie niezgodnych/trywialnych/nie-cyfrowych PIN-ów oraz
zmianę istniejącego PIN-u. PIN nigdy nie jest renderowany jawnie.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from accounts.services import set_voice_pin, verify_voice_pin

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user("pinui", "pinui@a.test", "pw-1234!Tajne")


@pytest.mark.django_db
class TestVoicePinUI:
    def test_anonymous_redirected_to_login(self, client):
        resp = client.get(reverse("accounts:voice_pin"))
        assert resp.status_code == 302
        assert "/login/" in resp.url

    def test_get_shows_form(self, client, user):
        client.force_login(user)
        resp = client.get(reverse("accounts:voice_pin"))
        assert resp.status_code == 200
        assert b"new_pin" in resp.content
        assert b"confirm_pin" in resp.content

    def test_set_valid_pin(self, client, user):
        client.force_login(user)
        resp = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "4821", "confirm_pin": "4821"}
        )
        assert resp.status_code == 302
        assert resp.url == reverse("accounts:profile")
        user.profile.refresh_from_db()
        assert verify_voice_pin(user.profile, "4821")

    def test_mismatch_rejected(self, client, user):
        client.force_login(user)
        resp = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "4821", "confirm_pin": "9999"}
        )
        assert resp.status_code == 200  # re-render z błędem, bez redirectu
        user.profile.refresh_from_db()
        assert not user.profile.voice_pin_hash

    def test_trivial_pin_rejected(self, client, user):
        client.force_login(user)
        resp = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "1234", "confirm_pin": "1234"}
        )
        assert resp.status_code == 200
        user.profile.refresh_from_db()
        assert not user.profile.voice_pin_hash

    def test_non_numeric_rejected(self, client, user):
        client.force_login(user)
        resp = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "abcd", "confirm_pin": "abcd"}
        )
        assert resp.status_code == 200
        user.profile.refresh_from_db()
        assert not user.profile.voice_pin_hash

    def test_change_existing_pin(self, client, user):
        set_voice_pin(user.profile, "1122")
        client.force_login(user)
        resp = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "7788", "confirm_pin": "7788"}
        )
        assert resp.status_code == 302
        user.profile.refresh_from_db()
        assert verify_voice_pin(user.profile, "7788")
        assert not verify_voice_pin(user.profile, "1122")  # stary PIN unieważniony

    def test_profile_shows_pin_status(self, client, user):
        set_voice_pin(user.profile, "8080")
        client.force_login(user)
        resp = client.get(reverse("accounts:profile"))
        assert resp.status_code == 200
        assert resp.context["has_voice_pin"] is True

    def test_rate_limited_after_10_per_hour(self, client):
        # Ustawianie PIN-u to zapis sekretu — musi mieć limit (jak login/eksport RODO).
        # 10 POST/h przechodzi, 11. jest blokowany (429), by zalogowany user nie spamował.
        from django.core.cache import cache

        cache.clear()  # świeży licznik ratelimit dla izolacji testu
        rl_user = User.objects.create_user("pin_rl", "pinrl@a.test", "pw-1234!Tajne")
        client.force_login(rl_user)
        for i in range(10):
            pin = f"73{i:02d}"
            resp = client.post(reverse("accounts:voice_pin"), {"new_pin": pin, "confirm_pin": pin})
            assert resp.status_code in (200, 302)  # ustawienie/re-render, nie zablokowane
        blocked = client.post(
            reverse("accounts:voice_pin"), {"new_pin": "7399", "confirm_pin": "7399"}
        )
        assert blocked.status_code in (403, 429)  # limit przekroczony


@pytest.mark.django_db
class TestAdminResetVoicePin:
    """Admin reset PIN-u głosowego — gdy pracownik zapomni PIN.

    Admin kasuje hash (nie ustawia nowego — nie zna cudzego); pracownik ustawia
    nowy self-service. Zdarzenie w dzienniku, ale wartość hasha jest maskowana.
    """

    def _target_with_pin(self):
        target = User.objects.create_user("forgot", "forgot@a.test", "pw-1234!Tajne")
        set_voice_pin(target.profile, "4821")
        target.profile.refresh_from_db()
        assert target.profile.voice_pin_hash  # PIN jest ustawiony
        return target

    def test_admin_clears_employee_pin(self, client):
        admin = User.objects.create_superuser("admin_rst", "adm@a.test", "pw-1234!Tajne")
        target = self._target_with_pin()
        client.force_login(admin)
        resp = client.post(reverse("accounts:employee_clear_voice_pin", args=[target.profile.pk]))
        assert resp.status_code == 302
        assert resp.url == reverse("accounts:employee_list")
        target.profile.refresh_from_db()
        assert target.profile.voice_pin_hash == ""  # PIN skasowany w bazie
        assert verify_voice_pin(target.profile, "4821") is False

    def test_requires_change_permission(self, client):
        # Zwykły użytkownik bez uprawnienia → 403 (nie może resetować cudzych PIN-ów).
        plain = User.objects.create_user("plain_rst", "plain@a.test", "pw-1234!Tajne")
        target = self._target_with_pin()
        client.force_login(plain)
        resp = client.post(reverse("accounts:employee_clear_voice_pin", args=[target.profile.pk]))
        assert resp.status_code == 403
        target.profile.refresh_from_db()
        assert target.profile.voice_pin_hash  # PIN NIETKNIĘTY

    def test_permission_grants_access_without_superuser(self, client):
        # Dokładnie ``change_employeeprofile`` odblokowuje akcję (nie tylko superuser).
        staff = User.objects.create_user("staff_rst", "staff@a.test", "pw-1234!Tajne")
        staff.user_permissions.add(Permission.objects.get(codename="change_employeeprofile"))
        target = self._target_with_pin()
        client.force_login(staff)
        resp = client.post(reverse("accounts:employee_clear_voice_pin", args=[target.profile.pk]))
        assert resp.status_code == 302
        target.profile.refresh_from_db()
        assert target.profile.voice_pin_hash == ""

    def test_idempotent_when_no_pin(self, client):
        admin = User.objects.create_superuser("admin_np", "admnp@a.test", "pw-1234!Tajne")
        target = User.objects.create_user("nopin", "nopin@a.test", "pw-1234!Tajne")
        assert not target.profile.voice_pin_hash  # nigdy nie miał PIN
        client.force_login(admin)
        resp = client.post(reverse("accounts:employee_clear_voice_pin", args=[target.profile.pk]))
        assert resp.status_code == 302  # bez błędu — idempotentne

    def test_audit_masks_pin_hash(self, client):
        # Kasowanie PIN loguje FAKT zmiany, ale NIGDY hasha (sekret) do dziennika.
        from core.models import AuditLogEntry

        admin = User.objects.create_superuser("admin_aud", "adma@a.test", "pw-1234!Tajne")
        target = self._target_with_pin()
        old_hash = target.profile.voice_pin_hash
        client.force_login(admin)
        client.post(reverse("accounts:employee_clear_voice_pin", args=[target.profile.pk]))

        entry = AuditLogEntry.objects.filter(
            action="accounts:employee_clear_voice_pin",
            object_type="accounts.EmployeeProfile",
        ).first()
        assert entry is not None  # zdarzenie zapisane (actor = admin)
        assert entry.user_id == admin.pk
        blob = str(entry.changes)
        assert "pbkdf2" not in blob  # hash NIE w dzienniku
        assert old_hash not in blob
        assert "<ustawiony>" in blob  # tylko znacznik zmiany (ustawiony → pusty)
        assert "<pusty>" in blob
