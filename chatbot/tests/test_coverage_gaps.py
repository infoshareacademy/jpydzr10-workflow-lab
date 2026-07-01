"""Wave 12 — chatbot coverage gap-filling.

Pokrywa:
* :mod:`chatbot.middleware` — Ratelimited propagacja gdy brak settings,
  ImportError fallback dla view_path.
* :mod:`chatbot.sanitize` — pusty input → "".
* :mod:`chatbot.services._extract_answer` — fallback str(output).
* :mod:`chatbot.tools` — INSPECTIONS_LIST_LIMIT break.
* :mod:`chatbot.admin` — title/content/role_badge formattery.
"""

from __future__ import annotations

import pytest

# =============================================================================
# middleware — propagacja Ratelimited gdy brak RATELIMIT_VIEW
# =============================================================================


def test_middleware_passes_non_ratelimited():
    """Wyjątek niebędący Ratelimited → None (propaguje dalej)."""
    from chatbot.middleware import RatelimitedMiddleware

    def get_response(req):
        return None

    mw = RatelimitedMiddleware(get_response)
    # Każdy inny wyjątek niż Ratelimited → return None
    result = mw.process_exception(None, ValueError("foo"))
    assert result is None


def test_middleware_no_ratelimit_view_propagates(settings):
    """Bez settings.RATELIMIT_VIEW → process_exception zwraca None (default 403)."""
    from django_ratelimit.exceptions import Ratelimited

    from chatbot.middleware import RatelimitedMiddleware

    if hasattr(settings, "RATELIMIT_VIEW"):
        delattr(settings, "RATELIMIT_VIEW")

    mw = RatelimitedMiddleware(lambda r: None)
    result = mw.process_exception(None, Ratelimited())
    assert result is None


def test_middleware_invalid_view_path_logs_and_propagates(settings):
    """RATELIMIT_VIEW=invalid path → ImportError → None (fallback)."""
    from django_ratelimit.exceptions import Ratelimited

    from chatbot.middleware import RatelimitedMiddleware

    settings.RATELIMIT_VIEW = "chatbot.views.nonexistent_view_99"

    mw = RatelimitedMiddleware(lambda r: None)
    result = mw.process_exception(None, Ratelimited())
    assert result is None


# =============================================================================
# sanitize — pusty input
# =============================================================================


def test_sanitize_empty_returns_empty():
    """sanitize_user_input("") → "" (early return line 57)."""
    from chatbot.sanitize import sanitize_user_input

    assert sanitize_user_input("") == ""
    assert sanitize_user_input(None) == ""  # type: ignore[arg-type]


# =============================================================================
# services._extract_answer — fallback str(output)
# =============================================================================


def test_extract_answer_str_output_path():
    """Output to string → return output bezpośrednio."""
    from chatbot.services import _extract_answer

    class FakeResult:
        output = "Hello user"
        response = None

    assert _extract_answer(FakeResult()) == "Hello user"


def test_extract_answer_fallback_to_str():
    """Brak output i parts → fallback str(output) — ale output=None → "".

    Edge case: gdy output != None ale to nie-string, fallback str(output).
    """
    from chatbot.services import _extract_answer

    class FakeResultNoneOutput:
        output = None
        response = None

    assert _extract_answer(FakeResultNoneOutput()) == ""


def test_extract_answer_non_str_output_fallback():
    """output to BaseModel-like → str(output) fallback (line 275)."""
    from chatbot.services import _extract_answer

    class CustomOutput:
        def __str__(self):
            return "stringified-output"

    class FakeResult:
        output = CustomOutput()
        response = None

    assert _extract_answer(FakeResult()) == "stringified-output"


