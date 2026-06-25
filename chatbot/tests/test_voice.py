"""Testy agenta głosowego (część testowalna: stan, caller-ID, dyspozytor).

Żywe gniazdo WS (Gemini Live) jest bramkowane akcjami autora i NIE jest tu
testowane — sprawdzamy maszynę stanów, rozpoznanie dzwoniącego po numerze oraz
reużycie reguł uprawnień (admin pisze, montażysta/gość tylko czytają).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model

from accounts.models import EmployeeProfile
from chatbot.voice_consumer import (
    build_user_perms_summary,
    confirm_pending,
    propose_or_execute,
)
from chatbot.voice_session import VoiceCallSession, VoiceState
from machines.models import Machine

User = get_user_model()

pytestmark = pytest.mark.django_db


def _role_user(username, function, phone):
    user = User.objects.create_user(username=username, password="x")
    profile = user.profile
    profile.function = function
    profile.phone = phone
    profile.save(update_fields=["function", "phone", "updated_at"])
    return User.objects.get(pk=user.pk)


# -----------------------------------------------------------------------------
# Maszyna stanów VoiceCallSession
# -----------------------------------------------------------------------------


class TestVoiceSession:
    def test_guest_cannot_write(self):
        s = VoiceCallSession(call_sid="CA1", user=None)
        assert s.is_guest
        assert not s.can_write

    def test_propose_confirm_cycle(self):
        s = VoiceCallSession(call_sid="CA2", user=object())
        s.propose("create_reservation", {"machine_uid": "KOP-001"})
        assert s.has_pending()
        assert s.state is VoiceState.AWAITING_CONFIRMATION
        action, params = s.confirm()
        assert action == "create_reservation"
        assert params == {"machine_uid": "KOP-001"}
        assert not s.has_pending()
        assert s.state is VoiceState.IDLE

    def test_cancel_clears_pending(self):
        s = VoiceCallSession(call_sid="CA3", user=object())
        s.propose("cancel_reservation", {"reservation_id": 5})
        s.cancel()
        assert not s.has_pending()

    def test_confirm_without_pending_raises(self):
        s = VoiceCallSession(call_sid="CA4", user=object())
        with pytest.raises(ValueError, match="oczekując"):
            s.confirm()


# -----------------------------------------------------------------------------
# Webhook caller-ID
# -----------------------------------------------------------------------------


class TestVoiceWebhook:
    def test_known_caller_resolved_to_user(self, client):
        user = _role_user("dzwoniacy", EmployeeProfile.Function.KIEROWNIK, "+48600000011")
        response = client.post("/voice/incoming/", {"From": "+48 600 000 011", "CallSid": "CA9"})
        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"
        body = response.content.decode("utf-8")
        assert "ConversationRelay" in body
        assert f'value="{user.pk}"' in body

    def test_unknown_caller_is_guest(self, client):
        response = client.post("/voice/incoming/", {"From": "+48999999999", "CallSid": "CA8"})
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'value="guest"' in body


# -----------------------------------------------------------------------------
# Dyspozytor propozycja → potwierdzenie (reużycie uprawnień)
# -----------------------------------------------------------------------------


class TestVoiceDispatch:
    def test_guest_write_refused(self):
        s = VoiceCallSession(call_sid="CA10", user=None)
        result = propose_or_execute(s, "create_reservation", {})
        assert "gość" in result.lower() or "gosc" in result.lower()
        assert not s.has_pending()

    def test_montazysta_write_refused(self):
        mont = _role_user("mont_voice", EmployeeProfile.Function.MONTAZYSTA, "+48600000099")
        s = VoiceCallSession(call_sid="CA11", user=mont)
        result = propose_or_execute(s, "create_reservation", {})
        assert "uprawnie" in result.lower()
        assert not s.has_pending()

    def test_admin_write_proposes_confirmation(self):
        admin = User.objects.create_superuser("adminvoice", "a@a.test", "x")
        s = VoiceCallSession(call_sid="CA12", user=admin)
        result = propose_or_execute(s, "create_reservation", {})
        assert "potwierdzasz" in result.lower()
        assert s.has_pending()

    def test_confirm_executes_create_reservation(self):
        admin = User.objects.create_superuser("adminexec", "a@a.test", "x")
        machine = Machine.objects.create(
            uid="KOP-V01",
            name="Koparka voice",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        start = date.today() + timedelta(days=4)
        params = {
            "machine_uid": machine.uid,
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=3)).isoformat(),
            "person": "Jan Kowalski",
            "address": "ul. Polna 5, Kraków",
            "responsible_person": "Anna Nowak",
        }
        s = VoiceCallSession(call_sid="CA13", user=admin)
        propose_or_execute(s, "create_reservation", params)
        result = confirm_pending(s)
        assert "utworzona" in result.lower()
        from reservations.models import Reservation

        reservation = Reservation.objects.latest("pk")
        assert reservation.created_by == admin

    def test_perms_summary_variants(self):
        admin = User.objects.create_superuser("adminsum", "a@a.test", "x")
        mont = _role_user("montsum", EmployeeProfile.Function.MONTAZYSTA, "+48600000088")
        assert "zapisujące" in build_user_perms_summary(admin)
        assert "gości" in build_user_perms_summary(None).lower()
        assert "odczyt" in build_user_perms_summary(mont).lower()
