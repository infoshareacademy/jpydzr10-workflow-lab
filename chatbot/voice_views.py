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
    # Greeting jest TTS-owany przez Twilio na starcie i sygnalizuje rozmówcy, że
    # to JEGO kolej — musi wprost zapraszać do mówienia (inaczej rozmówca czeka
    # w ciszy, nie wiedząc że ma zacząć). Krótko, po ludzku.
    greeting = (
        "Dzień dobry, tu asystent Planera Maszyn Budowlanych. Powiedz, w czym mogę pomóc."
        if user is not None
        else "Dzień dobry, tu asystent Planera Maszyn. Masz dostęp tylko do odczytu — o co chcesz zapytać?"
    )
    user_id = str(user.pk) if user is not None else "guest"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<ConversationRelay url="{escape(ws_url)}" language="pl-PL" '
        'ttsProvider="Google" transcriptionProvider="Google" '
        # interruptible="any": mowa rozmówcy zatrzymuje TTS bota (barge-in po stronie Twilio).
        # reportInputDuringAgentSpeech="speech": Twilio PRZEKAZUJE mowę rozmówcy do serwera
        # także gdy bot mówi (domyślnie 'none' = milczy → most nie wie o przerwaniu na czas).
        # ignoreBackchannel="true": „mhm/aha" nie liczą się jako przerwanie (mniej fałszywych cięć).
        f'welcomeGreeting="{escape(greeting)}" interruptible="any" '
        'reportInputDuringAgentSpeech="speech" ignoreBackchannel="true" '
        'dtmfDetection="true">'
        f'<Parameter name="user_id" value="{escape(user_id)}"/>'
        f'<Parameter name="nonce" value="{escape(nonce)}"/>'
        "</ConversationRelay></Connect></Response>"
    )


def _ws_url(request) -> str:
    """URL gniazda WS agenta (za tunelem cloudflared albo host żądania)."""
    tunnel_host = getattr(settings, "VOICE_TUNNEL_HOST", "") or request.get_host()
    return f"wss://{tunnel_host}/ws/voice/"


# =============================================================================
# PIN — drugi czynnik uwierzytelnienia (DTMF) PRZED podłączeniem Gemini
# =============================================================================
#
# Gdy ``VOICE_REQUIRE_PIN`` jest włączony, znany dzwoniący musi wpisać PIN na
# klawiaturze (DTMF) ZANIM webhook zwróci ``ConversationRelay`` — Gemini NIE
# uruchamia się bez poprawnego PIN (podwójna weryfikacja: numer + PIN; dodatkowo
# oszczędza tokeny). Weryfikacja jest 100% server-side (``verify_voice_pin``),
# nigdy nie ufamy LLM. Liczbę prób ograniczamy DWUWARSTWOWO: per ``CallSid``
# (UX jednego połączenia) ORAZ per NUMER dzwoniącego — twardy limit, którego
# nowe połączenie (= nowy ``CallSid``) NIE resetuje. Bez tej drugiej warstwy
# atakujący z podszytym ``From`` wybierałby numer w kółko, dostając świeże 3
# próby na każde połączenie = nieograniczony brute-force PIN.

_PIN_MAX_ATTEMPTS = 3
_PIN_ATTEMPTS_TTL = 600  # 10 min — okno jednego połączenia
_PIN_FROM_MAX_ATTEMPTS = 10  # twardy limit prób per NUMER (kumulowany przez wiele połączeń)
_PIN_FROM_TTL = 3600  # 1 h — okno kumulacji prób per numer

_NO_PIN_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response>'
    '<Say language="pl-PL">Brak skonfigurowanego PIN-u dla tego numeru. '
    "Skontaktuj się z administratorem.</Say><Hangup/></Response>"
)


