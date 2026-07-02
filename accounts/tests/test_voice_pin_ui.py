"""Testy self-service UI PIN-u głosowego (widok ``voice_pin_view``).

Weryfikują pełny przepływ: dostęp tylko dla zalogowanych, poprawny zapis
(hash + verify), odrzucenie niezgodnych/trywialnych/nie-cyfrowych PIN-ów oraz
zmianę istniejącego PIN-u. PIN nigdy nie jest renderowany jawnie.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
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
