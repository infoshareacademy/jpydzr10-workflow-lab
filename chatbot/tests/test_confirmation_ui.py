"""Testy UI confirmation card chatbota (Wave 14-C Bundle 5).

Sprawdzają że POST /asystent/zapytaj/ renderuje confirmation card
gdy agent zaproponuje write action, oraz że click "Potwierdź"/"Anuluj"
poprawnie triggeruje multi-turn flow.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.urls import reverse

from chatbot import agent as agent_module
from machines.models import Machine
from reservations.models import Reservation

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user_full_perms(db):
    user_model = get_user_model()
    u = user_model.objects.create_user(username="ui-tester", password="secret-pw")
    for app_label, codename in [
        ("reservations", "add_reservation"),
        ("reservations", "change_reservation"),
        ("reservations", "view_reservation"),
        ("machines", "change_machine"),
        ("machines", "view_machine"),
    ]:
        u.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def client_logged(client, user_full_perms):
    client.force_login(user_full_perms)
    return client


@pytest.fixture
def koparka(db):
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka UI test",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


class _ProposingAgent:
    """Wave 14-H Bundle C-1: fake agent symulujący ToolCallPart.

    Zamiast text JSON output (echo-attack vector), zwraca ``all_messages()``
    z faktycznym ``ToolCallPart(tool_name="propose_<action>", args=params)``.
    """

    def __init__(self, action: str, params: dict, preview: str):
        self.action = action
        self.params = params
        self.preview = preview

    def run_sync(self, *_args, **_kwargs):
        from pydantic_ai.messages import ToolCallPart

        tool_call = ToolCallPart(
            tool_name=f"propose_{self.action}",
            args=self.params,
        )
        fake_msg = SimpleNamespace(parts=[tool_call])
        return SimpleNamespace(
            output=self.preview,
            usage=SimpleNamespace(total_tokens=10),
            all_messages=lambda: [fake_msg],
        )


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.django_db
class TestConfirmationCardRendering:
    def _make_proposing_agent(self, koparka):
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan Kowalski",
            "address": "",
            "notes": "",
        }
        return _ProposingAgent("create_reservation", params, "Utworzę rezerwację KOP-001 dla Jana")

    def test_confirmation_card_rendered_after_proposal(self, monkeypatch, client_logged, koparka):
        monkeypatch.setattr(agent_module, "AGENT", self._make_proposing_agent(koparka))
        response = client_logged.post(
            reverse("chatbot:ask"), {"question": "Utwórz rezerwację KOP-001"}
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        # Card-level markery.
        assert "Wymagane potwierdzenie" in body
        assert "Potwierdź" in body
        assert "Anuluj" in body
        # Preview tekst pojawia się w karcie (server-rendered z params,
        # Wave 14-H Bundle C-1 — bez echo-attack vector).
        assert "KOP-001" in body
        assert "Proponowana akcja" in body

    def test_card_includes_params_breakdown(self, monkeypatch, client_logged, koparka):
        """User widzi DOKŁADNIE jakie params zostaną wykonane (anti-hallucination)."""
        monkeypatch.setattr(agent_module, "AGENT", self._make_proposing_agent(koparka))
        response = client_logged.post(reverse("chatbot:ask"), {"question": "Utwórz rezerwację"})
        body = response.content.decode("utf-8")
        # Klucze parametrów widoczne (machine_uid, person etc.).
        assert "machine_uid" in body
        assert "person" in body
        assert "Jan Kowalski" in body
        assert "KOP-001" in body

    def test_card_has_hidden_conversation_id(self, monkeypatch, client_logged, koparka):
        """Confirmation card includes conversation_id hidden input — żeby
        następny POST trafił do tej samej konwersacji (a nie utworzył nowej)."""
        monkeypatch.setattr(agent_module, "AGENT", self._make_proposing_agent(koparka))
        response = client_logged.post(reverse("chatbot:ask"), {"question": "Utwórz rezerwację"})
        body = response.content.decode("utf-8")
        from chatbot.models import Conversation

        conv = Conversation.objects.filter(user=client_logged.session["_auth_user_id"]).first()
        # Może być None gdy session key inny — spróbujmy user perms direct.

        if conv is None:
            user_pk = int(client_logged.session["_auth_user_id"])
            conv = Conversation.objects.filter(user_id=user_pk).first()
        assert conv is not None
        assert f'value="{conv.pk}"' in body

    def test_card_has_potwierdz_button_with_value_tak(self, monkeypatch, client_logged, koparka):
        monkeypatch.setattr(agent_module, "AGENT", self._make_proposing_agent(koparka))
        response = client_logged.post(reverse("chatbot:ask"), {"question": "Utwórz rezerwację"})
        body = response.content.decode("utf-8")
        # Hidden input z value="tak" musi być w formularzu.
        assert 'value="tak"' in body
        assert 'value="nie"' in body

    def test_no_card_for_plain_response(self, monkeypatch, client_logged):
        """Bez proposala — brak confirmation card."""

        class _PlainAgent:
            def run_sync(self, *_args, **_kwargs):
                return SimpleNamespace(
                    output="To jest zwykła odpowiedź bez akcji.",
                    usage=SimpleNamespace(total_tokens=5),
                    all_messages=lambda: [],
                )

        monkeypatch.setattr(agent_module, "AGENT", _PlainAgent())
        response = client_logged.post(
            reverse("chatbot:ask"), {"question": "Jakie maszyny są dostępne?"}
        )
        body = response.content.decode("utf-8")
        assert "Wymagane potwierdzenie" not in body


@pytest.mark.django_db
class TestConfirmationCardClickFlow:
    def _setup_pending(self, monkeypatch, client_logged, koparka):
        today = date.today()
        # Wave 14-H Bundle M-1: chatbot wymaga responsible_person + address.
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "ul. Budowlana 1, 00-001 Warszawa",
            "notes": "",
            "responsible_person": "Anna Kierownik",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )
        client_logged.post(reverse("chatbot:ask"), {"question": "Utwórz rezerwację KOP-001"})
        from chatbot.models import Conversation

        user_pk = int(client_logged.session["_auth_user_id"])
        return Conversation.objects.get(user_id=user_pk)

    def test_potwierdz_click_executes_action(self, monkeypatch, client_logged, koparka):
        conv = self._setup_pending(monkeypatch, client_logged, koparka)
        # Symulujemy click "Potwierdź" — POST z question="tak" i conversation_id.
        response = client_logged.post(
            reverse("chatbot:ask"),
            {"question": "tak", "conversation_id": str(conv.pk)},
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "utworzona" in body.lower()
        # DB sprawdzenie — rezerwacja powstała.
        assert Reservation.objects.filter(machine=koparka).count() == 1
        # Pending wyczyszczone.
        conv.refresh_from_db()
        assert conv.pending_action is None

    def test_anuluj_click_clears_pending(self, monkeypatch, client_logged, koparka):
        conv = self._setup_pending(monkeypatch, client_logged, koparka)
        response = client_logged.post(
            reverse("chatbot:ask"),
            {"question": "nie", "conversation_id": str(conv.pk)},
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "anulowana" in body.lower()
        assert Reservation.objects.filter(machine=koparka).count() == 0
        conv.refresh_from_db()
        assert conv.pending_action is None
