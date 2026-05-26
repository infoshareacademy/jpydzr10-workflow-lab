"""Testy multi-turn confirmation flow chatbota (Wave 14-C Bundle 3).

Sprawdzają cały lifecycle pending_action:
  1. Agent proponuje write akcję → ``Conversation.pending_action`` zapisany.
  2. User odpisuje "tak" → akcja wykonana + pending wyczyszczony.
  3. User odpisuje "nie" → pending wyczyszczony bez wykonania.
  4. User odpisuje niejednoznacznie → pending zachowany, normalny flow.

Testy używają monkeypatch żeby agent zwrócił deterministyczny JSON
zamiast wywoływać Gemini API.

**Wave 14-H Bundle C-1**: fake agent zwraca teraz ``all_messages()``
z ``ToolCallPart`` (faktyczny tool call), nie tylko ``output=JSON``.
Dzięki temu services wykrywa proposal przez :func:`_extract_proposal_from_tool_calls`
zamiast podatnego na echo-attack :func:`_parse_proposal`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from pydantic_ai.messages import ToolCallPart

from chatbot import agent as agent_module
from chatbot.models import Message
from chatbot.services import (
    _is_affirmative,
    _is_negative,
    _parse_proposal,
    ask_chatbot,
)
from machines.models import Machine
from reservations.models import Reservation

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_full_perms(db):
    """User z PEŁNYMI write uprawnieniami."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="confirm-tester", password="x")
    perms = [
        ("reservations", "add_reservation"),
        ("reservations", "change_reservation"),
        ("reservations", "view_reservation"),
        ("machines", "change_machine"),
        ("machines", "view_machine"),
    ]
    for app_label, codename in perms:
        u.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def koparka(db):
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


# =============================================================================
# Unit: _is_affirmative / _is_negative / _parse_proposal
# =============================================================================


class TestAffirmativeDetector:
    @pytest.mark.parametrize(
        "text",
        ["tak", "TAK", "Tak.", "potwierdzam", "potwierdź", "ok", "okej", "yes", "y", "confirm"],
    )
    def test_matches_affirmative(self, text):
        assert _is_affirmative(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "nie",
            "anuluj",
            "nieprawda",  # nie z dodatkowymi znakami
            "tak jak chcesz",  # tak w dłuższym zdaniu
            "yes please do it",  # yes w dłuższym zdaniu
            "",
        ],
    )
    def test_does_not_match_non_affirmative(self, text):
        assert _is_affirmative(text) is False


class TestNegativeDetector:
    @pytest.mark.parametrize("text", ["nie", "Nie.", "anuluj", "stop", "cancel", "no", "n"])
    def test_matches_negative(self, text):
        assert _is_negative(text) is True

    @pytest.mark.parametrize("text", ["tak", "nie wiem co robić", "no problem", ""])
    def test_does_not_match_non_negative(self, text):
        assert _is_negative(text) is False


class TestParseProposal:
    def test_parses_pure_json_response(self):
        raw = json.dumps(
            {
                "proposed_action": "create_reservation",
                "params": {"machine_uid": "KOP-001"},
                "preview": "Utworzę X",
                "confirmation_required": True,
            }
        )
        result = _parse_proposal(raw)
        assert result is not None
        assert result["action"] == "create_reservation"
        assert result["params"] == {"machine_uid": "KOP-001"}
        assert result["preview"] == "Utworzę X"

    def test_parses_json_embedded_in_prose(self):
        json_part = json.dumps(
            {
                "proposed_action": "cancel_reservation",
                "params": {"reservation_id": 5},
                "preview": "Anuluję 5",
                "confirmation_required": True,
            }
        )
        raw = f"Oto co planuję: {json_part}. Czy potwierdzasz?"
        result = _parse_proposal(raw)
        assert result is not None
        assert result["action"] == "cancel_reservation"

    def test_returns_none_for_plain_text(self):
        assert _parse_proposal("To jest zwykła odpowiedź bez akcji.") is None

    def test_returns_none_for_non_proposal_json(self):
        # JSON ale BEZ confirmation_required=True.
        raw = json.dumps({"machine": "KOP-001", "status": "ok"})
        assert _parse_proposal(raw) is None

    def test_handles_empty_string(self):
        assert _parse_proposal("") is None
        assert _parse_proposal(None) is None


# =============================================================================
# Integration: ask_chatbot multi-turn flow
# =============================================================================


class _ProposingAgent:
    """Fake agent który symuluje wywołanie ``propose_*`` toola.

    **Wave 14-H Bundle C-1**: zwraca obiekt z metodą ``all_messages()``
    zawierającą ``ToolCallPart(tool_name="propose_<action>", args=params)``.
    Services wykrywa proposal przez :func:`_extract_proposal_from_tool_calls`
    (NIE przez parse text — vide echo-attack mitigation).
    """

    def __init__(self, action: str, params: dict, preview: str):
        self.action = action
        self.params = params
        self.preview = preview

    def run_sync(self, *_args, **_kwargs):
        tool_call = ToolCallPart(
            tool_name=f"propose_{self.action}",
            args=self.params,
        )
        fake_message = SimpleNamespace(parts=[tool_call])
        return SimpleNamespace(
            output=self.preview,
            usage=SimpleNamespace(total_tokens=10),
            all_messages=lambda: [fake_message],
        )


