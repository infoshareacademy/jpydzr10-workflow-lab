"""Testy żywego gniazda głosowego (``chatbot.voice_socket``) na atrapach.

Żywe I/O (Twilio WS + Gemini Live) jest mockowane:

* Twilio WS — atrapa kanału ASGI (``FakeChannel``) z zaprogramowaną sekwencją
  zdarzeń ``receive`` i zbieraniem ``send``;
* Gemini Live — ``_gemini_connect`` podmieniony na atrapę context managera z
  sesją, której ``receive()`` to async-generator zwracający zaprogramowane ramki
  (tekst / tool_call / server_content), a ``send_tool_response`` /
  ``send_client_content`` zapisują wywołania.

Każdy test efektu w bazie ma swój wariant „anty-teatr" — gdyby usunąć kontrolę
(uprawnienia / nonce), test by PADŁ (rezerwacja powstałaby lub nie).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from freezegun import freeze_time

from accounts.models import EmployeeProfile
from chatbot import voice_socket
from chatbot.voice_session import VoiceCallSession
from chatbot.voice_socket import (
    CONFIRM_TOOL,
    build_function_declarations,
    dispatch_tool_call,
    resolve_caller,
)
from chatbot.voice_views import mint_identity_nonce
from machines.models import Machine
from reservations.models import Reservation

User = get_user_model()

pytestmark = pytest.mark.django_db


# =============================================================================
# Atrapy transportu
# =============================================================================


class FakeFC:
    def __init__(self, fc_id, name, args):
        self.id = fc_id
        self.name = name
        self.args = args


class FakeToolCall:
    def __init__(self, function_calls):
        self.function_calls = function_calls


class _FakeTranscript:
    def __init__(self, text):
        self.text = text
        self.finished = False


class FakeServerContent:
    def __init__(self, *, interrupted=False, turn_complete=False, output_text=None):
        self.interrupted = interrupted
        self.turn_complete = turn_complete
        # Realny protokół AUDIO: tekst asystenta przychodzi jako transkrypt wyjścia
        # (``output_transcription``), nie jako ``gmsg.text`` (które przy AUDIO jest puste).
        self.output_transcription = (
            _FakeTranscript(output_text) if output_text is not None else None
        )


class FakeMsg:
    def __init__(self, *, text=None, tool_call=None, server_content=None):
        self.text = text
        self.tool_call = tool_call
        # Gdy test podaje text=..., budujemy ramkę transkryptu wyjścia (realny
        # protokół AUDIO — patrz FakeServerContent).
        if text is not None and server_content is None:
            server_content = FakeServerContent(output_text=text)
        self.server_content = server_content


class FakeGeminiSession:
    """Sesja Gemini Live — jedna ``receive()`` (jeden async-for) na turę."""

    def __init__(self, turns):
        # turns: lista batchy; każdy batch = lista FakeMsg dla jednej tury (prompt).
        self._turns = list(turns)
        self.client_contents = []
        self.tool_responses = []

    async def send_client_content(self, turns, turn_complete):
        self.client_contents.append(turns)

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(function_responses)

    async def receive(self):
        batch = self._turns.pop(0) if self._turns else []
        for msg in batch:
            yield msg


class FakeConnect:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


class FakeChannel:
    """Kanał ASGI WS — zaprogramowane ``receive``, zebrane ``send``."""

    def __init__(self, events):
        self._events = list(events)
        self.sent = []

    async def receive(self):
        if self._events:
            return self._events.pop(0)
        return {"type": "websocket.disconnect"}

    async def send(self, message):
        self.sent.append(message)


def _ws_text(payload: dict) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload, ensure_ascii=False)}


def _setup_event(user) -> dict:
    """Ramka 'setup' Twilio z customParameters (user_id + podpisany nonce)."""
    user_id = str(user.pk) if user is not None else "guest"
    nonce = mint_identity_nonce(user)
    return _ws_text(
        {
            "type": "setup",
            "callSid": "CAtest",
            "customParameters": {"user_id": user_id, "nonce": nonce},
        }
    )


def _run_socket(events, fake_session, monkeypatch) -> FakeChannel:
    monkeypatch.setattr(voice_socket, "_gemini_connect", lambda user: FakeConnect(fake_session))
    channel = FakeChannel(events)
    async_to_sync(voice_socket.run_voice_socket)(
        {"type": "websocket", "path": "/ws/voice/"}, channel.receive, channel.send
    )
    return channel


def _sent_texts(channel: FakeChannel) -> list[dict]:
    """Wyłuskuje JSON ramek 'text' wysłanych do Twilio."""
    return [json.loads(msg["text"]) for msg in channel.sent if msg.get("type") == "websocket.send"]


def _admin():
    return User.objects.create_superuser("vs_admin", "a@a.test", "x")


def _role_user(username, function, phone):
    user = User.objects.create_user(username=username, password="x")
    profile = user.profile
    profile.function = function
    profile.phone = phone
    profile.save(update_fields=["function", "phone", "updated_at"])
    return User.objects.get(pk=user.pk)


def _reservation_args(machine):
    start = date.today() + timedelta(days=4)
    return {
        "machine_uid": machine.uid,
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=3)).isoformat(),
        "person": "Jan Kowalski",
        "address": "ul. Polna 5, Kraków",
        "responsible_person": "Anna Nowak",
    }


# =============================================================================
# build_function_declarations
# =============================================================================


class TestFunctionDeclarations:
    def test_covers_all_actions_and_confirm_tool(self):
        from chatbot.tools import READ_ACTIONS, WRITE_ACTION_PERMS

        names = {d["name"] for d in build_function_declarations()}
        assert names >= set(READ_ACTIONS)
        assert names >= set(WRITE_ACTION_PERMS)
        assert CONFIRM_TOOL in names

    def test_schemas_have_no_gemini_unsupported_keys(self):
        # Gemini odrzuca anyOf/$ref/$defs — czyszczenie MUSI je usunąć.
        blob = json.dumps(build_function_declarations())
        assert "anyOf" not in blob
        assert "$ref" not in blob
        assert "$defs" not in blob

    def test_optional_field_collapses_to_nullable(self):
        decls = {d["name"]: d for d in build_function_declarations()}
        name_field = decls["update_machine"]["parameters"]["properties"]["name"]
        assert name_field["type"] == "string"
        assert name_field["nullable"] is True

    def test_literal_field_keeps_enum(self):
        decls = {d["name"]: d for d in build_function_declarations()}
        reason = decls["cancel_reservation"]["parameters"]["properties"]["reason"]
        assert set(reason["enum"]) == {
            "klient_zrezygnowal",
            "awaria",
            "zmiana_terminu",
            "brak_dostepnosci",
            "inne",
        }


# =============================================================================
# resolve_caller (tożsamość z customParameters + nonce)
# =============================================================================


class TestResolveCaller:
    def _setup_dict(self, user_id, nonce):
        return {"customParameters": {"user_id": user_id, "nonce": nonce}}

    def test_known_user_resolved(self):
        user = _role_user("vs_known", EmployeeProfile.Function.KIEROWNIK, "+48600000201")
        setup = self._setup_dict(str(user.pk), mint_identity_nonce(user))
        assert resolve_caller(setup) == user

    def test_guest_nonce_is_none(self):
        setup = self._setup_dict("guest", mint_identity_nonce(None))
        assert resolve_caller(setup) is None

    def test_forged_nonce_degrades_to_guest(self):
        # Atakujący podstawia user_id admina, ale nonce jest sfałszowany.
        user = _role_user("vs_forge", EmployeeProfile.Function.KIEROWNIK, "+48600000202")
        setup = self._setup_dict(str(user.pk), "999:totally-bogus-signature")
        assert resolve_caller(setup) is None

    def test_mismatched_user_id_vs_nonce_is_guest(self):
        # nonce podpisany dla usera A, ale customParameters.user_id mówi B.
        user_a = _role_user("vs_a", EmployeeProfile.Function.KIEROWNIK, "+48600000203")
        nonce_a = mint_identity_nonce(user_a)
        setup = self._setup_dict("123456", nonce_a)
        assert resolve_caller(setup) is None

    def test_expired_nonce_is_guest(self):
        user = _role_user("vs_exp", EmployeeProfile.Function.KIEROWNIK, "+48600000204")
        with freeze_time("2026-07-01 10:00:00"):
            nonce = mint_identity_nonce(user)
        # +11 min > NONCE_MAX_AGE_SECONDS (600 s).
        with freeze_time("2026-07-01 10:11:00"):
            setup = self._setup_dict(str(user.pk), nonce)
            assert resolve_caller(setup) is None

    def test_inactive_user_is_guest(self):
        user = _role_user("vs_inact", EmployeeProfile.Function.KIEROWNIK, "+48600000205")
        nonce = mint_identity_nonce(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        setup = self._setup_dict(str(user.pk), nonce)
        assert resolve_caller(setup) is None


# =============================================================================
# dispatch_tool_call (routing do dyspozytora)
# =============================================================================


class TestDispatchToolCall:
    def test_write_action_proposes_for_admin(self):
        admin = _admin()
        session = VoiceCallSession(call_sid="CA", user=admin)
        result = dispatch_tool_call(session, "create_reservation", {"machine_uid": "KOP-001"})
        assert "potwierdzasz" in result.lower()
        assert session.has_pending()

    def test_confirm_tool_routes_to_confirm_pending(self):
        admin = _admin()
        machine = Machine.objects.create(
            uid="KOP-DS1",
            name="K",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        session = VoiceCallSession(call_sid="CA", user=admin)
        dispatch_tool_call(session, "create_reservation", _reservation_args(machine))
        assert session.has_pending()
        result = dispatch_tool_call(session, CONFIRM_TOOL, {})
        assert "utworzona" in result.lower()
        assert not session.has_pending()

    def test_guest_write_refused(self):
        session = VoiceCallSession(call_sid="CA", user=None)
        result = dispatch_tool_call(session, "create_reservation", {"machine_uid": "KOP-001"})
        assert "gość" in result.lower() or "gosc" in result.lower()
        assert not session.has_pending()


# =============================================================================
# run_voice_socket — pełna pętla na atrapach
# =============================================================================


class TestRunVoiceSocket:
    def test_first_frame_not_setup_closes(self, monkeypatch):
        # Ramka inna niż 'setup' → gniazdo zamknięte (nie wchodzimy w Gemini).
        events = [
            {"type": "websocket.connect"},
            _ws_text({"type": "prompt", "voicePrompt": "halo"}),
        ]
        channel = _run_socket(events, FakeGeminiSession([]), monkeypatch)
        assert {"type": "websocket.accept"} in channel.sent
        assert {"type": "websocket.close"} in channel.sent

    def test_admin_create_then_confirm_writes_to_db(self, monkeypatch):
        admin = _admin()
        machine = Machine.objects.create(
            uid="KOP-WS1",
            name="Koparka WS",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        args = _reservation_args(machine)
        before = Reservation.objects.count()

        # Tura 1: Gemini woła create_reservation → propozycja → tekst → koniec tury.
        turn1 = [
            FakeMsg(tool_call=FakeToolCall([FakeFC("fc1", "create_reservation", args)])),
            FakeMsg(text="Czy potwierdzasz utworzenie rezerwacji?"),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        # Tura 2: user mówi „tak" → Gemini woła confirm_pending_action → wykonanie.
        turn2 = [
            FakeMsg(tool_call=FakeToolCall([FakeFC("fc2", CONFIRM_TOOL, {})])),
            FakeMsg(text="Rezerwacja utworzona."),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        session = FakeGeminiSession([turn1, turn2])
        events = [
            {"type": "websocket.connect"},
            _setup_event(admin),
            _ws_text({"type": "prompt", "voicePrompt": "Zarezerwuj koparkę"}),
            _ws_text({"type": "prompt", "voicePrompt": "tak"}),
            {"type": "websocket.disconnect"},
        ]
        channel = _run_socket(events, session, monkeypatch)

        # EFEKT W DB — rezerwacja powstała z parametrami z tool_call (anty-teatr:
        # gdyby dispatch nie wykonał confirm, count by się nie zmienił).
        assert Reservation.objects.count() == before + 1
        res = Reservation.objects.latest("pk")
        assert res.machine == machine
        assert res.person == "Jan Kowalski"
        assert res.created_by == admin
        # Twilio dostało zamknięcie obu tur (ramka last=True ×2).
        last_frames = [t for t in _sent_texts(channel) if t.get("last") is True]
        assert len(last_frames) == 2

    def test_guest_write_refused_no_db_change(self, monkeypatch):
        machine = Machine.objects.create(
            uid="KOP-WS2",
            name="K",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        before = Reservation.objects.count()
        turn1 = [
            FakeMsg(
                tool_call=FakeToolCall(
                    [FakeFC("fc1", "create_reservation", _reservation_args(machine))]
                )
            ),
            FakeMsg(text="Niestety nie mogę."),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        session = FakeGeminiSession([turn1])
        events = [
            {"type": "websocket.connect"},
            _setup_event(None),  # gość
            _ws_text({"type": "prompt", "voicePrompt": "Zarezerwuj"}),
            {"type": "websocket.disconnect"},
        ]
        _run_socket(events, session, monkeypatch)

        # Gość nie może pisać → ZERO nowych rezerwacji + odmowa w tool_response.
        assert Reservation.objects.count() == before
        result = session.tool_responses[0][0].response["result"]
        assert "gość" in result.lower() or "gosc" in result.lower()

    def test_guest_can_read(self, monkeypatch):
        Machine.objects.create(
            uid="KOP-WS3",
            name="Czytana",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        turn1 = [
            FakeMsg(
                tool_call=FakeToolCall([FakeFC("fc1", "get_machine_status", {"uid": "KOP-WS3"})])
            ),
            FakeMsg(text="Maszyna jest w magazynie."),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        session = FakeGeminiSession([turn1])
        events = [
            {"type": "websocket.connect"},
            _setup_event(None),  # gość
            _ws_text({"type": "prompt", "voicePrompt": "Status koparki KOP-WS3"}),
            {"type": "websocket.disconnect"},
        ]
        _run_socket(events, session, monkeypatch)

        # Odczyt wykonany mimo gościa — wynik zawiera UID maszyny.
        result = session.tool_responses[0][0].response["result"]
        assert "KOP-WS3" in result
        assert '"found":true' in result.replace(" ", "")

    def test_barge_in_ends_turn_without_last_frame(self, monkeypatch):
        admin = _admin()
        # Gemini sygnalizuje przerwanie (interrupted) — tura kończy się BEZ last=True.
        turn1 = [
            FakeMsg(text="Zaczynam mówić…"),
            FakeMsg(server_content=FakeServerContent(interrupted=True)),
            FakeMsg(text="tego nie powinno być"),
        ]
        session = FakeGeminiSession([turn1])
        events = [
            {"type": "websocket.connect"},
            _setup_event(admin),
            _ws_text({"type": "prompt", "voicePrompt": "Opowiedz o flocie"}),
            {"type": "websocket.disconnect"},
        ]
        channel = _run_socket(events, session, monkeypatch)
        texts = _sent_texts(channel)
        # Wysłano pierwszy fragment, ale NIE domknięcie tury (last=True) ani tekst po interrupt.
        assert any(t.get("token") == "Zaczynam mówić…" for t in texts)
        assert all(t.get("last") is not True for t in texts)
        assert all(t.get("token") != "tego nie powinno być" for t in texts)

    def test_asgi_router_sends_voice_ws_to_voice_handler(self, monkeypatch):
        import planer_config.asgi as asgi
        from chatbot import voice_consumer

        called = {}

        async def fake_voice(scope, receive, send):
            called["path"] = scope["path"]

        async def _noop():
            return {}

        async def _noop_send(_m):
            return None

        monkeypatch.setattr(voice_consumer, "run_voice_socket", fake_voice)
        async_to_sync(asgi.application)(
            {"type": "websocket", "path": asgi.VOICE_WS_PATH}, _noop, _noop_send
        )
        assert called.get("path") == "/ws/voice/"

    def test_asgi_router_sends_non_voice_to_django(self, monkeypatch):
        import planer_config.asgi as asgi

        called = {}

        async def fake_django(scope, receive, send):
            called["type"] = scope["type"]

        async def _noop():
            return {}

        async def _noop_send(_m):
            return None

        monkeypatch.setattr(asgi, "_django_app", fake_django)
        async_to_sync(asgi.application)({"type": "http", "path": "/maszyny/"}, _noop, _noop_send)
        assert called.get("type") == "http"

    def test_router_path_matches_twiml_ws_url(self, client):
        # Guard przeciw dryfowi: ścieżka routera ASGI musi być tą samą, którą
        # webhook wstawia do TwiML (wss://.../ws/voice/). Rozjazd literałów =
        # martwe gniazdo na scenie.
        import planer_config.asgi as asgi

        resp = client.post("/voice/incoming/", {"From": "+48999999999", "CallSid": "CA1"})
        assert asgi.VOICE_WS_PATH in resp.content.decode("utf-8")

    def test_interrupt_frame_clears_pending(self, monkeypatch):
        admin = _admin()
        machine = Machine.objects.create(
            uid="KOP-WS4",
            name="K",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        before = Reservation.objects.count()
        # Tura 1: propozycja create. Następnie ramka 'interrupt' z Twilio czyści
        # wiszącą akcję. Tura 2: „tak" → confirm_pending nie ma czego wykonać.
        turn1 = [
            FakeMsg(
                tool_call=FakeToolCall(
                    [FakeFC("fc1", "create_reservation", _reservation_args(machine))]
                )
            ),
            FakeMsg(text="Potwierdź?"),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        turn2 = [
            FakeMsg(tool_call=FakeToolCall([FakeFC("fc2", CONFIRM_TOOL, {})])),
            FakeMsg(text="Nie ma nic do potwierdzenia."),
            FakeMsg(server_content=FakeServerContent(turn_complete=True)),
        ]
        session = FakeGeminiSession([turn1, turn2])
        events = [
            {"type": "websocket.connect"},
            _setup_event(admin),
            _ws_text({"type": "prompt", "voicePrompt": "Zarezerwuj"}),
            _ws_text({"type": "interrupt"}),
            _ws_text({"type": "prompt", "voicePrompt": "tak"}),
            {"type": "websocket.disconnect"},
        ]
        _run_socket(events, session, monkeypatch)
        # Po interrupt wisząca akcja skasowana → confirm nic nie utworzył.
        assert Reservation.objects.count() == before
        confirm_result = session.tool_responses[1][0].response["result"]
        assert "oczekując" in confirm_result.lower()
