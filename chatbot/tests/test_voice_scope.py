"""Zakres głosu — nieodwracalne akcje zablokowane na kanale głosowym.

Terminate/anonymize employee (RODO) i delete_site są zbyt wrażliwe na kanał
głosowy (słabszy czynnik: caller-ID + PIN) — wykonywane wyłącznie w UI, NIEZALEŻNIE
od roli/uprawnień dzwoniącego. (Decyzja Sebastiana 2026-07-01.)
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from chatbot.voice_consumer import (
    VOICE_BLOCKED_ACTIONS,
    confirm_pending,
    propose_or_execute,
)
from chatbot.voice_session import VoiceCallSession

User = get_user_model()


@pytest.mark.django_db
class TestVoiceScope:
    def test_blocked_actions_refused_even_for_admin(self):
        # Admin (superuser) MA uprawnienia do wszystkiego — mimo to głos odmawia.
        admin = User.objects.create_superuser("vs_scope_admin", "a@a.test", "x")
        session = VoiceCallSession(call_sid="CAblk", user=admin)
        for action in ["terminate_employee", "anonymize_employee", "delete_site"]:
            result = propose_or_execute(session, action, {"username": "x"})
            assert "aplikacji" in result  # grzeczna odmowa głosowa
            assert not session.has_pending()  # NIE zaproponowano do potwierdzenia

    def test_blocked_set_contents(self):
        assert VOICE_BLOCKED_ACTIONS == {
            "terminate_employee",
            "anonymize_employee",
            "delete_site",
        }

    def test_confirm_defense_in_depth(self):
        # Nawet gdyby pending jakoś zawierał blocked action, confirm odmawia.
        admin = User.objects.create_superuser("vs_scope_admin2", "a2@a.test", "x")
        session = VoiceCallSession(call_sid="CAblk2", user=admin)
        session.propose("delete_site", {"project_number": "BUD-2026-001"})
        assert "aplikacji" in confirm_pending(session)

    def test_allowed_write_still_proposes(self):
        # Akcja spoza blacklisty — admin dostaje normalną propozycję (nie regres).
        admin = User.objects.create_superuser("vs_scope_admin3", "a3@a.test", "x")
        session = VoiceCallSession(call_sid="CAok", user=admin)
        result = propose_or_execute(session, "create_reservation", {"machine_uid": "KOP-001"})
        assert "potwierdzasz" in result.lower()
        assert session.has_pending()
