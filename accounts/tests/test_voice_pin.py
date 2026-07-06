"""PIN głosowy — set_voice_pin / verify_voice_pin + scrub RODO przy anonimizacji.

PIN jest DRUGIM czynnikiem uwierzytelnienia w agencie głosowym (obok caller-ID).
Hash PBKDF2 (nigdy plaintext); anonimizacja RODO kasuje hash (bieżący + historia).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.services import (
    anonymize_employee,
    clear_voice_pin,
    set_voice_pin,
    verify_voice_pin,
)

User = get_user_model()


@pytest.fixture
def profile(db):
    u = User.objects.create_user("pinuser", password="x")
    return u.profile


@pytest.mark.django_db
class TestVoicePin:
    def test_set_and_verify_ok(self, profile):
        set_voice_pin(profile, "4821")
        profile.refresh_from_db()
        assert profile.voice_pin_hash  # hash niepusty
        assert profile.voice_pin_hash != "4821"  # NIGDY plaintext
        assert verify_voice_pin(profile, "4821") is True
        assert verify_voice_pin(profile, "9999") is False

    def test_verify_false_when_no_pin(self, profile):
        # Brak skonfigurowanego PIN → weryfikacja zawsze False (fail-closed).
        assert verify_voice_pin(profile, "4821") is False

    def test_rejects_non_digits(self, profile):
        with pytest.raises(ValidationError):
            set_voice_pin(profile, "abcd")

    def test_rejects_too_short_and_too_long(self, profile):
        with pytest.raises(ValidationError):
            set_voice_pin(profile, "12")
        with pytest.raises(ValidationError):
            set_voice_pin(profile, "1234567")

    def test_rejects_trivial(self, profile):
        for bad in ["1234", "123456", "0000", "1111", "121212"]:
            with pytest.raises(ValidationError):
                set_voice_pin(profile, bad)

    def test_accepts_six_digits(self, profile):
        set_voice_pin(profile, "482913")
        assert verify_voice_pin(profile, "482913") is True

    def test_anonymize_scrubs_pin(self, profile):
        set_voice_pin(profile, "4821")
        profile.refresh_from_db()
        assert profile.voice_pin_hash  # jest PIN
        anonymize_employee(profile)
        profile.refresh_from_db()
        assert profile.voice_pin_hash == ""  # RODO: bieżący hash wykasowany
        # Historia (django-simple-history) też nie trzyma już hasha PIN-u.
        assert not profile.history.exclude(voice_pin_hash="").exists()

    def test_clear_voice_pin_removes_hash(self, profile):
        # Ścieżka „admin reset": pracownik zapomniał PIN → admin kasuje hash.
        set_voice_pin(profile, "4821")
        profile.refresh_from_db()
        assert clear_voice_pin(profile) is True  # PIN istniał → skasowany
        profile.refresh_from_db()
        assert profile.voice_pin_hash == ""
        assert verify_voice_pin(profile, "4821") is False  # stary PIN nie działa

    def test_clear_voice_pin_idempotent_when_no_pin(self, profile):
        # Brak PIN-u → False, żadnego zapisu (idempotentne).
        assert clear_voice_pin(profile) is False
        profile.refresh_from_db()
        assert profile.voice_pin_hash == ""
