"""Step implementations for ``chatbot_qa.feature``.

Pokrywa lukę BDD dla chatbota — istniejące testy w ``chatbot/tests/`` są
unit-level, brakowało Gherkin scenariuszy opisujących user journey
"magazynier pyta asystenta o stan magazynu".

Mocking: agent jest **monkey-patched** przez ``_FakeAgent`` (lokalna kopia
helpera z ``chatbot/tests/test_services.py``) — nigdy nie wywołujemy
prawdziwego Gemini API z testów.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from accounts.factories import UserFactory
from chatbot import agent as agent_module
from chatbot.models import Conversation, Message
from chatbot.services import ask_chatbot
from machines.factories import MachineFactory
from machines.models import Machine

scenarios("../features/chatbot_qa.feature")


# ----------------------------------------------------------------------------
# Fake agent — deterministyczna odpowiedź bez API call
# ----------------------------------------------------------------------------


class _FakeResult:
    """Mock wyniku agenta — pydantic-ai 0.1.x używa atrybutu ``output``."""

    output: str = ""

    def usage(self):
        return type("U", (), {"total_tokens": 42})()


class _FakeAgent:
    """Mock agenta zwracającego deterministyczną odpowiedź — żadnego API call."""

    def __init__(self, response: str = "Odpowiedź testowa."):
        self._response = response
        self.calls: list[str] = []
        self.deps_seen: list = []

    def run_sync(self, question: str, **_kwargs):
        # ``**_kwargs`` — ``services.ask_chatbot`` przekazuje ``deps`` (ChatDeps)
        # oraz ``model_settings={"timeout": N}``; fake je akceptuje i ignoruje
        # (zero realnego API call). ``deps`` zapamiętujemy w ``deps_seen`` dla
        # asercji "tool dostał typed deps" w przyszłych testach.
        self.calls.append(question)
        self.deps_seen.append(_kwargs.get("deps"))
        result = _FakeResult()
        result.output = self._response
        return result


# ----------------------------------------------------------------------------
# GIVEN — seed
# ----------------------------------------------------------------------------


@given(
    parsers.parse('zalogowanego pracownika "{username}"'),
    target_fixture="user",
)
def given_logged_user(username: str, client):
    """Tworzy usera + force_login (skrót — bez prawdziwego POST loginu)."""
    user = UserFactory(username=username)
    client.force_login(user)
    return user


@given(parsers.parse('{count:d} maszyny w stanie "W magazynie"'))
@given(parsers.parse('{count:d} maszyn w stanie "W magazynie"'))
def given_machines_in_warehouse(count: int):
    """Seeduje N maszyn z status=W_MAGAZYNIE — uid unique per call."""
    for i in range(count):
        MachineFactory(uid=f"BDD-Q-{i}", status=Machine.Status.W_MAGAZYNIE)


@given("nieskonfigurowany API klucz Gemini")
def given_no_api_key(monkeypatch, context: dict):
    """``AGENT = None`` → service zwraca komunikat o brakującej konfiguracji.

    Marker ``no_api=True`` w context blokuje fallback w ``when_user_asks``
    (który normalnie ustawia _FakeAgent dla happy path).
    """
    monkeypatch.setattr(agent_module, "AGENT", None)
    context["no_api"] = True


@given("skonfigurowany asystent z deterministyczną odpowiedzią")
def given_fake_agent(monkeypatch, context: dict):
    """Patch ``AGENT`` na ``_FakeAgent`` — żaden test nie woła prawdziwego API."""
    machines_count = Machine.objects.count()
    fake = _FakeAgent(response=f"W magazynie znajduje się {machines_count} maszyn.")
    monkeypatch.setattr(agent_module, "AGENT", fake)
    context["fake_agent"] = fake


# ----------------------------------------------------------------------------
# WHEN — action
# ----------------------------------------------------------------------------


@when(parsers.parse('magazynier pyta asystenta "{question}"'))
def when_user_asks(user, question: str, context: dict, monkeypatch):
    """Wołamy serwis bezpośrednio (omijamy view + ratelimit + form parsing).

    Jeśli scenariusz nie zaznaczył ``no_api`` w context, defaultnie ustawiamy
    ``_FakeAgent`` żeby happy path testy nie zależały od GEMINI_API_KEY w env.
    """
    if not context.get("no_api") and "fake_agent" not in context:
        machines_count = Machine.objects.count()
        fake = _FakeAgent(response=f"W magazynie znajduje się {machines_count} maszyn dostępnych.")
        monkeypatch.setattr(agent_module, "AGENT", fake)
        context["fake_agent"] = fake

    context["message"] = ask_chatbot(user=user, question=question)


# ----------------------------------------------------------------------------
# THEN — assertion
# ----------------------------------------------------------------------------


@then(parsers.parse('asystent odpowiada zawierając tekst "{snippet}"'))
def then_response_contains(context: dict, snippet: str):
    """Odpowiedź assistant zawiera substring (zwykle liczbowy)."""
    message: Message = context["message"]
    assert message.role == Message.Role.ASSISTANT
    assert snippet in message.content, (
        f"Spodziewano '{snippet}' w odpowiedzi, dostano: {message.content!r}"
    )


@then("pytanie i odpowiedź są zapisane w historii konwersacji")
def then_conversation_persisted(context: dict, user):
    """W bazie mamy 1 konwersację z 2 wiadomościami: user + assistant."""
    convs = list(Conversation.objects.filter(user=user))
    assert len(convs) == 1
    messages = list(convs[0].messages.order_by("created_at"))
    assert len(messages) == 2
    assert messages[0].role == Message.Role.USER
    assert messages[1].role == Message.Role.ASSISTANT


@then("asystent odpowiada błędem o brakującym kluczu")
def then_error_about_api_key(context: dict):
    """Bez ``AGENT`` (no API key) — komunikat błędu z hintem dla admina."""
    message: Message = context["message"]
    assert message.role == Message.Role.ERROR
    assert "GEMINI_API_KEY" in message.content or "niedostępny" in message.content


# Auto-mark — wszystkie testy chatbota dotykają DB (Conversation + Message).
pytestmark = [pytest.mark.integration, pytest.mark.django_db]
