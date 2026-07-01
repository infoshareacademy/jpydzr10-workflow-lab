"""Webhook połączenia przychodzącego Twilio dla agenta głosowego.

Synchroniczny widok Django:

1. (opcjonalnie) waliduje podpis ``X-Twilio-Signature`` — aktywne gdy w
   środowisku jest ``TWILIO_AUTH_TOKEN``; bez niego (dev/test) walidacja jest
   pomijana z ostrzeżeniem.
2. normalizuje numer dzwoniącego ``From`` → E.164 → :func:`accounts.services.user_for_phone`
   → User (albo gość, gdy numer nieznany/zastrzeżony).
3. podpisuje krótkotrwały nonce (``TimestampSigner``: user_id) przekazywany do WS.
4. zwraca TwiML ``<Connect><ConversationRelay ...>`` kierujący Twilio do gniazda WS.

Gniazdo WS (live, Gemini Live) jest budowane osobno w ``voice_consumer.py`` i
jest bramkowane konfiguracją uruchomienia na żywo (model Gemini Live, tunel).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.signing import TimestampSigner
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.services import user_for_phone
from core.validators import normalize_phone_e164

logger = logging.getLogger("chatbot")

_NONCE_SALT = "voice-call-identity"

# TwiML odrzucający połączenie z numeru spoza białej listy — zwracany ZANIM
# powstanie ConversationRelay, więc Gemini pozostaje nietknięty (zero tokenów).
_REJECT_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response><Reject reason="rejected"/></Response>'
)


def mint_identity_nonce(user) -> str:
    """Podpisany, krótkotrwały token tożsamości dzwoniącego dla warstwy WS."""
    signer = TimestampSigner(salt=_NONCE_SALT)
    user_id = str(user.pk) if user is not None else "guest"
    return signer.sign(user_id)


def _reconstructed_url(request) -> str:
    """Odtwarza pełny URL żądania z nagłówków forwardowanych (za tunelem)."""
    host = request.META.get("HTTP_X_FORWARDED_HOST") or request.get_host()
    proto = request.META.get("HTTP_X_FORWARDED_PROTO", "https")
    return f"{proto}://{host}{request.get_full_path()}"


def _signature_valid(request) -> bool:
    """Waliduje podpis Twilio.

    Bez ``TWILIO_AUTH_TOKEN`` zachowanie zależy od ``VOICE_REQUIRE_SIGNATURE``:

    * ``True`` (prod / profil ``voice`` za publicznym tunelem) → **fail-closed**:
      odrzucamy żądanie, bo bez tokenu nie sposób odróżnić prawdziwego Twilio od
      podszywającego się klienta (sfałszowany ``From`` = podszycie pod uprawnionego).
    * ``False`` (dev / test) → bypass z ostrzeżeniem, by rozwijać lokalnie bez tokenu.
    """
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", None) or _env_auth_token()
    if not auth_token:
        if getattr(settings, "VOICE_REQUIRE_SIGNATURE", True):
            logger.error(
                "Voice webhook: brak TWILIO_AUTH_TOKEN przy VOICE_REQUIRE_SIGNATURE=True "
                "— odrzucam żądanie (fail-closed)."
            )
            return False
        logger.warning("Voice webhook: brak TWILIO_AUTH_TOKEN — pomijam walidację podpisu (dev).")
        return True
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
    # ``POST.dict()`` spłaszcza QueryDict do {klucz: wartość}. To kanoniczny format
    # dla ``RequestValidator.validate`` i jest bezpieczny dla webhooków Twilio:
    # parametry połączenia (From/To/CallSid/...) są jednowartościowe, a Twilio liczy
    # podpis nad tymi samymi pojedynczymi wartościami. (Pełny QueryDict zepsułby
    # walidację — validate() oczekuje płaskiego dict.)
    return validator.validate(_reconstructed_url(request), request.POST.dict(), signature)


def _env_auth_token() -> str:
    import os

    return os.environ.get("TWILIO_AUTH_TOKEN", "")


def build_twiml(*, ws_url: str, user, nonce: str) -> str:
    """Buduje odpowiedź TwiML kierującą do ConversationRelay (STT+TTS po stronie Twilio)."""
    greeting = (
        "Łączę z asystentem Planera Maszyn."
        if user is not None
        else "Łączę z asystentem. Dostęp tylko do odczytu."
    )
    user_id = str(user.pk) if user is not None else "guest"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<ConversationRelay url="{escape(ws_url)}" language="pl-PL" '
        'ttsProvider="Google" transcriptionProvider="Google" '
        f'welcomeGreeting="{escape(greeting)}" interruptible="any" dtmfDetection="true">'
        f'<Parameter name="user_id" value="{escape(user_id)}"/>'
        f'<Parameter name="nonce" value="{escape(nonce)}"/>'
        "</ConversationRelay></Connect></Response>"
    )


@csrf_exempt
@require_POST
def voice_incoming(request):
    """Webhook połączenia przychodzącego — zwraca TwiML z ConversationRelay."""
    if not _signature_valid(request):
        return HttpResponseForbidden("Invalid Twilio signature")

    from_number = request.POST.get("From", "")
    e164 = normalize_phone_e164(from_number)
    user = user_for_phone(e164)
    # Biały list: numer spoza bazy (nieznany / nieaktywny / zanonimizowany) →
    # ODRZUĆ zanim cokolwiek dotknie Gemini (anti-token-drain — „nie da się
    # dodzwonić" z nieautoryzowanego numeru). Flaga off (dev/test) → dawny gość
    # read-only, dla lokalnego debugowania ścieżki gościa.
    if user is None and getattr(settings, "VOICE_REJECT_UNKNOWN_CALLERS", True):
        logger.warning("Voice incoming ODRZUCONE (biały list): nieznany numer from=%s", from_number)
        return HttpResponse(_REJECT_TWIML, content_type="text/xml")
    logger.info(
        "Voice incoming: from=%s e164=%s → %s",
        from_number,
        e164,
        getattr(user, "username", "guest"),
    )

    nonce = mint_identity_nonce(user)
    tunnel_host = getattr(settings, "VOICE_TUNNEL_HOST", "") or request.get_host()
    ws_url = f"wss://{tunnel_host}/ws/voice/"
    twiml = build_twiml(ws_url=ws_url, user=user, nonce=nonce)
    return HttpResponse(twiml, content_type="text/xml")
