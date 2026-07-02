"""Retry agenta przy błędach PRZEJŚCIOWYCH (Gemini bywa chwilowo rozłączony).

Model potrafi zwrócić jednorazowy ``RemoteProtocolError`` („server disconnected")
~1/28 wywołań. Bez retry chatbot „zawiesza się" na scenie. Weryfikujemy, że:

* błąd przejściowy jest ponawiany raz i rozmowa dociera do odpowiedzi,
* limit prób jest twardy (nie pętla w nieskończoność),
* błąd NIE-przejściowy (auth/limit) NIE jest ponawiany (retry i tak nie pomoże).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from chatbot import agent as agent_module
from chatbot.models import Message
from chatbot.services import _is_transient_agent_error, ask_chatbot

User = get_user_model()


class _RemoteProtocolError(Exception):
    """Nazwa zawiera 'protocol' → klasyfikowana jako przejściowa (jak httpx)."""


class _AuthenticationError(Exception):
    """Nazwa zawiera 'auth' → NIE-przejściowa (błąd konfiguracji klucza)."""


class _FlakyAgent:
    """Rzuca zadany wyjątek pierwsze ``fail_times`` wywołań, potem zwraca wynik."""

    def __init__(self, exc, fail_times, output="Odpowiedź asystenta."):
        self.exc = exc
        self.fail_times = fail_times
        self.output = output
        self.calls = 0

    def run_sync(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return SimpleNamespace(
            output=self.output,
            usage=SimpleNamespace(total_tokens=7),
            all_messages=lambda: [],
        )


@pytest.mark.django_db
class TestAgentRetry:
    def _user(self):
        return User.objects.create_user("retry_user", "r@r.test", "x")

    def test_transient_error_retried_then_succeeds(self, monkeypatch):
        # 1. wywołanie pada (rozłączenie), 2. zwraca odpowiedź → user dostaje treść.
        flaky = _FlakyAgent(_RemoteProtocolError("server disconnected"), fail_times=1)
        monkeypatch.setattr(agent_module, "AGENT", flaky)
        msg = ask_chatbot(user=self._user(), question="Ile mamy koparek w magazynie?")
        assert flaky.calls == 2  # 1 fail + 1 retry
        assert msg.role == Message.Role.ASSISTANT
        assert msg.content == "Odpowiedź asystenta."

    def test_transient_error_exhausts_retries(self, monkeypatch):
        # Uporczywy błąd przejściowy → dokładnie 2 próby, potem grzeczny błąd.
        flaky = _FlakyAgent(_RemoteProtocolError("server disconnected"), fail_times=99)
        monkeypatch.setattr(agent_module, "AGENT", flaky)
        msg = ask_chatbot(user=self._user(), question="Zapytanie testowe do agenta")
        assert flaky.calls == 2  # twardy limit prób
        assert msg.role == Message.Role.ERROR

    def test_nontransient_error_not_retried(self, monkeypatch):
        # Błąd auth (zła konfiguracja) → BEZ retry (ponowienie nic nie da).
        flaky = _FlakyAgent(_AuthenticationError("invalid api_key"), fail_times=99)
        monkeypatch.setattr(agent_module, "AGENT", flaky)
        msg = ask_chatbot(user=self._user(), question="Zapytanie testowe do agenta")
        assert flaky.calls == 1  # brak retry
        assert msg.role == Message.Role.ERROR

    def test_is_transient_classification(self):
        assert _is_transient_agent_error(_RemoteProtocolError("x")) is True
        assert _is_transient_agent_error(TimeoutError("slow")) is True
        assert _is_transient_agent_error(ConnectionError("refused")) is True
        # Auth i limit zapytań są celowo NIE-przejściowe.
        assert _is_transient_agent_error(_AuthenticationError("bad key")) is False

        class _RateLimitError(Exception):
            pass

        assert _is_transient_agent_error(_RateLimitError("429 too many requests")) is False
