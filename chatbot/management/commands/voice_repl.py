"""Lokalny symulator agenta głosowego — iteracja bez telefonu, tunelu i Twilio.

Uruchamia PRAWDZIWY most :func:`chatbot.voice_socket.run_voice_socket` z prawdziwą
sesją Gemini Live, ale kanał Twilio zastępuje ``stdin``/``stdout``: piszesz
wypowiedź (jak przez telefon), widzisz odpowiedź agenta w sekundy. Omija telefon,
tunel cloudflared, ConversationRelay, bramkę PIN i rozpoznawanie mowy (STT) — dzięki
czemu iterację nad promptem, doborem narzędzi i RBAC robi się w sekundy zamiast
minut. Realny telefon zostaje na finalną weryfikację end-to-end (telefonia + STT + TTS).

Tożsamość rozmówcy podstawiana jest jak w realnym połączeniu — przez podpisany
``nonce`` (``mint_identity_nonce``) w ramce ``setup``, więc ``resolve_caller`` i cała
warstwa RBAC działają identycznie jak na żywo.

Użycie:
    make voice-repl                  # rola admin (konto sebastian)
    make voice-repl ROLE=montazysta  # read-only — agent odmówi zapisu

W trakcie:  wpisz wypowiedź + Enter.  ``/interrupt`` = ramka barge-in (jak przerwanie
mową),  ``/quit`` = koniec.
"""

from __future__ import annotations

import asyncio
import json
import sys

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from chatbot import voice_socket
from chatbot.voice_views import mint_identity_nonce

User = get_user_model()

# Mapowanie roli → konto demo (spójne z ``chatbot_roleplay``). ``None`` = gość.
ROLE_USERNAME: dict[str, str | None] = {
    "admin": "sebastian",
    "kierownik": "seba1",
    "magazynier": "seba2",
    "montazysta": "seba3",
    "guest": None,
}

_CYAN = "\033[1;36m"
_YELLOW = "\033[1;33m"
_RESET = "\033[0m"


class StdioChannel:
    """Kanał ASGI WebSocket dla REPL — ``receive`` czyta stdin, ``send`` drukuje token.

    Produkuje dokładnie te ramki, których oczekuje ``run_voice_socket``
    (``websocket.connect`` → ``setup`` → kolejne ``prompt``/``interrupt`` →
    ``disconnect``), i konsumuje ramki ``{"type":"text",...}`` wysyłane przez most.
    """

    def __init__(self, setup_frame: dict):
        self._queue: list[dict] = [
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "text": json.dumps(setup_frame, ensure_ascii=False)},
        ]
        self._bot_started = False

    async def receive(self) -> dict:
        if self._queue:
            return self._queue.pop(0)
        line = await asyncio.to_thread(self._read_line)
        if line is None:  # EOF (Ctrl-D / potok wyczerpany)
            return {"type": "websocket.disconnect"}
        line = line.strip()
        if line in ("/quit", "/q", "exit"):
            return {"type": "websocket.disconnect"}
        if line == "/interrupt":
            return {"type": "websocket.receive", "text": json.dumps({"type": "interrupt"})}
        if not line:  # pusta linia — poproś ponownie, nie wysyłaj pustej tury
            return await self.receive()
        frame = {"type": "prompt", "voicePrompt": line, "last": True}
        return {"type": "websocket.receive", "text": json.dumps(frame, ensure_ascii=False)}

    @staticmethod
    def _read_line() -> str | None:
        sys.stdout.write(f"\n{_CYAN}Ty ›{_RESET} ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        return line if line else None

    async def send(self, message: dict) -> None:
        if message.get("type") != "websocket.send":
            return
        try:
            payload = json.loads(message.get("text") or "{}")
        except json.JSONDecodeError:
            return
        if payload.get("type") != "text":
            return
        token = payload.get("token", "")
        if token:
            if not self._bot_started:
                sys.stdout.write(f"\n{_YELLOW}Bot ›{_RESET} ")
                self._bot_started = True
            sys.stdout.write(token)
            sys.stdout.flush()
        if payload.get("last"):
            if self._bot_started:
                sys.stdout.write("\n")
            self._bot_started = False
            sys.stdout.flush()


def build_setup_frame(user) -> dict:
    """Ramka ``setup`` z podpisanym nonce — identyczna tożsamość jak na żywo."""
    return {
        "type": "setup",
        "callSid": "REPL-LOCAL",
        "customParameters": {
            "user_id": str(user.pk) if user is not None else "guest",
            "nonce": mint_identity_nonce(user),
        },
    }


class Command(BaseCommand):
    help = (
        "Lokalny symulator agenta głosowego (Gemini Live realny, Twilio zastąpiony stdin/stdout)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--role",
            default="admin",
            choices=sorted(ROLE_USERNAME),
            help="Rola rozmówcy (mapowana na konto demo). Domyślnie admin.",
        )

    def handle(self, *args, **options):
        # Wycisz hałaśliwe biblioteki I/O — REPL ma pokazywać tylko rozmowę, nie
        # ramki WebSocket. (Profil 'voice' loguje na DEBUG dla serwera na żywo.)
        import logging

        for noisy in ("websockets", "websockets.client", "google_genai", "urllib3", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        # Model Live jest tylko w profilu ustawień 'voice' — bez niego _gemini_connect
        # rzuci AttributeError. Kierujemy usera na właściwe uruchomienie.
        if not getattr(settings, "GEMINI_LIVE_MODEL", None):
            raise CommandError(
                "Brak GEMINI_LIVE_MODEL w ustawieniach — uruchom przez `make voice-repl` "
                "(profil 'voice'), nie zwykłym `manage.py`."
            )

        role = options["role"]
        username = ROLE_USERNAME[role]
        user = None
        if username is not None:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(
                    f"Konto demo '{username}' nie istnieje — uruchom najpierw `make seed`."
                ) from exc

        who = f"{role} ({username})" if username else "gość (nieznany numer)"
        self.stdout.write(self.style.SUCCESS(f"\n🎙  voice_repl — rozmawiasz jako: {who}"))
        self.stdout.write(
            "Wpisz wypowiedź + Enter (jak przez telefon). "
            "Komendy: /interrupt = barge-in, /quit = koniec.\n"
        )

        channel = StdioChannel(build_setup_frame(user))
        scope = {"type": "websocket", "path": "/ws/voice/"}
        try:
            async_to_sync(voice_socket.run_voice_socket)(scope, channel.receive, channel.send)
        except KeyboardInterrupt:
            self.stdout.write("\nPrzerwano (Ctrl-C).")
        self.stdout.write(self.style.SUCCESS("\n— koniec sesji voice_repl —"))