class _PlainAgent:
    """Fake agent który zwraca zwykły tekst (brak tool calls)."""

    def __init__(self, text: str = "Zwykła odpowiedź"):
        self.text = text

    def run_sync(self, *_args, **_kwargs):
        return SimpleNamespace(
            output=self.text,
            usage=SimpleNamespace(total_tokens=5),
            all_messages=lambda: [],
        )


@pytest.mark.django_db
class TestMultiTurnConfirmationFlow:
    def test_agent_proposal_stores_pending_action(self, monkeypatch, user_full_perms, koparka):
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )

        msg = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001 na 3-8 czerwca")

        conv = msg.conversation
        conv.refresh_from_db()
        assert conv.pending_action is not None
        assert conv.pending_action["action"] == "create_reservation"
        # Preview powinien być pokazany użytkownikowi, NIE surowy JSON.
        assert "KOP-001" in msg.content
        assert "TAK" in msg.content or "potwierdz" in msg.content.lower()

    def test_proposal_does_not_mutate_db(self, monkeypatch, user_full_perms, koparka):
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )

        ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        # ZERO rezerwacji utworzonych — propose != execute.
        assert Reservation.objects.filter(machine=koparka).count() == 0

    def test_user_tak_executes_action(self, monkeypatch, user_full_perms, koparka):
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

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        # Druga tura — user potwierdza.
        confirm_msg = ask_chatbot(
            user=user_full_perms, question="tak", conversation=first.conversation
        )

        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is None
        assert Reservation.objects.filter(machine=koparka).count() == 1
        assert "utworzona" in confirm_msg.content.lower()

    def test_user_nie_cancels_action(self, monkeypatch, user_full_perms, koparka):
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        cancel_msg = ask_chatbot(
            user=user_full_perms, question="nie", conversation=first.conversation
        )

        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is None
        assert Reservation.objects.filter(machine=koparka).count() == 0
        assert "anulowana" in cancel_msg.content.lower()

    def test_unclear_response_preserves_pending(self, monkeypatch, user_full_perms, koparka):
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        # Niejednoznaczna odpowiedź — pending zachowany.
        monkeypatch.setattr(agent_module, "AGENT", _PlainAgent("Mogę pomóc"))
        ask_chatbot(
            user=user_full_perms,
            question="A jakie inne maszyny są dostępne?",
            conversation=first.conversation,
        )

        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is not None
        assert first.conversation.pending_action["action"] == "create_reservation"

    def test_confirm_revoked_permission_blocks_execute(self, monkeypatch, user_full_perms, koparka):
        """Defense-in-depth: user stracił uprawnienie między propose a confirm."""
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", params, "Utworzę KOP-001"),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        # Symulujemy że uprawnienia zostały odebrane między propose a confirm.
        user_full_perms.user_permissions.clear()
        # Reload — usuwa permission cache w testach.
        user_model = get_user_model()
        revoked_user = user_model.objects.get(pk=user_full_perms.pk)

        confirm_msg = ask_chatbot(
            user=revoked_user, question="tak", conversation=first.conversation
        )

        assert "Brak uprawnień" in confirm_msg.content
        assert Reservation.objects.filter(machine=koparka).count() == 0

    def test_plain_response_does_not_set_pending(self, monkeypatch, user_full_perms):
        monkeypatch.setattr(agent_module, "AGENT", _PlainAgent("Pomogę z czymkolwiek innym."))
        msg = ask_chatbot(user=user_full_perms, question="Cześć asystencie")
        msg.conversation.refresh_from_db()
        assert msg.conversation.pending_action is None
        assert "Pomogę z czymkolwiek innym." in msg.content

    def test_proposal_message_preview_no_raw_json(self, monkeypatch, user_full_perms, koparka):
        """Render proposal nie powinien wyrzucać surowego JSON do usera."""
        today = date.today()
        params = {
            "machine_id": koparka.pk,
            "machine_uid": koparka.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",
            "notes": "",
        }
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent(
                "create_reservation",
                params,
                "Utworzę rezerwację KOP-001 dla Jan",
            ),
        )

        msg = ask_chatbot(user=user_full_perms, question="Zarezerwuj")
        # Surowe pola jak "confirmation_required" / "proposed_action" NIE powinny
        # być widoczne w content (jest preview tekstowy renderowany serwerowo —
        # Wave 14-H Bundle C-1).
        assert "confirmation_required" not in msg.content
        assert "proposed_action" not in msg.content
        # Preview zawiera UID maszyny + osoba (server-rendered z params).
        assert "KOP-001" in msg.content
        assert "Jan" in msg.content

    def test_full_lifecycle_two_turns_persisted_to_db(self, monkeypatch, user_full_perms, koparka):
        """End-to-end: 2 user msgs + 2 assistant msgs persisted po confirm."""
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

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        ask_chatbot(user=user_full_perms, question="tak", conversation=first.conversation)

        msgs = list(first.conversation.messages.order_by("created_at"))
        assert len(msgs) == 4
        assert [m.role for m in msgs] == [
            Message.Role.USER,
            Message.Role.ASSISTANT,
            Message.Role.USER,
            Message.Role.ASSISTANT,
        ]
        # Drugi user message = "tak"; drugi assistant message = success result.
        assert msgs[2].content == "tak"
        assert "utworzona" in msgs[3].content.lower()
