"""Testy integracji obserwowalności (GlitchTip / Sentry SDK).

Inicjalizacja SDK jest sterowana ``SENTRY_DSN`` i POMIJANA pod pytest — testy
weryfikują, że bez DSN nic się nie inicjalizuje, że ``before_send`` wycina
DOKŁADNIE wrażliwe pola (i NIE redaguje legalnych), oraz że wyzwalacz
``/debug/boom/`` jest dostępny tylko dla zalogowanego admina.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from planer_config.settings.base import _sentry_before_send

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_sentry_dsn_unset_in_tests():
    """Konfiguracja środowiska testowego: DSN nie jest ustawiony.

    To check konfiguracyjny (nie behawioralny) — gdy DSN jest pusty, blok
    ``if SENTRY_DSN and not _RUNNING_TESTS`` w ``base.py`` nie wykonuje
    ``sentry_sdk.init()``. ``test_sentry_sdk_not_initialized_under_pytest``
    weryfikuje skutek behawioralny.
    """
    assert getattr(settings, "SENTRY_DSN", None) in (None, "")


def test_sentry_sdk_not_initialized_under_pytest():
    """Behawioralnie: pod pytest SDK NIE jest zainicjalizowane (brak aktywnego klienta).

    Gdyby warunek inicjalizacji był błędny (np. odpalał init mimo testów),
    ``sentry_sdk.Hub`` miałby aktywnego klienta z DSN — tu sprawdzamy, że nie ma.
    """
    sentry_sdk = pytest.importorskip("sentry_sdk")
    # sentry-sdk 2.x API — Hub jest deprecated; get_client() zwraca aktywnego
    # klienta (lub NonRecordingClient gdy SDK nieinicjalizowane).
    client = sentry_sdk.get_client()
    # Brak działającego klienta albo klient bez DSN — w obu przypadkach
    # zdarzenia nie lecą do Sentry.
    assert not client.is_active() or getattr(client, "dsn", None) in (None, "")


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


def test_before_send_does_not_redact_lookalike_keys():
    """Dopasowanie po DOKŁADNEJ nazwie klucza — nie po podłańcuchu.

    Kluczowy regres: stare dopasowanie substringowe redagowało legalne pola,
    których nazwa tylko ZAWIERA słowo wrażliwe (``session_tokens`` → ``token``,
    ``api_key_hash`` → ``api_key``, ``user_secret_answer`` → ``secret``).
    Po przejściu na exact-match te wartości MUSZĄ przetrwać.
    """
    event = {
        "extra": {
            "session_tokens": 3,
            "api_key_hash": "sha256:abc",
            "user_secret_answer": "blue",
            "tokens_remaining": 7,
            "secret": "REALSECRET",  # dokładny klucz → redagowany
            "token": "REALTOKEN",  # dokładny klucz → redagowany
        }
    }
    scrubbed = _sentry_before_send(event, {})
    extra = scrubbed["extra"]
    assert extra["session_tokens"] == 3
    assert extra["api_key_hash"] == "sha256:abc"
    assert extra["user_secret_answer"] == "blue"
    assert extra["tokens_remaining"] == 7
    assert extra["secret"] == "[redacted]"
    assert extra["token"] == "[redacted]"


def test_before_send_case_insensitive_keys():
    """Redakcja jest niewrażliwa na wielkość liter w nazwie klucza."""
    event = {"extra": {"AUTHORIZATION": "x", "Password": "y", "Api_Key": "z"}}
    scrubbed = _sentry_before_send(event, {})
    assert scrubbed["extra"]["AUTHORIZATION"] == "[redacted]"
    assert scrubbed["extra"]["Password"] == "[redacted]"
    assert scrubbed["extra"]["Api_Key"] == "[redacted]"


def test_before_send_redacts_nested_breadcrumbs():
    """Rekurencyjna redakcja sięga list słowników (np. ``breadcrumbs``)."""
    event = {
        "breadcrumbs": [
            {"category": "auth", "data": {"token": "secret1", "ok": "tak"}},
            {"category": "http", "data": {"api_key": "secret2", "url": "/x"}},
        ],
    }
    scrubbed = _sentry_before_send(event, {})
    assert scrubbed["breadcrumbs"][0]["data"]["token"] == "[redacted]"
    assert scrubbed["breadcrumbs"][0]["data"]["ok"] == "tak"
    assert scrubbed["breadcrumbs"][1]["data"]["api_key"] == "[redacted]"
    assert scrubbed["breadcrumbs"][1]["data"]["url"] == "/x"


def test_before_send_handles_event_without_request():
    """Event bez pól wrażliwych zostaje nietknięty (ten sam obiekt, te same pola)."""
    event = {"message": "coś poszło nie tak"}
    result = _sentry_before_send(event, {})
    assert result is event
    assert "request" not in result
    assert "extra" not in result
    assert result["message"] == "coś poszło nie tak"


def test_debug_boom_redirects_anonymous_user(client):
    """Anonim (bez logowania) → 302 na stronę logowania, NIE rzuca wyjątkiem."""
    response = client.get("/debug/boom/")
    assert response.status_code == 302
    assert "login" in response.url


def test_debug_boom_forbidden_for_non_superuser(client):
    """Zalogowany nie-superuser → 302 na login (predykat ``user_passes_test`` zawodzi).

    ``user_passes_test`` przekierowuje KAŻDEGO użytkownika niespełniającego
    predykatu na ``LOGIN_URL`` (302), także już zalogowanego — to nie jest 403.
    """
    user = User.objects.create_user("zwykly", password="x")
    client.force_login(user)
    response = client.get("/debug/boom/")
    assert response.status_code == 302
    assert "login" in response.url


def test_debug_boom_raises_for_superuser(client):
    """Superuser → widok wykonuje się i rzuca dokładny RuntimeError (test GlitchTip)."""
    admin = User.objects.create_superuser("adminobs", "a@a.test", "x")
    client.force_login(admin)
    with pytest.raises(RuntimeError, match="Celowy wyjątek testowy GlitchTip"):
        client.get("/debug/boom/")
