"""Testy integracji obserwowalności (GlitchTip / Sentry SDK).

Inicjalizacja SDK jest sterowana ``SENTRY_DSN`` i POMIJANA pod pytest — testy
weryfikują, że bez DSN nic się nie inicjalizuje, że ``before_send`` wycina
wrażliwe pola, oraz że wyzwalacz ``/debug/boom/`` jest dostępny tylko dla admina.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from planer_config.settings.base import _sentry_before_send

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_sentry_dsn_unset_in_tests():
    """W środowisku testowym DSN nie jest ustawiony → SDK nie inicjalizowane."""
    assert getattr(settings, "SENTRY_DSN", None) in (None, "")


def test_before_send_redacts_sensitive_fields():
    event = {
        "request": {
            "data": {"password": "tajne123", "username": "jan"},
            "headers": {"Authorization": "Bearer abc", "Accept": "text/html"},
        },
        "extra": {"api_key": "AIzaSECRET", "note": "ok"},
    }
    scrubbed = _sentry_before_send(event, {})
    assert scrubbed["request"]["data"]["password"] == "[redacted]"
    assert scrubbed["request"]["data"]["username"] == "jan"
    assert scrubbed["request"]["headers"]["Authorization"] == "[redacted]"
    assert scrubbed["request"]["headers"]["Accept"] == "text/html"
    assert scrubbed["extra"]["api_key"] == "[redacted]"
    assert scrubbed["extra"]["note"] == "ok"


def test_before_send_handles_event_without_request():
    event = {"message": "coś poszło nie tak"}
    assert _sentry_before_send(event, {}) == event


def test_debug_boom_forbidden_for_non_superuser(client):
    user = User.objects.create_user("zwykly", password="x")
    client.force_login(user)
    response = client.get("/debug/boom/")
    # user_passes_test przekierowuje niespełniających predykatu (302 na login).
    assert response.status_code in (302, 403)


def test_debug_boom_raises_for_superuser(client):
    admin = User.objects.create_superuser("adminobs", "a@a.test", "x")
    client.force_login(admin)
    with pytest.raises(RuntimeError):
        client.get("/debug/boom/")