def build_gather_pin_twiml(prompt: str) -> str:
    """TwiML proszący o PIN (DTMF). Po zebraniu cyfr Twilio POST-uje na verify-pin."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        '<Gather input="dtmf" numDigits="6" finishOnKey="#" timeout="10" '
        'action="/voice/verify-pin/" method="POST">'
        f'<Say language="pl-PL">{escape(prompt)}</Say>'
        "</Gather>"
        '<Reject reason="rejected"/>'  # brak wpisu (timeout) → odrzuć połączenie
        "</Response>"
    )


def _pin_attempts_key(call_sid: str) -> str:
    return f"voice:pin:attempts:{call_sid or 'unknown'}"


def _bump_pin_attempts(call_sid: str) -> int:
    from django.core.cache import cache

    key = _pin_attempts_key(call_sid)
    count = cache.get(key, 0) + 1
    cache.set(key, count, _PIN_ATTEMPTS_TTL)
    return count


def _clear_pin_attempts(call_sid: str) -> None:
    from django.core.cache import cache

    cache.delete(_pin_attempts_key(call_sid))


def _pin_from_key(e164: str) -> str:
    return f"voice:pin:from:{e164 or 'unknown'}"


def _bump_pin_from_attempts(e164: str) -> int:
    """Zwiększa licznik prób PIN per NUMER (kumulowany między połączeniami)."""
    from django.core.cache import cache

    key = _pin_from_key(e164)
    count = cache.get(key, 0) + 1
    cache.set(key, count, _PIN_FROM_TTL)
    return count


def _pin_from_locked(e164: str) -> bool:
    """True gdy numer wyczerpał twardy limit prób (brute-force wielopołączeniowy)."""
    from django.core.cache import cache

    return cache.get(_pin_from_key(e164), 0) >= _PIN_FROM_MAX_ATTEMPTS


def _clear_pin_from_attempts(e164: str) -> None:
    from django.core.cache import cache

    cache.delete(_pin_from_key(e164))


@csrf_exempt
@require_POST
def voice_verify_pin(request):
    """Weryfikuje PIN wpisany DTMF; po sukcesie łączy z ConversationRelay."""
    if not _signature_valid(request):
        return HttpResponseForbidden("Invalid Twilio signature")

    from_number = request.POST.get("From", "")
    e164 = normalize_phone_e164(from_number)
    user = user_for_phone(e164)
    if user is None:  # defensywnie — webhook incoming już odsiał nieznane numery
        return HttpResponse(_REJECT_TWIML, content_type="text/xml")

    # Twardy limit per NUMER wyczerpany → odrzuć BEZ sprawdzania PIN (brute-force
    # wieloma połączeniami z podszytym From nie obejdzie tego świeżym CallSid).
    if _pin_from_locked(e164):
        logger.warning("Voice verify-pin ZABLOKOWANE (limit per-numer): from=%s", from_number)
        return HttpResponse(_REJECT_TWIML, content_type="text/xml")

    call_sid = request.POST.get("CallSid", "")
    digits = request.POST.get("Digits", "")
    profile = user.profile

    from accounts.services import verify_voice_pin

    if not profile.voice_pin_hash:
        logger.warning("Voice verify-pin: user=%s bez PIN skonfigurowanego.", user.username)
        return HttpResponse(_NO_PIN_TWIML, content_type="text/xml")

    if verify_voice_pin(profile, digits):
        _clear_pin_attempts(call_sid)
        _clear_pin_from_attempts(e164)  # sukces zeruje też twardy licznik per-numer
        logger.info("Voice PIN OK: user=%s call=%s", user.username, call_sid)
        nonce = mint_identity_nonce(user)
        twiml = build_twiml(ws_url=_ws_url(request), user=user, nonce=nonce)
        return HttpResponse(twiml, content_type="text/xml")

    attempts = _bump_pin_attempts(call_sid)
    from_attempts = _bump_pin_from_attempts(e164)
    logger.warning(
        "Voice PIN FAIL: user=%s call=%s próba(połączenie)=%d próba(numer)=%d",
        user.username,
        call_sid,
        attempts,
        from_attempts,
    )
    if attempts >= _PIN_MAX_ATTEMPTS or from_attempts >= _PIN_FROM_MAX_ATTEMPTS:
        _clear_pin_attempts(call_sid)
        return HttpResponse(_REJECT_TWIML, content_type="text/xml")
    return HttpResponse(
        build_gather_pin_twiml("Błędny PIN. Spróbuj ponownie."),
        content_type="text/xml",
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

    # Znany numer + PIN wymagany → poproś o PIN (brama DTMF przed Gemini).
    if user is not None and getattr(settings, "VOICE_REQUIRE_PIN", False):
        # Numer po twardym limicie prób PIN → odrzuć od razu (nie proś o PIN).
        if _pin_from_locked(e164):
            logger.warning(
                "Voice incoming ODRZUCONE (limit PIN per-numer): from=%s user=%s",
                from_number,
                user.username,
            )
            return HttpResponse(_REJECT_TWIML, content_type="text/xml")
        return HttpResponse(
            build_gather_pin_twiml("Podaj swój PIN i zakończ krzyżykiem."),
            content_type="text/xml",
        )

    nonce = mint_identity_nonce(user)
    twiml = build_twiml(ws_url=_ws_url(request), user=user, nonce=nonce)
    return HttpResponse(twiml, content_type="text/xml")
