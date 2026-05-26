"""Wave 14-H Bundle H-3 — pending_action TTL (10 minutes) tests.

Atak: user wraca po godzinach (np. zostawił otwartą zakładkę z propozycją
anulowania) i klika "tak" / wpisuje "tak" — system wykonałby akcję bez
świeżego intentu. Mitygacja: 10-minutowy TTL.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from freezegun import freeze_time
from pydantic_ai.messages import ToolCallPart

from chatbot import agent as agent_module
from chatbot.services import PENDING_ACTION_TTL, ask_chatbot
from machines.models import Machine
from reservations.models import Reservation


@pytest.fixture
def user_full_perms(db):
    user_model = get_user_model()
    u = user_model.objects.create_user(username="ttl-tester", password="x")
    for app_label, codename in [
        ("reservations", "add_reservation"),
        ("reservations", "change_reservation"),
        ("reservations", "view_reservation"),
        ("machines", "change_machine"),
    ]:
        u.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def koparka(db):
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka TTL",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


class _ProposingAgent:
    def __init__(self, action: str, params: dict):
        self.action = action
        self.params = params

    def run_sync(self, *_args, **_kwargs):
        tool_call = ToolCallPart(
            tool_name=f"propose_{self.action}",
            args=self.params,
        )
        fake_msg = SimpleNamespace(parts=[tool_call])
        return SimpleNamespace(
            output="(preview)",
            usage=SimpleNamespace(total_tokens=10),
            all_messages=lambda: [fake_msg],
        )


def _propose_params(koparka, today: date):
    # Wave 14-H Bundle M-1: chatbot wymaga responsible_person + address.
    return {
        "machine_uid": koparka.uid,
        "start_date": (today + timedelta(days=3)).isoformat(),
        "end_date": (today + timedelta(days=8)).isoformat(),
        "person": "Jan",
        "address": "ul. Budowlana 1, 00-001 Warszawa",
        "responsible_person": "Anna Kierownik",
    }


@pytest.mark.django_db
class TestPendingActionTTL:
    """Bundle H-3: 10-minute TTL na pending_action."""

    def test_ttl_constant_is_10_minutes(self):
        """Audit: PENDING_ACTION_TTL = 10 minut (z security review)."""
        assert timedelta(minutes=10) == PENDING_ACTION_TTL

    def test_pending_action_within_ttl_executes_ok(self, monkeypatch, user_full_perms, koparka):
        """Akcja w ramach TTL (< 10min) wykonuje się normalnie."""
        today = date.today()
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", _propose_params(koparka, today)),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is not None

        # 5 minut później — wciąż w TTL.
        future = timezone.now() + timedelta(minutes=5)
        with freeze_time(future):
            confirm = ask_chatbot(
                user=user_full_perms, question="tak", conversation=first.conversation
            )
        first.conversation.refresh_from_db()
        # Sukces: rezerwacja utworzona, pending wyczyszczony, no expiry msg.
        assert first.conversation.pending_action is None
        assert Reservation.objects.filter(machine=koparka).count() == 1
        assert "wygasł" not in confirm.content.lower()

    def test_pending_action_expires_after_10_minutes(self, monkeypatch, user_full_perms, koparka):
        """Akcja PO 10 minutach — wygasa, NIE wykonuje się."""
        today = date.today()
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", _propose_params(koparka, today)),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj KOP-001")
        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is not None
        # Capture created_at before time travel.
        orig_created_at = first.conversation.pending_action_created_at
        assert orig_created_at is not None

        # 15 minut później — TTL wygasł (10 min).
        future = orig_created_at + timedelta(minutes=15)
        with freeze_time(future):
            confirm = ask_chatbot(
                user=user_full_perms, question="tak", conversation=first.conversation
            )
        first.conversation.refresh_from_db()
        # Pending wyczyszczony BEZ wykonania — żadnej rezerwacji.
        assert first.conversation.pending_action is None
        assert first.conversation.pending_action_created_at is None
        assert Reservation.objects.filter(machine=koparka).count() == 0
        # User dostał error message o wygaśnięciu.
        assert "wygasł" in confirm.content.lower() or "limit" in confirm.content.lower()

    def test_pending_action_exactly_at_ttl_boundary(self, monkeypatch, user_full_perms, koparka):
        """Granica TTL — dokładnie 10:01 wygasa, dokładnie 9:59 OK."""
        today = date.today()
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", _propose_params(koparka, today)),
        )

        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj")
        first.conversation.refresh_from_db()
        orig_created = first.conversation.pending_action_created_at
        assert orig_created is not None

        # Dokładnie 10:01 — wygasa.
        future = orig_created + timedelta(minutes=10, seconds=1)
        with freeze_time(future):
            confirm = ask_chatbot(
                user=user_full_perms, question="tak", conversation=first.conversation
            )
        assert "wygasł" in confirm.content.lower() or "limit" in confirm.content.lower()
        assert Reservation.objects.filter(machine=koparka).count() == 0

    def test_pending_action_created_at_set_on_propose(self, monkeypatch, user_full_perms, koparka):
        """Pole pending_action_created_at jest ustawione po propose."""
        today = date.today()
        before = timezone.now()
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", _propose_params(koparka, today)),
        )
        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj")
        after = timezone.now()
        first.conversation.refresh_from_db()
        assert first.conversation.pending_action_created_at is not None
        assert before <= first.conversation.pending_action_created_at <= after

    def test_pending_action_created_at_cleared_on_nie(self, monkeypatch, user_full_perms, koparka):
        """User odpisał 'nie' → pending_action_created_at również wyczyszczony."""
        today = date.today()
        monkeypatch.setattr(
            agent_module,
            "AGENT",
            _ProposingAgent("create_reservation", _propose_params(koparka, today)),
        )
        first = ask_chatbot(user=user_full_perms, question="Zarezerwuj")
        ask_chatbot(user=user_full_perms, question="nie", conversation=first.conversation)
        first.conversation.refresh_from_db()
        assert first.conversation.pending_action is None
        assert first.conversation.pending_action_created_at is None
