"""Testy widoków chatbota — drawer + endpoint POST /asystent/zapytaj/.

Wszystkie testy mockują agenta (monkeypatch ``chatbot.agent.AGENT``) —
zero prawdziwych wywołań Gemini API.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from chatbot import agent as agent_module
from chatbot.factories import ConversationFactory
from chatbot.models import Conversation, Message


class _FakeUsage:
    """Imituje ``RunUsage`` z pydantic-ai 1.x."""

    total_tokens = 7


class _FakeAgentResponse:
    """Imituje ``AgentRunResult`` 1.x — ``output`` jako pole, ``usage`` jako property."""

    output = "Mockowana odpowiedź asystenta."
    usage = _FakeUsage()


class _FakeAgent:
    def __init__(self, response_text: str = "Mockowana odpowiedź asystenta."):
        self.response_text = response_text

    def run_sync(self, question: str, **_kwargs):
        # ``**_kwargs`` — services przekazuje ``model_settings={"timeout": N}``;
        # fake je ignoruje (brak realnego API call).
        result = _FakeAgentResponse()
        result.output = self.response_text
        return result


# =============================================================================
# GET /asystent/drawer/
# =============================================================================


@pytest.mark.django_db
def test_drawer_requires_login(client):
    response = client.get(reverse("chatbot:drawer"))
    assert response.status_code == 302  # redirect do login


@pytest.mark.django_db
def test_drawer_renders_for_logged_user(client_logged):
    response = client_logged.get(reverse("chatbot:drawer"))
    assert response.status_code == 200
    assert b"Asystent" in response.content


@pytest.mark.django_db
def test_drawer_lists_user_conversations(client_logged, user):
    ConversationFactory(user=user, title="Test konwersacja 1")
    ConversationFactory(user=user, title="Test konwersacja 2")
    response = client_logged.get(reverse("chatbot:drawer"))
    assert response.status_code == 200
    assert b"Test konwersacja 1" in response.content
    assert b"Test konwersacja 2" in response.content


@pytest.mark.django_db
def test_drawer_hides_other_users_conversations(client_logged):
    """Drawer pokazuje tylko konwersacje zalogowanego usera."""
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="inny-user", password="x")
    ConversationFactory(user=other, title="Tajemnica innego usera")
    response = client_logged.get(reverse("chatbot:drawer"))
    assert b"Tajemnica innego usera" not in response.content


# =============================================================================
# POST /asystent/zapytaj/
# =============================================================================


@pytest.mark.django_db
def test_ask_requires_login(client):
    response = client.post(reverse("chatbot:ask"), {"question": "Test?"})
    assert response.status_code == 302


@pytest.mark.django_db
def test_ask_requires_post(client_logged):
    response = client_logged.get(reverse("chatbot:ask"))
    assert response.status_code == 405


@pytest.mark.django_db
def test_ask_returns_partial_with_answer(monkeypatch, client_logged):
    monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("Odpowiedź dla testu"))
    response = client_logged.post(
        reverse("chatbot:ask"),
        {"question": "Czy KOP-001 dostępna?"},
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Czy KOP-001 dostępna?" in body  # echo pytania
    assert "Odpowiedź dla testu" in body  # odpowiedź agenta


@pytest.mark.django_db
def test_ask_persists_messages_in_db(monkeypatch, client_logged, user):
    monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("Persist test"))
    client_logged.post(reverse("chatbot:ask"), {"question": "Pierwsze pytanie"})

    assert Conversation.objects.filter(user=user).count() == 1
    conv = Conversation.objects.get(user=user)
    assert conv.messages.count() == 2  # user + assistant
    assert conv.messages.filter(role=Message.Role.USER).count() == 1
    assert conv.messages.filter(role=Message.Role.ASSISTANT).count() == 1


@pytest.mark.django_db
def test_ask_with_invalid_form_returns_400(monkeypatch, client_logged):
    monkeypatch.setattr(agent_module, "AGENT", _FakeAgent())
    response = client_logged.post(reverse("chatbot:ask"), {"question": "xx"})  # za krótkie
    assert response.status_code == 400
    assert b"question" in response.content or b"znaki" in response.content


@pytest.mark.django_db
def test_ask_uses_existing_conversation_when_id_provided(monkeypatch, client_logged, user):
    monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("Reuse"))
    conv = ConversationFactory(user=user, title="Istniejąca")

    client_logged.post(
        reverse("chatbot:ask"),
        {"question": "Nowe pytanie", "conversation_id": str(conv.pk)},
    )

    assert Conversation.objects.filter(user=user).count() == 1
    conv.refresh_from_db()
    assert conv.messages.count() == 2


@pytest.mark.django_db
def test_ask_ignores_conversation_id_from_other_user(monkeypatch, client_logged, user):
    """Bezpieczeństwo: user nie może wstrzyknąć cudzej konwersacji przez POST."""
    monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("Owned"))
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="inny-attacker", password="x")
    other_conv = ConversationFactory(user=other, title="Cudza")

    client_logged.post(
        reverse("chatbot:ask"),
        {"question": "Próba przejęcia", "conversation_id": str(other_conv.pk)},
    )

    # Cudza konwersacja musi pozostać nietknięta — nowa konwersacja założona
    # dla zalogowanego usera zamiast.
    other_conv.refresh_from_db()
    assert other_conv.messages.count() == 0
    assert Conversation.objects.filter(user=user).count() == 1
    assert Conversation.objects.filter(user=other).count() == 1


@pytest.mark.django_db
def test_ask_renders_error_message_when_agent_unavailable(monkeypatch, client_logged):
    monkeypatch.setattr(agent_module, "AGENT", None)
    response = client_logged.post(
        reverse("chatbot:ask"),
        {"question": "Pytanie bez agenta"},
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "GEMINI_API_KEY" in body or "niedostępny" in body.lower()


# =============================================================================
# Rate limit — 50/d per user (django-ratelimit + RatelimitedMiddleware)
# =============================================================================


@pytest.mark.django_db
class TestChatbotRateLimit:
    """Testy rate-limit dla endpointa POST /asystent/zapytaj/.

    Każdy test najpierw czyści cache (django-ratelimit trzyma countery
    w default cache backend — w testach to ``locmem``). Bez clear()
    countery z innych testów wpływałyby na te.
    """

    @pytest.fixture(autouse=True)
    def _clear_ratelimit_cache(self):
        from django.core.cache import cache

        cache.clear()
        yield
        cache.clear()

    def test_50_requests_pass_then_51st_returns_429(self, monkeypatch, client_logged):
        """50 zapytań POST przechodzi, 51-sze dostaje 429."""
        monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("OK"))

        # 50 OK
        for i in range(50):
            response = client_logged.post(
                reverse("chatbot:ask"),
                {"question": f"Pytanie nr {i}"},
            )
            assert response.status_code == 200, (
                f"Zapytanie #{i + 1} powinno było przejść, dostało {response.status_code}"
            )

        # 51-sze już zablokowane — middleware łapie Ratelimited i renderuje 429.
        response = client_logged.post(
            reverse("chatbot:ask"),
            {"question": "Pytanie ponad limit"},
        )
        assert response.status_code == 429

    def test_429_response_contains_polish_message(self, monkeypatch, client_logged):
        """Odpowiedź 429 zawiera polski komunikat o limicie (HTMX partial)."""
        monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("OK"))

        # Wystrzel 50 OK żeby wyczerpać limit.
        for _ in range(50):
            client_logged.post(reverse("chatbot:ask"), {"question": "x" * 10})

        # 51-szy request z nagłówkiem HX-Request → partial _message.html.
        response = client_logged.post(
            reverse("chatbot:ask"),
            {"question": "Pytanie ponad limit"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 429
        body = response.content.decode("utf-8").lower()
        # Polski komunikat zawiera słowa "limit" lub "spróbuj" / "asystent".
        assert "limit" in body or "spróbuj" in body or "asystent" in body

    def test_429_persists_within_24h_window(self, monkeypatch, client_logged):
        """Po wyczerpaniu limitu kolejne zapytania też dostają 429."""
        monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("OK"))

        for _ in range(50):
            client_logged.post(reverse("chatbot:ask"), {"question": "x" * 10})

        # Sprawdzamy trzy kolejne requesty — wszystkie powinny być 429,
        # bo limit "50/d" trzyma countery 24h (lub do `cache.clear()`).
        for i in range(3):
            response = client_logged.post(
                reverse("chatbot:ask"),
                {"question": f"Następne pytanie {i}"},
            )
            assert response.status_code == 429, (
                f"Po lockout zapytanie #{i + 1} dało {response.status_code}, oczekiwano 429"
            )

    def test_429_full_page_when_not_htmx_request(self, monkeypatch, client_logged):
        """Bez HX-Request → full page ratelimited.html (HTTP 429)."""
        monkeypatch.setattr(agent_module, "AGENT", _FakeAgent("OK"))

        for _ in range(50):
            client_logged.post(reverse("chatbot:ask"), {"question": "x" * 10})

        response = client_logged.post(
            reverse("chatbot:ask"),
            {"question": "Bez HTMX"},
        )
        assert response.status_code == 429
        body = response.content.decode("utf-8")
        # Full page renderuje template `ratelimited.html` z linkiem do home.
        assert "429" in body
        assert "limit" in body.lower() or "asystent" in body.lower()
