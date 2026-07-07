"""Żywe gniazdo WebSocket agenta głosowego: Twilio ConversationRelay ↔ Gemini Live.

Twilio robi STT (mowa→tekst) i TTS (tekst→mowa); MY mostkujemy warstwę LLM.
Protokół po stronie Twilio (ramki JSON):

* ``{"type":"setup", ..., "customParameters":{"user_id":"123","nonce":"123:sig"}}``
  — pierwsza ramka; ``customParameters`` pochodzą z ``<Parameter>`` w TwiML
  (patrz :func:`chatbot.voice_views.build_twiml`).
* ``{"type":"prompt","voicePrompt":"<transkrypcja>","last":true}`` — wypowiedź usera.
* ``{"type":"interrupt", ...}`` — barge-in (user przerwał TTS).

Wysyłamy do Twilio strumień ``{"type":"text","token":"<chunk>","last":false}`` i na
końcu tury ``{"type":"text","token":"","last":true}``.

Po stronie Gemini Live (``google-genai`` 2.3.0, async): tool-calling robi GEMINI
(nie Twilio). Na ``tool_call`` wołamy ten sam dyspozytor co czat
(:func:`chatbot.voice_consumer.propose_or_execute` / :func:`confirm_pending`), więc
głos stosuje DOKŁADNIE te same reguły uprawnień. Pseudo-narzędzie
``confirm_pending_action`` pozwala Gemini potwierdzić wiszącą akcję na „tak"
zamiast kruchego dopasowania słów kluczowych.

Bezpieczeństwo: tożsamość dzwoniącego pochodzi z ``setup.customParameters`` (nie z
ponownego lookupu numeru w WS — to zrobił już webhook). Podpisany ``nonce`` jest
weryfikowany z ``max_age`` (okno replay), a jego ładunek (``user_id``) musi się
zgadzać z jawnym ``customParameters.user_id``. Każda nieprawidłowość → degradacja
do GOŚCIA (read-only) — nigdy eskalacja.

Cała warstwa ORM (rozpoznanie usera, dyspozytor narzędzi) jest synchroniczna i
owijana ``asgiref.sync.sync_to_async`` (NIE ``channels.db`` — projekt nie używa
Channels; pętla WS to surowe ASGI obsługiwane natywnie przez uvicorn).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from chatbot.sanitize import sanitize_user_input, wrap_user_input
from chatbot.tools import WRITE_ACTION_PERMS
from chatbot.voice_consumer import (
    NONCE_MAX_AGE_SECONDS,
    build_user_perms_summary,
    confirm_pending,
    propose_or_execute,
)
from chatbot.voice_session import VoiceCallSession
from chatbot.voice_views import _NONCE_SALT

logger = logging.getLogger("chatbot")

User = get_user_model()

# Pseudo-narzędzie potwierdzenia — Gemini woła je gdy user powie „tak"/„potwierdzam",
# zamiast kruchego keyword-matchingu po naszej stronie.
CONFIRM_TOOL = "confirm_pending_action"


# =============================================================================
# FUNCTION DECLARATIONS — schematy narzędzi dla Gemini (oczyszczone)
# =============================================================================
#
# ``model_json_schema()`` z Pydantica produkuje ``anyOf`` (dla pól Optional) oraz
# klucze walidacyjne (pattern/maxLength/...), których schemat funkcji Gemini nie
# akceptuje. ``_gemini_clean`` spłaszcza ``anyOf [T, null]`` → ``T`` z
# ``nullable=True`` i usuwa nieobsługiwane klucze. (Modele ``*Params`` są płaskie —
# nie ma zagnieżdżonych ``$ref``/``$defs`` — ale i tak je usuwamy defensywnie.)

# Klucze walidacyjne JSON Schema, których nie przekazujemy do Gemini.
_DROP_KEYS = frozenset(
    {
        "maxLength",
        "minLength",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "default",
        "title",
        "additionalProperties",
        "$defs",
        "$ref",
        "format",
    }
)


def _gemini_clean(schema: dict) -> dict:
    """Rekurencyjnie oczyszcza JSON Schema do podzbioru akceptowanego przez Gemini."""
    schema = dict(schema)
    schema.pop("$defs", None)

    if "anyOf" in schema:
        variants = [v for v in schema["anyOf"] if v.get("type") != "null"]
        nullable = any(v.get("type") == "null" for v in schema["anyOf"])
        base = _gemini_clean(variants[0]) if variants else {"type": "string"}
        if nullable:
            base["nullable"] = True
        if schema.get("description") and "description" not in base:
            base["description"] = schema["description"]
        return base

    cleaned = {k: v for k, v in schema.items() if k not in _DROP_KEYS}

    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["properties"] = {k: _gemini_clean(v) for k, v in cleaned["properties"].items()}
    if "items" in cleaned:
        cleaned["items"] = _gemini_clean(cleaned["items"])
    return cleaned


# Mapowanie akcji zapisującej → model parametrów (źródło schematu dla Gemini).
def _write_param_models() -> dict[str, Any]:
    from chatbot import tools as t

    return {
        "create_reservation": t.CreateReservationParams,
        "cancel_reservation": t.CancelReservationParams,
        "change_operator": t.ChangeOperatorParams,
        "swap_machine": t.SwapMachineParams,
        "set_machine_to_service": t.SetMachineToServiceParams,
        "create_service_record": t.CreateServiceRecordParams,
        "update_service_record": t.UpdateServiceRecordParams,
        "update_machine_inspection_date": t.UpdateMachineInspectionDateParams,
        "confirm_reservation": t.ConfirmReservationParams,
        "complete_reservation": t.CompleteReservationParams,
        "update_reservation": t.UpdateReservationParams,
        "report_breakdown": t.ReportBreakdownParams,
        "create_machine": t.CreateMachineParams,
        "update_machine": t.UpdateMachineParams,
        "return_machine": t.ReturnMachineParams,
        "close_repair_machine": t.CloseRepairMachineParams,
        "retire_machine": t.RetireMachineParams,
        "create_site": t.CreateSiteParams,
        "update_site": t.UpdateSiteParams,
        "delete_site": t.DeleteSiteParams,
        "terminate_employee": t.TerminateEmployeeParams,
        "anonymize_employee": t.AnonymizeEmployeeParams,
    }


# Schematy narzędzi odczytu (zwykłe funkcje, nie modele Pydantic — opisujemy ręcznie).
_READ_PARAM_SCHEMAS: dict[str, dict] = {
    "get_machine_status": {
        "type": "object",
        "properties": {"uid": {"type": "string", "description": "UID maszyny (np. KOP-001)"}},
        "required": ["uid"],
    },
    "check_availability": {
        "type": "object",
        "properties": {
            "uid": {"type": "string", "description": "UID maszyny"},
            "start_date": {"type": "string", "description": "Data od (ISO YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "Data do (ISO YYYY-MM-DD)"},
        },
        "required": ["uid", "start_date", "end_date"],
    },
    "get_inspections_due": {
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "Horyzont w dniach (domyślnie 14)"}
        },
        "required": [],
    },
    "get_service_costs": {
        "type": "object",
        "properties": {
            "machine_type": {
                "type": "string",
                "nullable": True,
                "description": "Filtr typu maszyny (opcjonalny)",
            },
            "days": {"type": "integer", "description": "Okno w dniach (domyślnie 90)"},
        },
        "required": [],
    },
    "get_machine_service_history": {
        "type": "object",
        "properties": {
            "uid": {"type": "string", "description": "UID maszyny (np. KOP-001)"},
            "limit": {
                "type": "integer",
                "description": "Ile ostatnich wpisów serwisowych (domyślnie 5)",
            },
        },
        "required": ["uid"],
    },
}


def build_function_declarations() -> list[dict]:
    """Buduje listę deklaracji funkcji (dict JSON-schema) dla Gemini Live.

    Zwraca dict-y nadające się jako ``FunctionDeclaration.parameters_json_schema``
    (czyste — bez ``anyOf``/``$ref``/``$defs``). Obejmuje: 4 narzędzia odczytu, wszystkie
    akcje zapisujące z :data:`WRITE_ACTION_PERMS` oraz pseudo-narzędzie
    :data:`CONFIRM_TOOL`.
    """
    declarations: list[dict] = []

    for action, schema in _READ_PARAM_SCHEMAS.items():
        declarations.append(
            {
                "name": action,
                "description": f"Akcja odczytu: {action} (bez efektów ubocznych, dostępna gościom).",
                "parameters": _gemini_clean(schema),
            }
        )

    param_models = _write_param_models()
    for action in WRITE_ACTION_PERMS:
        model = param_models.get(action)
        if model is None:  # pragma: no cover - mapowanie pełne, ale defensywnie
            continue
        declarations.append(
            {
                "name": action,
                "description": (
                    f"Akcja zapisująca: {action}. Wymaga uprawnień i POTWIERDZENIA głosowego "
                    f"(po wywołaniu poproś o „tak” i dopiero wtedy wywołaj {CONFIRM_TOOL})."
                ),
                "parameters": _gemini_clean(model.model_json_schema()),
            }
        )

    declarations.append(
        {
            "name": CONFIRM_TOOL,
            "description": (
                "Potwierdza wiszącą akcję zapisującą — wywołaj DOPIERO gdy rozmówca powie "
                "„tak”/„potwierdzam” po zaproponowanej akcji."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    )
    return declarations


# =============================================================================
# TOŻSAMOŚĆ DZWONIĄCEGO (z setup.customParameters)
# =============================================================================


def resolve_caller(setup: dict):
    """Rozpoznaje usera z ramki ``setup`` Twilio (``customParameters``).

    Zwraca obiekt ``User`` dla zweryfikowanego, znanego dzwoniącego albo ``None``
    (gość, read-only). Degradacja do gościa przy KAŻDEJ nieprawidłowości — nigdy
    eskalacja:

    * ``nonce`` weryfikowany ``TimestampSigner.unsign(..., max_age=...)`` — zły/
      wygasły podpis → gość;
    * ładunek nonce (``user_id``) musi się zgadzać z jawnym ``customParameters.user_id``
      (inaczej ktoś podmienił jeden bez drugiego) → gość;
    * ``"guest"`` lub nieistniejący/nieaktywny user → gość.
    """
    custom = (setup or {}).get("customParameters") or {}
    claimed_user_id = str(custom.get("user_id", "guest"))
    nonce = custom.get("nonce", "")

    signer = TimestampSigner(salt=_NONCE_SALT)
    try:
        signed_user_id = signer.unsign(nonce, max_age=NONCE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        logger.warning("Voice WS: nieprawidłowy/wygasły nonce — degradacja do gościa.")
        return None

    if signed_user_id != claimed_user_id:
        logger.warning(
            "Voice WS: nonce (%s) ≠ customParameters.user_id (%s) — gość.",
            signed_user_id,
            claimed_user_id,
        )
        return None
    if signed_user_id == "guest":
        return None

    try:
        return User.objects.get(pk=int(signed_user_id), is_active=True)
    except (User.DoesNotExist, ValueError):
        logger.warning("Voice WS: user_id=%s nie odpowiada aktywnemu kontu — gość.", signed_user_id)
        return None


def dispatch_tool_call(session: VoiceCallSession, name: str, args: dict) -> str:
    """Kieruje wywołanie narzędzia Gemini do dyspozytora głosowego.

    ``confirm_pending_action`` → :func:`confirm_pending`; każde inne → przez
    :func:`propose_or_execute` (które egzekwuje uprawnienia/gość/potwierdzenie).
    """
    if name == CONFIRM_TOOL:
        return confirm_pending(session)
    return propose_or_execute(session, name, dict(args or {}))


# =============================================================================
# WARSTWA TRANSPORTU (Twilio WS) + POŁĄCZENIE GEMINI
# =============================================================================


async def _send_text(send, token: str, *, last: bool) -> None:
    """Wysyła ramkę tekstu do ConversationRelay (Twilio zrobi TTS)."""
    await send(
        {
            "type": "websocket.send",
            "text": json.dumps({"type": "text", "token": token, "last": last}, ensure_ascii=False),
        }
    )


async def _recv_json(receive) -> dict | None:
    """Czyta jedną ramkę z gniazda. ``None`` = rozłączenie (koniec pętli)."""
    event = await receive()
    etype = event.get("type")
    if etype == "websocket.disconnect":
        return None
    if etype == "websocket.receive":
        text = event.get("text")
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Voice WS: nieparsowalna ramka JSON — pomijam.")
            return {}
    return {}


def _build_live_config(user):
    """Buduje ``LiveConnectConfig`` dla ConversationRelay.

    🔴 Modalność MUSI być ``AUDIO`` (nie ``TEXT``): ŻADEN dostępny model Gemini
    Live nie streamuje TEXT-out — ``response_modalities=['TEXT']`` zwraca błąd API
    1007 (zweryfikowane realnymi połączeniami). Zamiast tego model mówi AUDIO, a
    my włączamy ``output_audio_transcription`` i równoległą transkrypcję tekstową
    przekazujemy do ConversationRelay jako ramki ``text`` (Twilio robi z nich TTS).
    Wydzielone z :func:`_gemini_connect`, by test mógł sprawdzić config bez I/O.
    """
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=_system_instruction(user),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=d["name"],
                        description=d["description"],
                        parameters_json_schema=d["parameters"],
                    )
                    for d in build_function_declarations()
                ]
            )
        ],
    )


def _gemini_connect(user):  # pragma: no cover - I/O na żywo (mockowane w testach)
    """Otwiera sesję Gemini Live skonfigurowaną pod ConversationRelay.

    Zwraca async context manager. Wydzielone, by testy mogły to podmienić na
    atrapę bez realnego klucza/sieci; budowanie configu → :func:`_build_live_config`.
    """
    import os

    from django.conf import settings
    from google import genai

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "").strip())
    return client.aio.live.connect(
        model=settings.GEMINI_LIVE_MODEL, config=_build_live_config(user)
    )


def _system_instruction(user) -> str:
    """Instrukcja systemowa dla Gemini — voice-first zwięzłość + kontrakt potwierdzeń.

    Kanał głosowy: rozmówca SŁUCHA odpowiedzi, więc długie tury (recytacja pól,
    preambuły) są nie do zniesienia. Twarde reguły zwięzłości + format potwierdzenia
    „≤3 fakty + potwierdzasz?" zamiast odczytywania całego podglądu akcji. Kontrakt
    bezpieczeństwa (write tylko przez narzędzie → potwierdzenie → confirm) zachowany;
    RBAC i tak egzekwuje serwer w ``propose_or_execute``, niezależnie od promptu.
    """
    return (
        "Jesteś asystentem GŁOSOWYM Planera Maszyn Budowlanych. Rozmawiasz przez "
        "telefon — rozmówca SŁUCHA, nie czyta. Bądź maksymalnie zwięzły.\n"
        "ZASADY WYPOWIEDZI (bezwzględne):\n"
        "1. Maksymalnie 1-2 krótkie zdania na turę. Bez wstępów („Jasne”, „Już "
        "sprawdzam”), bez podsumowań, bez powtarzania pytania rozmówcy.\n"
        "2. Mów tylko to, o co pytano — NIE wyliczaj wszystkich pól. Przy statusie "
        "maszyny podaj sam status (i lokalizację, jeśli istotna); resztę tylko na prośbę.\n"
        "3. Daty mów naturalnie („ósmego lipca”), nie czytaj formatu ISO ani surowych danych.\n"
        "AKCJE ZAPISUJĄCE (rezerwacja, anulowanie, serwis…):\n"
        "4. Wykonuj je WYŁĄCZNIE przez właściwe narzędzie. Po jego wywołaniu zadaj JEDNO "
        "krótkie pytanie potwierdzające z najwyżej trzema kluczowymi faktami: „Rezerwuję "
        "KOP-001 na jutro dla Kowalskiego, potwierdzasz?”. NIE odczytuj wszystkich pól "
        "podglądu, NIE wymieniaj adresu ani notatek, chyba że rozmówca dopyta.\n"
        f"5. Dopiero gdy rozmówca powie „tak”/„potwierdzam”, wywołaj narzędzie {CONFIRM_TOOL}. "
        "Po wykonaniu potwierdź jednym zdaniem („Gotowe, rezerwacja utworzona”).\n"
        "6. Odmowę uprawnień lub błąd przekaż jednym krótkim zdaniem, bez tłumaczenia się.\n"
        + build_user_perms_summary(user)
    )


async def _handle_prompt(gsession, session: VoiceCallSession, msg: dict, send) -> None:
    """Przekazuje wypowiedź usera do Gemini i streamuje odpowiedź z powrotem do Twilio."""
    from google.genai import types

    voice_prompt = msg.get("voicePrompt", "")
    # Transkrypt (audyt) trzyma SUROWĄ wypowiedź — chcemy wiedzieć co user naprawdę
    # powiedział. Do Gemini idzie wersja sanityzowana i opakowana w <user_input>
    # (defense-in-depth, spójnie ze ścieżką tekstową w ``chatbot.services``).
    # RBAC serwerowy w ``propose_or_execute`` i tak jest twardą warstwą autoryzacji,
    # ale sanityzacja ogranicza prompt-leak i wzorce wstrzyknięcia w mowie.
    session.add_turn("user", voice_prompt)
    prompt_for_model = wrap_user_input(sanitize_user_input(voice_prompt))
    await gsession.send_client_content(
        turns={"role": "user", "parts": [{"text": prompt_for_model}]}, turn_complete=True
    )

    async for gmsg in gsession.receive():
        tool_call = getattr(gmsg, "tool_call", None)
        if tool_call and getattr(tool_call, "function_calls", None):
            responses = []
            for fc in tool_call.function_calls:
                result = await sync_to_async(dispatch_tool_call, thread_sensitive=True)(
                    session, fc.name, dict(fc.args or {})
                )
                session.add_turn("tool", result)
                responses.append(
                    types.FunctionResponse(id=fc.id, name=fc.name, response={"result": result})
                )
            await gsession.send_tool_response(function_responses=responses)
            continue

        server_content = getattr(gmsg, "server_content", None)
        if server_content and getattr(server_content, "interrupted", False):
            # Barge-in po stronie Gemini (różny od ramki ``interrupt`` z Twilio):
            # rozmówca przerwał — kończymy turę bez ramki ``last``.
            return

        # Model gada AUDIO; tekst do ConversationRelay bierzemy z transkrypcji
        # wyjścia (``output_transcription``) — ``gmsg.text`` przy modalności AUDIO
        # jest puste. Transkrypt jest strumieniowany przyrostowo.
        ot = getattr(server_content, "output_transcription", None) if server_content else None
        text = getattr(ot, "text", None) if ot else None
        if text:
            session.add_turn("assistant", text)
            await _send_text(send, text, last=False)

        if server_content and getattr(server_content, "turn_complete", False):
            await _send_text(send, "", last=True)
            return


async def run_voice_socket(scope, receive, send) -> None:
    """Pętla WS: akceptacja → setup/tożsamość → Gemini Live ↔ Twilio (tury)."""
    # Handshake ASGI WebSocket.
    event = await receive()
    if event.get("type") == "websocket.connect":
        await send({"type": "websocket.accept"})

    setup = await _recv_json(receive)
    if setup is None:
        return
    if setup.get("type") != "setup":
        logger.warning("Voice WS: pierwsza ramka to nie 'setup' (%s) — zamykam.", setup.get("type"))
        await send({"type": "websocket.close"})
        return

    user = await sync_to_async(resolve_caller, thread_sensitive=True)(setup)
    call_sid = setup.get("callSid") or setup.get("CallSid") or ""
    session = VoiceCallSession(call_sid=call_sid, user=user)
    logger.info("Voice WS setup: call_sid=%s user=%s", call_sid, getattr(user, "pk", "guest"))

    # Budowa configu Gemini uderza do DB (build_user_perms_summary → has_perm),
    # więc MUSI iść przez sync_to_async — inaczej dla zalogowanego NIE-superusera
    # (kierownik/magazynier/montażysta) leci ``SynchronousOnlyOperation`` i połączenie
    # pada tuż po PIN. (Admin=superuser omija DB, więc bug nie ujawniał się na demo.)
    gemini_cm = await sync_to_async(_gemini_connect, thread_sensitive=True)(user)
    async with gemini_cm as gsession:
        while True:
            msg = await _recv_json(receive)
            if msg is None:
                break
            mtype = msg.get("type")
            if mtype == "prompt":
                await _handle_prompt(gsession, session, msg, send)
            elif mtype == "interrupt" and session.has_pending():
                # Barge-in z Twilio: w modelu turowym tura Gemini już jest
                # zamknięta; czyścimy wiszącą akcję, by „tak” po przerwaniu nie
                # potwierdziło czegoś nieaktualnego.
                session.cancel()
            # 'setup'/inne ramki ignorujemy.
    logger.info("Voice WS zakończone: call_sid=%s", call_sid)
