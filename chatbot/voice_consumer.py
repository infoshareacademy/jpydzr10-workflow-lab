"""Orkiestracja tury agenta głosowego — logika propozycja → potwierdzenie.

Część TESTOWALNA (bez I/O): dyspozytor akcji ``propose_or_execute`` /
``confirm_pending`` REUŻYWA narzędzi czatu (``chatbot.tools``) i mechanizmu
uprawnień (``_check_user_can``), więc agent głosowy stosuje DOKŁADNIE te same
reguły co czat (admin pisze, montażysta tylko czyta, gość tylko czyta).

Część BRAMKOWANA (I/O, integracja): ``run_voice_socket`` — żywe gniazdo WS do
Twilio ConversationRelay + Gemini Live. Wymaga zamrożonego ``GEMINI_LIVE_MODEL``
(po weryfikacji dostępu do Gemini Live) oraz konfiguracji telefonii i tunelu.
NIE jest pokrywane testami jednostkowymi i pozostaje szkieletem do domknięcia
przy uruchamianiu na żywo.
"""

from __future__ import annotations

import logging

from chatbot.tools import (
    READ_ACTIONS,
    WRITE_ACTION_PERMS,
    _check_user_can,
    execute_confirmed_action,
    execute_read_action,
)
from chatbot.voice_session import VoiceCallSession

logger = logging.getLogger("chatbot")

_REFUSAL = "Nie masz uprawnień do tej operacji."
_GUEST_REFUSAL = "Ta operacja wymaga zalogowanego konta. Dzwonisz jako gość."
_UNKNOWN_ACTION = "Nie rozpoznaję tej operacji."

# Maksymalny wiek nonce tożsamości (sekundy). Połączenie głosowe nie żyje
# dłużej niż kilka minut, więc krótki TTL zamyka okno replay przechwyconego
# nonce. Egzekwowane przez ``TimestampSigner.unsign(nonce, max_age=...)`` przy
# domykaniu ``run_voice_socket`` na żywo.
NONCE_MAX_AGE_SECONDS = 600


def build_user_perms_summary(user) -> str:
    """Krótkie podsumowanie dozwolonych akcji zapisujących — do system promptu.

    Współdzielone między czatem a głosem: LLM dostaje jasny zakres tego, co
    dany użytkownik (po caller-ID) może zlecić, więc nie proponuje akcji ponad
    uprawnienia.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return "Rozmówca jest gościem — dostęp wyłącznie do odczytu."
    allowed = sorted(a for a in WRITE_ACTION_PERMS if _check_user_can(user, a) is None)
    if not allowed:
        return "Rozmówca może wyłącznie odczytywać dane (brak akcji zapisujących)."
    return "Rozmówca może wykonywać akcje zapisujące: " + ", ".join(allowed) + "."


def propose_or_execute(session: VoiceCallSession, action: str, params: dict) -> str:
    """Dla akcji zapisującej: sprawdź uprawnienia i zapamiętaj do potwierdzenia.
    Dla akcji odczytu: wykonaj od razu. Zwraca tekst do wypowiedzenia."""
    if action in WRITE_ACTION_PERMS:
        if session.is_guest:
            return _GUEST_REFUSAL
        if _check_user_can(session.user, action) is not None:
            return _REFUSAL
        session.propose(action, params)
        return f"Czy potwierdzasz akcję „{action}”? Powiedz tak, aby wykonać."
    if action in READ_ACTIONS:
        # Akcje odczytu — bez potwierdzenia, dostępne także gościom (read-only).
        # Przekazujemy usera: wrażliwe odczyty (koszty serwisowe) wymagają
        # uprawnień tak samo jak w UI (montażysta/gość ich nie zobaczy).
        return execute_read_action(action, params, session.user)
    return _UNKNOWN_ACTION


def confirm_pending(session: VoiceCallSession) -> str:
    """Wykonuje akcję oczekującą po głosowym „tak”. Zwraca tekst do wypowiedzenia."""
    if not session.has_pending():
        return "Nie ma akcji oczekującej na potwierdzenie."
    action, params = session.confirm()
    result = execute_confirmed_action(action, params, session.user)
    logger.info("Voice confirm: action=%s user=%s", action, getattr(session.user, "pk", None))
    return result


async def run_voice_socket(scope, receive, send):
    """Żywa pętla WS (Twilio ConversationRelay ↔ Gemini Live).

    Implementacja żyje w :mod:`chatbot.voice_socket` (transport WS + most do
    Gemini Live). Tu zostaje cienki delegat, by zachować historyczny punkt
    wejścia i uniknąć cyklicznego importu (``voice_socket`` importuje dyspozytor
    z tego modułu). Routing ASGI ``/ws/voice/`` wskazuje na tę funkcję.
    """
    from chatbot.voice_socket import run_voice_socket as _impl

    return await _impl(scope, receive, send)