def test_extract_answer_with_parts_from_response():
    """output empty, response.parts ma TextPart-y → join."""
    from chatbot.services import _extract_answer

    class TextPart:
        def __init__(self, content):
            self.content = content

    class FakeResponse:
        def __init__(self, parts):
            self.parts = parts

    class FakeResult:
        output = ""
        response = FakeResponse([TextPart("Część A. "), TextPart("Część B.")])

    result = _extract_answer(FakeResult())
    assert "Część A" in result
    assert "Część B" in result


# =============================================================================
# tools — INSPECTIONS_LIST_LIMIT break
# =============================================================================


@pytest.mark.django_db
def test_get_inspections_due_respects_limit():
    """>20 maszyn z overdue inspection_date → tylko 20 zwróconych (line 254)."""
    from datetime import date, timedelta

    from chatbot import tools as chatbot_tools
    from machines.models import Machine

    today = date.today()
    overdue = today - timedelta(days=10)

    for i in range(25):
        Machine.objects.create(
            uid=f"OVR-{i:02d}",
            name=f"Maszyna {i}",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
            inspection_date=overdue,
        )

    result = chatbot_tools.get_inspections_due(days_ahead=14)
    # Limit 20 — machines max 20
    assert len(result.machines) == 20
    # Pełen overdue_count nadal raportowany (>20)
    assert result.overdue_count > 20


# =============================================================================
# admin — title_preview / message_count / role_badge / content_preview
# =============================================================================


@pytest.mark.django_db
def test_admin_title_preview_empty_shows_dash():
    """Conversation.title pusty → "—"."""
    from django.contrib.auth import get_user_model

    from chatbot.admin import ConversationAdmin
    from chatbot.models import Conversation

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest", password="pw")
    conv = Conversation.objects.create(user=user, title="")
    admin = ConversationAdmin(Conversation, None)
    assert admin.title_preview(conv) == "—"


@pytest.mark.django_db
def test_admin_title_preview_shows_title():
    from django.contrib.auth import get_user_model

    from chatbot.admin import ConversationAdmin
    from chatbot.models import Conversation

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest2", password="pw")
    conv = Conversation.objects.create(user=user, title="Moja konwersacja")
    admin = ConversationAdmin(Conversation, None)
    assert admin.title_preview(conv) == "Moja konwersacja"


@pytest.mark.django_db
def test_admin_message_count():
    from django.contrib.auth import get_user_model

    from chatbot.admin import ConversationAdmin
    from chatbot.models import Conversation, Message

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest3", password="pw")
    conv = Conversation.objects.create(user=user, title="X")
    Message.objects.create(conversation=conv, role=Message.Role.USER, content="Hi")
    Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, content="Hello")
    admin = ConversationAdmin(Conversation, None)
    assert admin.message_count(conv) == 2


@pytest.mark.django_db
def test_admin_role_badge_renders_html():
    from django.contrib.auth import get_user_model

    from chatbot.admin import MessageAdmin
    from chatbot.models import Conversation, Message

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest4", password="pw")
    conv = Conversation.objects.create(user=user, title="X")
    msg = Message.objects.create(conversation=conv, role=Message.Role.USER, content="test")
    admin = MessageAdmin(Message, None)
    badge = admin.role_badge(msg)
    assert "bg-blue-100" in badge

    # Test każdej roli (colors dict)
    msg.role = Message.Role.ASSISTANT
    assert "bg-green-100" in admin.role_badge(msg)

    msg.role = Message.Role.SYSTEM
    assert "bg-gray-100" in admin.role_badge(msg)

    msg.role = Message.Role.ERROR
    assert "bg-red-100" in admin.role_badge(msg)


@pytest.mark.django_db
def test_admin_content_preview_long_truncates():
    """content > 80 znaków → truncate z "…"."""
    from django.contrib.auth import get_user_model

    from chatbot.admin import MessageAdmin
    from chatbot.models import Conversation, Message

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest5", password="pw")
    conv = Conversation.objects.create(user=user, title="X")
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.USER,
        content="a" * 200,
    )
    admin = MessageAdmin(Message, None)
    preview = admin.content_preview(msg)
    assert preview.endswith("…")
    assert len(preview) == 81  # 80 + …


