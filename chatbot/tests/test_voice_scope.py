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
        assert {
            "terminate_employee",
            "anonymize_employee",
            "delete_site",
        } == VOICE_BLOCKED_ACTIONS

    def test_confirm_defense_in_depth(self):
        # Nawet gdyby pending jakoś zawierał blocked action, confirm odmawia.
        admin = User.objects.create_superuser("vs_scope_admin2", "a2@a.test", "x")
        session = VoiceCallSession(call_sid="CAblk2", user=admin)
        session.propose("delete_site", {"project_number": "BUD-2026-001"})
        assert "aplikacji" in confirm_pending(session)

    def test_allowed_write_still_proposes(self):
        # Akcja spoza blacklisty z PRAWIDŁOWYMI danymi → normalna propozycja (nie regres).
        from machines.models import Machine

        admin = User.objects.create_superuser("vs_scope_admin3", "a3@a.test", "x")
        Machine.objects.create(
            uid="KOP-001",
            name="Koparka",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        session = VoiceCallSession(call_sid="CAok", user=admin)
        result = propose_or_execute(session, "set_machine_to_service", {"machine_uid": "KOP-001"})
        assert "potwierdzasz" in result.lower()
        assert session.has_pending()

    def test_p6_validates_before_promise(self):
        # P6: głos waliduje write PRZED obietnicą — akcja na NIEISTNIEJĄCYM obiekcie
        # → błąd wypowiedziany, NIE „Czy potwierdzasz?" (parytet z czatem tekstowym).
        admin = User.objects.create_superuser("vs_scope_p6", "p6@a.test", "x")
        session = VoiceCallSession(call_sid="CAp6", user=admin)
        result = propose_or_execute(session, "set_machine_to_service", {"machine_uid": "KOP-999"})
        assert "potwierdzasz" not in result.lower()  # NIE obiecuje
        assert not session.has_pending()  # brak pending do potwierdzenia
        assert "nie istnieje" in result.lower()


@pytest.mark.django_db
class TestVoiceWriteRateLimit:
    """Rate-limit write na głosie = parytet z czatem (wspólny licznik per user)."""

    def test_confirm_blocked_when_daily_write_limit_exhausted(self):
        # Wyczerpany limit (np. wcześniejsze zapisy) → głos odmawia confirm.
        from chatbot.services import WRITE_RATE_LIMIT_PER_DAY, _check_write_rate_limit

        admin = User.objects.create_superuser("vrl_admin", "vrl@a.test", "x")
        for _ in range(WRITE_RATE_LIMIT_PER_DAY):
            _check_write_rate_limit(admin.pk)
        session = VoiceCallSession(call_sid="CArl", user=admin)
        session.propose("set_machine_to_service", {"machine_uid": "KOP-401"})
        result = confirm_pending(session)
        assert "limit" in result.lower()  # odmowa PRZED wykonaniem

    def test_confirm_shares_counter_with_text_channel(self):
        # Parytet: 9 zapisów „czatem" + 1 głosem = 10 (przechodzi), 11. głosem
        # zablokowany — ten sam licznik per user, nie da się obejść zmianą kanału.
        from chatbot.services import WRITE_RATE_LIMIT_PER_DAY, _check_write_rate_limit
        from machines.models import Machine

        admin = User.objects.create_superuser("vrl_admin2", "vrl2@a.test", "x")
        Machine.objects.create(
            uid="KOP-402",
            name="K",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        for _ in range(WRITE_RATE_LIMIT_PER_DAY - 1):
            _check_write_rate_limit(admin.pk)  # 9 zapisów „czatem"
        # 10. zapis (głos) — wciąż w limicie → wykonany.
        s1 = VoiceCallSession(call_sid="CArl2a", user=admin)
        s1.propose("set_machine_to_service", {"machine_uid": "KOP-402"})
        assert "limit" not in confirm_pending(s1).lower()
        # 11. zapis (głos) — limit wyczerpany → odmowa.
        s2 = VoiceCallSession(call_sid="CArl2b", user=admin)
        s2.propose("set_machine_to_service", {"machine_uid": "KOP-402"})
        assert "limit" in confirm_pending(s2).lower()
