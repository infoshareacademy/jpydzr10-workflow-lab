"""Testy symulatora ``voice_repl`` — konstrukcja ramek + tożsamość (bez Gemini/sieci).

Sam most (``run_voice_socket``) jest pokryty w ``test_voice_socket``. Tu weryfikujemy
warstwę adaptera stdin/stdout: że kanał produkuje dokładnie te ramki, których
oczekuje most (``connect`` → ``setup`` → ``prompt``/``interrupt``/``disconnect``),
oraz że ``setup`` niesie podpisany nonce, który ``resolve_caller`` rozwiązuje na
właściwego użytkownika (identyczna tożsamość jak na żywym połączeniu).
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model

from chatbot.management.commands.voice_repl import StdioChannel, build_setup_frame
from chatbot.voice_socket import resolve_caller

User = get_user_model()
pytestmark = pytest.mark.django_db


def _recv(ch: StdioChannel) -> dict:
    return async_to_sync(ch.receive)()


def _decoded(event: dict) -> dict:
    assert event["type"] == "websocket.receive"
    return json.loads(event["text"])


def _drain_handshake(ch: StdioChannel) -> None:
    assert _recv(ch)["type"] == "websocket.connect"
    assert _decoded(_recv(ch))["type"] == "setup"


def test_channel_emits_connect_then_setup():
    ch = StdioChannel({"type": "setup", "callSid": "T", "customParameters": {}})
    assert _recv(ch)["type"] == "websocket.connect"
    setup = _decoded(_recv(ch))
    assert setup["type"] == "setup"
    assert setup["callSid"] == "T"


def test_line_becomes_prompt_frame(monkeypatch):
    ch = StdioChannel({"type": "setup"})
    _drain_handshake(ch)
    monkeypatch.setattr(ch, "_read_line", lambda: "status KOP-001\n")
    assert _decoded(_recv(ch)) == {
        "type": "prompt",
        "voicePrompt": "status KOP-001",
        "last": True,
    }


def test_interrupt_command_becomes_interrupt_frame(monkeypatch):
    ch = StdioChannel({"type": "setup"})
    _drain_handshake(ch)
    monkeypatch.setattr(ch, "_read_line", lambda: "/interrupt\n")
    assert _decoded(_recv(ch)) == {"type": "interrupt"}


def test_quit_command_disconnects(monkeypatch):
    ch = StdioChannel({"type": "setup"})
    _drain_handshake(ch)
    monkeypatch.setattr(ch, "_read_line", lambda: "/quit\n")
    assert _recv(ch)["type"] == "websocket.disconnect"


def test_eof_disconnects(monkeypatch):
    ch = StdioChannel({"type": "setup"})
    _drain_handshake(ch)
    monkeypatch.setattr(ch, "_read_line", lambda: None)  # EOF
    assert _recv(ch)["type"] == "websocket.disconnect"


def test_blank_line_is_skipped(monkeypatch):
    ch = StdioChannel({"type": "setup"})
    _drain_handshake(ch)
    # Pierwsza linia pusta (ignorowana), druga realna → dostajemy dopiero prompt.
    lines = iter(["   \n", "zarezerwuj KOP-001\n"])
    monkeypatch.setattr(ch, "_read_line", lambda: next(lines))
    assert _decoded(_recv(ch))["voicePrompt"] == "zarezerwuj KOP-001"


def test_send_prints_assistant_tokens(capsys):
    ch = StdioChannel({"type": "setup"})
    frame = {
        "type": "websocket.send",
        "text": json.dumps({"type": "text", "token": "Witaj", "last": False}),
    }
    close = {
        "type": "websocket.send",
        "text": json.dumps({"type": "text", "token": "", "last": True}),
    }
    async_to_sync(ch.send)(frame)
    async_to_sync(ch.send)(close)
    assert "Witaj" in capsys.readouterr().out


def test_setup_frame_identity_roundtrips():
    user = User.objects.create_superuser("repl_admin", "r@a.test", "x")
    setup = build_setup_frame(user)
    assert setup["customParameters"]["user_id"] == str(user.pk)
    # Ten sam mechanizm co na żywo: podpisany nonce → resolve_caller → ten user.
    resolved = resolve_caller(setup)
    assert resolved is not None
    assert resolved.pk == user.pk


def test_setup_frame_guest_has_no_user():
    setup = build_setup_frame(None)
    assert setup["customParameters"]["user_id"] == "guest"
    assert resolve_caller(setup) is None