@pytest.mark.django_db
def test_admin_content_preview_short_no_truncate():
    from django.contrib.auth import get_user_model

    from chatbot.admin import MessageAdmin
    from chatbot.models import Conversation, Message

    user_model = get_user_model()
    user = user_model.objects.create_user(username="admintest6", password="pw")
    conv = Conversation.objects.create(user=user, title="X")
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.USER,
        content="Krótka treść",
    )
    admin = MessageAdmin(Message, None)
    preview = admin.content_preview(msg)
    assert preview == "Krótka treść"
    assert not preview.endswith("…")


# =============================================================================
# agent.build_agent — wewnętrzne tool callbacki (z monkeypatch tools)
# =============================================================================


@pytest.mark.django_db
def test_build_agent_tool_callbacks_invoked(monkeypatch):
    """Bezpośrednio wywołujemy zarejestrowane tool callbacki agenta.

    Pydantic AI Agent rejestruje @agent.tool dekoratorem; po build_agent
    callbacki są attached na obiekcie. Wymuszamy GEMINI_API_KEY → real
    Agent się tworzy. Po build wywołujemy każdy z czterech tools w
    izolacji, mockując warstwę :mod:`chatbot.tools` (żeby nie uderzać
    do bazy bez setupu).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-fake-1234")
    from chatbot import agent as agent_module
    from chatbot import tools as tools_module

    # Monkey-patch tools.* żeby zwracać pydantic objects z model_dump_json
    class FakeStatus:
        def model_dump_json(self):
            return '{"uid":"X"}'

    class FakeAvail:
        def model_dump_json(self):
            return '{"available":true}'

    class FakeInsp:
        def model_dump_json(self):
            return '{"days_ahead":14}'

    class FakeCost:
        def model_dump_json(self):
            return '{"total":0}'

    monkeypatch.setattr(tools_module, "get_machine_status", lambda uid: FakeStatus())
    monkeypatch.setattr(tools_module, "check_availability", lambda uid, s, e: FakeAvail())
    monkeypatch.setattr(tools_module, "get_inspections_due", lambda days_ahead=14: FakeInsp())
    monkeypatch.setattr(tools_module, "get_service_costs", lambda mt=None, days=90: FakeCost())

    agent = agent_module.build_agent()
    assert agent is not None  # API key present → build success

    # Pydantic AI 1.x: zarejestrowane funkcje w agent._function_toolset.tools
    # (dict name → Tool). Każdy Tool ma .function — wewnętrzna closure z
    # build_agent. Wywołujemy ją z fake ctx żeby pokryć linie 138/145/150/157.

    class _FakeUser:
        is_authenticated = True

        def has_perm(self, _perm):
            return True

    class _FakeDeps:
        user = _FakeUser()

    class FakeCtx:
        # get_service_costs sprawdza uprawnienia przez ctx.deps.user (RBAC kosztów).
        deps = _FakeDeps()

    tools_dict = agent._function_toolset.tools
    # Każda funkcja: delegacja do tools.* (już zmonkeypatched).
    assert tools_dict["get_machine_status"].function(FakeCtx(), "KOP-001") == '{"uid":"X"}'
    assert (
        tools_dict["check_availability"].function(FakeCtx(), "KOP-001", "2026-01-01", "2026-01-05")
        == '{"available":true}'
    )
    assert tools_dict["get_inspections_due"].function(FakeCtx(), 14) == '{"days_ahead":14}'
    assert tools_dict["get_service_costs"].function(FakeCtx(), "koparka", 30) == '{"total":0}'


@pytest.mark.django_db
def test_build_agent_no_api_key_returns_none(monkeypatch):
    """Bez GEMINI_API_KEY → build_agent zwraca None (już pokrywa logger.warning)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from chatbot import agent as agent_module

    result = agent_module.build_agent()
    assert result is None
