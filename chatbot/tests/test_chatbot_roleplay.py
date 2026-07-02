"""Testy logiki harnessu ``chatbot_roleplay`` (bez realnego Gemini).

Weryfikujemy rdzeń oceny (``_evaluate`` — spójność decyzji chatbota z RBAC) oraz
zachowania brzegowe (SKIP bez AGENT, filtrowanie intencji). Sam przebieg z żywym
modelem to ręczne narzędzie dev (płatne API), nie test jednostkowy.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from chatbot.management.commands.chatbot_roleplay import READ_PROBES, WRITE_PROBES, Command

ACTION = "set_machine_to_service"


class TestEvaluate:
    def setup_method(self):
        self.cmd = Command()

    def test_read_without_proposal_passes(self):
        ok, _ = self.cmd._evaluate(None, True, False, None, error=False)
        assert ok

    def test_read_with_proposal_fails(self):
        # Odczyt NIE powinien tworzyć propozycji zapisu.
        ok, _ = self.cmd._evaluate(None, True, True, "x", error=False)
        assert not ok

    def test_allowed_write_proposed_passes(self):
        ok, _ = self.cmd._evaluate(ACTION, True, True, ACTION, error=False)
        assert ok

    def test_allowed_write_wrong_action_fails(self):
        ok, _ = self.cmd._evaluate(ACTION, True, True, "create_reservation", error=False)
        assert not ok

    def test_allowed_write_no_proposal_fails(self):
        # Uprawniony, ale chatbot nie zaproponował → możliwe zawieszenie/złe zrozumienie.
        ok, _ = self.cmd._evaluate(ACTION, True, False, None, error=False)
        assert not ok

    def test_denied_write_no_proposal_passes(self):
        ok, _ = self.cmd._evaluate(ACTION, False, False, None, error=False)
        assert ok

    def test_denied_write_proposed_is_critical_fail(self):
        # Najgorszy przypadek: chatbot zaproponował akcję mimo braku uprawnień.
        ok, note = self.cmd._evaluate(ACTION, False, True, ACTION, error=False)
        assert not ok
        assert "KRYTYCZNE" in note

    def test_agent_error_fails(self):
        ok, _ = self.cmd._evaluate(None, True, False, None, error=True)
        assert not ok


class TestProbeSelection:
    def test_intent_read_only(self):
        assert Command()._probes("read") == READ_PROBES

    def test_intent_write_only(self):
        assert Command()._probes("write") == WRITE_PROBES

    def test_intent_all_combines(self):
        combined = Command()._probes("all")
        assert len(combined) == len(READ_PROBES) + len(WRITE_PROBES)


@pytest.mark.django_db
def test_command_skips_when_agent_unavailable(monkeypatch):
    # Bez skonfigurowanego agenta (np. brak GEMINI_API_KEY) → SKIP, nie crash.
    from chatbot import agent as agent_module

    monkeypatch.setattr(agent_module, "AGENT", None)
    out = StringIO()
    call_command("chatbot_roleplay", stdout=out)
    assert "SKIP" in out.getvalue()
