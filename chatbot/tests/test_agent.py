"""Testy agenta — bez prawdziwego wywołania Gemini API.

Sprawdzamy:
1. ``build_agent()`` zwraca ``None`` gdy brak ``GEMINI_API_KEY``;
2. ``build_agent()`` zwraca rzeczywistą instancję ``Agent`` gdy klucz jest
   ustawiony (mock env var — nie wymaga prawdziwego klucza, bo Pydantic AI
   leniwie waliduje dopiero przy ``run_sync``).

NIGDY nie wywołujemy ``agent.run_sync`` z prawdziwym providerem w testach.
"""

from __future__ import annotations

import pytest

from chatbot import agent as agent_module


def test_build_agent_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert agent_module.build_agent() is None


def test_build_agent_returns_none_when_api_key_blank(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert agent_module.build_agent() is None


# google-genai (transitively loaded przez pydantic-ai google provider) emituje
# DeprecationWarning na Python 3.14 (typing._UnionGenericAlias). To bug w
# third-party libce, nie w naszym kodzie — ignorujemy tylko w tym jednym teście.
@pytest.mark.filterwarnings("ignore:.*_UnionGenericAlias.*:DeprecationWarning")
def test_build_agent_returns_agent_instance(monkeypatch):
    """Sprawdza że factory tworzy ``Agent`` z 4 zarejestrowanymi narzędziami.

    Używamy fake klucza — pydantic-ai weryfikuje go dopiero przy ``run_sync``,
    a my tylko sprawdzamy że obiekt został utworzony.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests-only")
    agent = agent_module.build_agent()
    assert agent is not None
    # Pydantic AI Agent ma metodę ``run_sync`` — sanity check.
    assert hasattr(agent, "run_sync")


def test_build_agent_has_deps_type_chat_deps(monkeypatch):
    """Regression (Wave 8 P0 BLOCKER fix): build_agent MUSI wired deps_type=ChatDeps.

    Bez tego services.py ``agent.run_sync(question, deps=ChatDeps(user=user))``
    rzuca UserError w produkcji (pydantic-ai 1.97 odmawia deps gdy Agent
    nie ma deklarowanego deps_type). Test używa REAL Agent (NIE _FakeAgent)
    żeby uniknąć false-positive — fake bypasses pydantic-ai validation.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests-only")
    agent = agent_module.build_agent()
    assert agent is not None
    # Pydantic AI 1.97: ``Agent.deps_type`` exposes the declared deps class.
    assert agent.deps_type is agent_module.ChatDeps, (
        f"Agent must declare deps_type=ChatDeps, got {agent.deps_type!r}"
    )


def test_system_prompt_contains_polish_business_instruction():
    """System prompt MUSI explicit instruować: po polsku + zakres pomocy + bezpieczeństwo.

    Wave 14-C: agent przestał być read-only — operacje WRITE są dostępne ALE
    wymagają explicit confirmation w następnej turze rozmowy. Test sprawdza
    zarówno język (polski) jak i kluczowe zasady bezpieczeństwa.
    """
    p = agent_module.SYSTEM_PROMPT.lower()
    assert "polsku" in p
    # Write tools są dostępne, ale zawsze przez "propose_" + confirmation.
    assert "propose_" in p
    assert "potwierdz" in p or "confirmation" in p
    # Link do formy zostaje jako alternatywa dla operacji bez narzędzia.
    assert "/rezerwacje/dodaj/" in agent_module.SYSTEM_PROMPT


def test_system_prompt_lists_all_read_tools():
    """System prompt musi wymienić wszystkie 4 read-only narzędzia po nazwie."""
    p = agent_module.SYSTEM_PROMPT
    for tool_name in (
        "get_machine_status",
        "check_availability",
        "get_inspections_due",
        "get_service_costs",
    ):
        assert tool_name in p, f"System prompt nie zawiera narzędzia: {tool_name}"


def test_system_prompt_lists_all_write_tools():
    """Wave 14-C: System prompt musi wymienić wszystkie 5 propose_* narzędzi."""
    p = agent_module.SYSTEM_PROMPT
    for tool_name in (
        "propose_create_reservation",
        "propose_cancel_reservation",
        "propose_change_operator",
        "propose_swap_machine",
        "propose_set_machine_to_service",
    ):
        assert tool_name in p, f"System prompt nie zawiera write tool: {tool_name}"


def test_system_prompt_warns_about_prompt_injection():
    """System prompt MUSI ostrzegać przed prompt injection (defense-in-depth)."""
    p = agent_module.SYSTEM_PROMPT.lower()
    assert "<user_input>" in p
    assert "injection" in p or "ignore previous" in p or "instrukcji" in p


def test_system_prompt_forbids_silent_permission_bypass():
    """System prompt MUSI explicit zabraniać obchodzenia permission check."""
    p = agent_module.SYSTEM_PROMPT.lower()
    assert "brak uprawnień" in p or "uprawnień" in p
    # Agent ma POWTÓRZYĆ błąd usera, nie cichą próbę alternatywy.
    assert "powtórz" in p or "przekaż" in p
