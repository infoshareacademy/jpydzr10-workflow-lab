"""Pamięć rozmowy w czacie tekstowym (Pydantic AI ``message_history``).

Bez historii każda wiadomość jest bezstanowa — model gubi kontekst ("sprawdź tę
rezerwację" → "podaj maszynę?"). Weryfikujemy, że kolejna tura widzi poprzednie
wiadomości, że pierwsza tura startuje pusta, i że podczas wiszącej propozycji
(pending) historia NIE jest podawana (żeby nie nadpisać potwierdzenia).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from chatbot import agent as agent_module
from chatbot.models import Conversation, Message
from chatbot.services import ask_chatbot

User = get_user_model()


class _HistoryCapturingAgent:
    """Fake agent zapamiętujący ``message_history`` przekazane do run_sync."""

    def __init__(self, output="Odpowiedź asystenta."):
        self.output = output
        self.last_history = "UNSET"

    def run_sync(self, _prompt, *, deps=None, message_history=None, **_kwargs):
        self.last_history = message_history
        return SimpleNamespace(
            output=self.output,
            usage=SimpleNamespace(total_tokens=5),
            all_messages=lambda: [],
        )


@pytest.fixture
def user(db):
    return User.objects.create_user("histuser", "hist@a.test", "pw-1234!Tajne")


@pytest.mark.django_db
class TestChatHistory:
    def test_first_turn_has_empty_history(self, user, monkeypatch):
        agent = _HistoryCapturingAgent()
        monkeypatch.setattr(agent_module, "AGENT", agent)
        ask_chatbot(user=user, question="Ile koparek jest w magazynie?")
        assert agent.last_history == []  # brak wcześniejszych wiadomości

    def test_second_turn_includes_previous_exchange(self, user, monkeypatch):
        from pydantic_ai.messages import ModelRequest, ModelResponse

        agent = _HistoryCapturingAgent()
        monkeypatch.setattr(agent_module, "AGENT", agent)
        first = ask_chatbot(user=user, question="Jaki status maszyny KOP-001?")
        conv = first.conversation
        ask_chatbot(user=user, question="A sprawdź, czy jest dobrze zapisana.", conversation=conv)
        # Druga tura widzi parę z pierwszej: pytanie usera + odpowiedź asystenta.
        assert len(agent.last_history) == 2
        assert isinstance(agent.last_history[0], ModelRequest)  # user T1
        assert isinstance(agent.last_history[1], ModelResponse)  # assistant T1
        # Bieżące pytanie (T2) NIE jest w historii — idzie jako prompt.
        rendered = str(agent.last_history)
        assert "KOP-001" in rendered  # kontekst z T1 dotarł
        assert "dobrze zapisana" not in rendered  # T2 nie zdublowane w historii

    def test_history_excludes_error_messages(self, user, monkeypatch):
        agent = _HistoryCapturingAgent()
        monkeypatch.setattr(agent_module, "AGENT", agent)
        conv = Conversation.objects.create(user=user, title="t")
        Message.objects.create(conversation=conv, role=Message.Role.USER, content="Pytanie A")
        Message.objects.create(
            conversation=conv, role=Message.Role.ASSISTANT, content="Odpowiedź A"
        )
        Message.objects.create(conversation=conv, role=Message.Role.ERROR, content="Błąd sieci")
        ask_chatbot(user=user, question="Pytanie B", conversation=conv)
        # 2 wpisy (user A + assistant A); ERROR pominięty, bieżące pytanie wykluczone.
        assert len(agent.last_history) == 2

    def test_pending_action_skips_history(self, user, monkeypatch):
        agent = _HistoryCapturingAgent()
        monkeypatch.setattr(agent_module, "AGENT", agent)
        conv = Conversation.objects.create(user=user, title="t")
        Message.objects.create(conversation=conv, role=Message.Role.USER, content="Wcześniejsze")
        Message.objects.create(
            conversation=conv, role=Message.Role.ASSISTANT, content="Wcześniejsza odp"
        )
        conv.pending_action = {"action": "create_reservation", "params": {}}
        conv.save(update_fields=["pending_action"])
        # Pytanie inne niż tak/nie → normalny flow agenta, ale z pending → BEZ historii.
        ask_chatbot(user=user, question="A ile to potrwa?", conversation=conv)
        assert agent.last_history == []

    def test_history_isolated_between_users(self, monkeypatch, client):
        # Prywatność: user A podając conversation_id konwersacji usera B NIE dostaje
        # jego historii — widok filtruje konwersację po zalogowanym userze, więc
        # cudze conv_id → nowa konwersacja A, zero kontekstu (ani PII) usera B.
        from django.urls import reverse

        agent = _HistoryCapturingAgent()
        monkeypatch.setattr(agent_module, "AGENT", agent)
        user_b = User.objects.create_user("hist_b", "b@a.test", "pw-1234!Tajne")
        conv_b = Conversation.objects.create(user=user_b, title="B")
        Message.objects.create(
            conversation=conv_b, role=Message.Role.USER, content="Sekret B: KOP-B99"
        )
        Message.objects.create(
            conversation=conv_b, role=Message.Role.ASSISTANT, content="Odpowiedź dla B"
        )

        user_a = User.objects.create_user("hist_a", "a@a.test", "pw-1234!Tajne")
        client.force_login(user_a)
        resp = client.post(
            reverse("chatbot:ask"),
            {"question": "Cześć asystencie", "conversation_id": conv_b.pk},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        # Historia usera B NIE trafiła do modelu (guard w widoku → nowa konwersacja A).
        rendered = str(agent.last_history)
        assert "KOP-B99" not in rendered
        assert "Sekret B" not in rendered
