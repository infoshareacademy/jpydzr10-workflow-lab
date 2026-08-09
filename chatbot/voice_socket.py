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

import asyncio
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

# Rozmowa operacyjna (ustalenie maszyny, terminu, potwierdzenie) — oczekujemy
# powtarzalnych decyzji o wywołaniu narzędzia, nie wariantowości językowej.
TEMPERATURE = 0.2

# Awaria po stronie modelu/sieci w trakcie tury. Dzwoniący trzyma słuchawkę przy
# uchu, więc MUSI usłyszeć cokolwiek — milczący socket jest nieodróżnialny od
# zepsutego systemu i kończy się rozłączeniem przez rozmówcę.
TURN_ERROR_MESSAGE = "Przepraszam, nie dosłyszałem. Możesz powtórzyć?"
FATAL_ERROR_MESSAGE = (
    "Przepraszam, straciłem połączenie z systemem. Zadzwoń proszę jeszcze raz za chwilę."
)
CONNECT_ERROR_MESSAGE = (
    "Przepraszam, system jest chwilowo niedostępny. Zadzwoń proszę jeszcze raz za chwilę."
)
# Po tylu nieudanych turach z rzędu przestajemy udawać, że rozmowa trwa: kolejne
# próby na zerwanej sesji i tak padną, a rozmówca w kółko słyszy „powtórz”.
MAX_TURN_FAILURES = 2

# Model nie zawsze domyka turę ``turn_complete``. Zaobserwowane na żywym połączeniu
# (rozmowa CA189c74…): po odesłaniu wyniku narzędzia przyszła wypowiedź modelu i
# ``generation_complete``, ale ``turn_complete`` NIE przyszedł już nigdy. Pętla tury
# czekała na niego w nieskończoność, więc most przestał czytać ramki z Twilio —
# rozmówca mówił do mikrofonu, którego nikt nie słuchał, i słyszał ciszę aż do
# rozłączenia. Stąd DWA niezależne wyjścia awaryjne poniżej.
#
# ``generation_complete`` = model skończył mówić. Turę domykamy WTEDY, nie czekając na
# ``turn_complete``: rozmówca słyszy wtedy koniec zdania i od razu może mówić. Czekanie
# na spóźniony sygnał (2,4 s w zmierzonej turze, a bywa że nie przychodzi wcale) jest w
# słuchawce nieodróżnialne od zawieszenia — rozmówca zaczyna powtarzać pytanie.
# To okno służy już tylko złapaniu narzędzia wywołanego TUŻ po wypowiedzi; TTS jest
# domknięty wcześniej, więc rozmowy nie blokuje.
POST_GENERATION_GRACE_SECONDS = 0.8
# Siatka na wszystko inne: model milczy, choć nie zapowiedział końca generowania.
# Wartość hojna — to bezpiecznik na patologię, nie element normalnego rytmu rozmowy.
TURN_IDLE_TIMEOUT_SECONDS = 15.0


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
    "find_available_machines": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "Data od (ISO YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "Data do (ISO YYYY-MM-DD)"},
            "machine_type": {
                "type": "string",
                "nullable": True,
                "description": "Opcjonalny typ maszyny (np. minikoparka, koparka, agregat)",
            },
        },
        "required": ["start_date", "end_date"],
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
        # Rozmowa jest zadaniowa, nie twórcza: przy domyślnej temperaturze model
        # bywał "kreatywny" zamiast sięgnąć po narzędzie — potrafił orzec „nie mogę
        # zarezerwować tego terminu" bez ani jednego wywołania, mimo że maszyna była
        # wolna. Niska wartość stabilizuje wybór narzędzi i trzymanie się instrukcji.
        temperature=TEMPERATURE,
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
        "Jesteś asystentką telefoniczną Planera Maszyn Budowlanych. Rozmówca SŁUCHA, "
        "nie czyta — mów krótko, jak człowiek przy telefonie.\n"
        "\n"
        "JAK MÓWISZ\n"
        "1. Jesteś KOBIETĄ i mówisz o sobie w rodzaju żeńskim: „sprawdziłam”, „zarezerwowałam”, "
        "„już szukam”, „nie znalazłam”. Formy męskie („sprawdziłem”) są błędem — rozmówca słyszy "
        "kobiecy głos i taka niezgodność od razu razi.\n"
        "2. Jedno-dwa krótkie zdania na turę. Bez wstępów („Jasne”, „Już sprawdzam”), bez "
        "podsumowań, bez powtarzania pytania rozmówcy.\n"
        "3. Zadawaj JEDNO pytanie naraz i czekaj na odpowiedź. Rozmowa idzie krok po kroku — "
        "nigdy nie wypytuj o kilka rzeczy w jednym zdaniu.\n"
        "4. Daty mów naturalnie („dziewiątego sierpnia”), nie czytaj formatu z cyfr i myślników.\n"
        "5. Nazwę maszyny wymawiaj DOKŁADNIE tak, jak brzmi w systemie. Liczba w nazwie jest jej "
        "częścią, a nie kolejnością: „Minikoparka 2” to „minikoparka dwa” — nigdy „druga "
        "minikoparka”, „minikoparka numer dwa” ani „minikoparka II”. Tak samo przy wyliczaniu "
        "kilku maszyn: „minikoparka dwa i minikoparka trzy”. Ta sama zasada dla każdego typu "
        "(koparka, podnośnik nożycowy, agregat prądotwórczy).\n"
        "6. Dopasowujesz się do TONU rozmówcy. Gdy zagaja żartobliwie albo po koleżeńsku "
        "(„cześć wariatko”, „no cześć wariacie”, „siema”, „co tam słychać”) — odpowiedz w tym "
        "samym stylu, ciepło i z uśmiechem w głosie, odbijając jego zwrot: „No cześć, wariacie! "
        "W czym mogę pomóc?”. Rób to RAZ, przy powitaniu albo gdy rozmówca sam znów tak zagada; "
        "potem wracasz do normalnego, rzeczowego tonu. Nie wtrącaj takich zwrotów do każdego "
        "zdania i nie zaczynaj tak sama z siebie, gdy rozmówca mówi oficjalnie — wtedy jesteś "
        "uprzejma i konkretna.\n"
        "\n"
        "CZEGO NIGDY NIE ROBISZ\n"
        "7. Nie zmyślasz. Nie znasz żadnego faktu o maszynach, terminach ani rezerwacjach, "
        "dopóki nie zapytasz o niego narzędzia. NIGDY nie mów, że coś jest zajęte, wolne, "
        "niemożliwe albo że wystąpił błąd, jeśli nie masz tego z narzędzia.\n"
        "8. Nie obiecujesz rzeczy spoza systemu: nie ma operatora, konsultanta, oddzwaniania "
        "ani przełączania rozmowy. Możesz tylko to, co dają narzędzia. Gdy czegoś nie potrafisz "
        "— powiedz wprost, że tego nie obsługujesz, i zaproponuj co możesz zrobić.\n"
        "9. Nie wymyślasz identyfikatorów maszyn („MINI-001” to błąd). Gdy rozmówca mówi o "
        "konkretnej maszynie, przekaż narzędziu DOKŁADNIE jego słowa („koparka dwa”, "
        "„Minikoparka 1”, „M-0005”) — narzędzia rozumieją nazwy i liczebniki wypowiadane "
        "słownie. Gdy pada tylko typ („jakaś minikoparka”, „potrzebuję agregatu”) albo pytanie "
        "o wolne maszyny — użyj find_available_machines. Rezerwuj wyłącznie identyfikatorem, "
        "który zwróciło narzędzie.\n"
        "10. Gdy pasuje kilka maszyn — podaj dwie po nazwie i spytaj, którą wybrać.\n"
        "\n"
        "REZERWACJA — KROK PO KROKU\n"
        "11. Do rezerwacji potrzebujesz sześciu rzeczy: maszyna, data od, data do, osoba "
        "rezerwująca, osoba odpowiedzialna, adres dostawy. Zbieraj je POJEDYNCZO, w tej "
        "kolejności, jednym krótkim pytaniem („Na kiedy?”, „Dla kogo?”, „Kto odpowiedzialny?”, "
        "„Gdzie dostarczyć?”). Po każdej odpowiedzi pytaj o NASTĘPNĄ brakującą rzecz.\n"
        "12. To, co rozmówca podał wcześniej w rozmowie, jest już zebrane — nie pytaj o to "
        "drugi raz. Nie streszczaj po drodze zebranych pól.\n"
        "13. KOLEJNA MASZYNA NA TYCH SAMYCH WARUNKACH. Gdy po zrobionej rezerwacji rozmówca "
        "prosi o następną maszynę „z tymi samymi danymi”, „tak samo jak poprzednio”, „na te same "
        "dni” — masz komplet z poprzedniej rezerwacji w tej rozmowie (daty, osoba rezerwująca, "
        "osoba odpowiedzialna, adres). PRZEPISZ je bez zmian i NIE pytaj ponownie o żadne z nich. "
        "Brakuje tylko maszyny: gdy rozmówca ją wskazał — od razu zadaj pytanie potwierdzające; "
        "gdy podał sam typ — najpierw sprawdź dostępność narzędziem na TYCH SAMYCH datach. "
        "Dopytuj wyłącznie o to, co rozmówca sam każe zmienić.\n"
        "14. Narzędzie rezerwacji wołaj DOPIERO gdy masz wszystkie sześć. Potem zadaj jedno "
        "krótkie pytanie potwierdzające z maksymalnie trzema faktami: „Rezerwuję Minikoparkę 1 "
        "od jutra na trzy dni dla Kowalskiego, potwierdzasz?”. Adresu ani reszty pól nie "
        f"odczytujesz. Gdy rozmówca potwierdzi — wywołaj {CONFIRM_TOOL} i powiedz jednym "
        "zdaniem, że gotowe.\n"
        "15. Gdy narzędzie zwróci błąd — powiedz krótko, czego się nie da, i zaproponuj "
        "konkretne wyjście (inny termin albo inna maszyna). Bez tłumaczeń technicznych.\n"
        "16. Gdy rozmówca prosi o coś spoza swoich uprawnień (lista niżej) — odmów od razu, "
        "jednym zdaniem, wskazując właściwą rolę („Nie masz uprawnień do rezerwacji, zgłoś to "
        "magazynierowi”). Nie zbieraj wtedy żadnych danych. Odczyt — statusy, dostępność, "
        "historia — jest dozwolony dla każdego.\n"
        "\n" + build_user_perms_summary(user)
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
    # Transkrypt trafia też do logu: po rozmowie telefonicznej NIE ZOSTAJE nic innego,
    # z czego dałoby się odtworzyć, co poszło nie tak (nagrania nie robimy). Bez tego
    # diagnoza „bot się zaciął" opiera się wyłącznie na pamięci rozmówcy.
    logger.info("Voice ◀ rozmówca [%s]: %s", session.call_sid, voice_prompt)
    prompt_for_model = wrap_user_input(sanitize_user_input(voice_prompt))
    await gsession.send_client_content(
        turns={"role": "user", "parts": [{"text": prompt_for_model}]}, turn_complete=True
    )

    # Iterujemy JAWNIE (zamiast ``async for``), bo każde oczekiwanie na ramkę musi
    # mieć limit czasu — patrz komentarz przy ``POST_GENERATION_GRACE_SECONDS``.
    stream = gsession.receive().__aiter__()
    generation_done = False  # model zapowiedział koniec generowania
    saw_output = False  # w TEJ turze przyszła już treść albo wywołanie narzędzia
    closed = False  # ramka ``last`` poszła — TTS domknięty, rozmówca ma głos
    spoken: list[str] = []  # całość wypowiedzi bota w tej turze (do logu)

    async def _close_turn() -> None:
        """Domyka turę u Twilio dokładnie raz i zapisuje wypowiedź do logu."""
        nonlocal closed
        if closed:
            return
        closed = True
        await _send_text(send, "", last=True)
        if spoken:
            logger.info("Voice ▶ asystent [%s]: %s", session.call_sid, "".join(spoken))

    while True:
        timeout = POST_GENERATION_GRACE_SECONDS if generation_done else TURN_IDLE_TIMEOUT_SECONDS
        try:
            gmsg = await asyncio.wait_for(anext(stream), timeout)
        except StopAsyncIteration:
            # Strumień tury zamknięty bez ``turn_complete`` — i tak domykamy poniżej,
            # żeby Twilio wypowiedziało bufor i wróciło do słuchania.
            break
        except TimeoutError:
            logger.warning(
                "Voice WS: model nie domknął tury (call_sid=%s, po generowaniu=%s) — "
                "domykam po stronie mostu.",
                session.call_sid,
                generation_done,
            )
            break

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
            # Po wyniku narzędzia model generuje odpowiedź od nowa — poprzednia
            # zapowiedź końca generowania jest już nieaktualna.
            generation_done = False
            saw_output = True
            continue

        if closed:
            # Turę już domknęliśmy (model zapowiedział koniec mówienia), a to nie było
            # wywołanie narzędzia — nie ma na co dłużej czekać, oddajemy głos rozmówcy.
            return

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
            spoken.append(text)
            await _send_text(send, text, last=False)
            saw_output = True

        if server_content and getattr(server_content, "turn_complete", False):
            # ``saw_output`` chroni przed domknięciem tury ramką zaległą po turze
            # poprzedniej (możliwą, gdy tamtą zamknął nasz timeout, a model dosłał
            # ``turn_complete`` już po fakcie) — inaczej ucięlibyśmy odpowiedź,
            # zanim model zdąży cokolwiek powiedzieć.
            if saw_output:
                await _close_turn()
                return
            continue

        if server_content and getattr(server_content, "generation_complete", False):
            # Model skończył mówić — oddajemy głos OD RAZU. Zostajemy jeszcze na krótkie
            # okno (patrz stała), bo zaraz po wypowiedzi może paść wywołanie narzędzia.
            generation_done = True
            await _close_turn()

    await _close_turn()


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
    try:
        gemini_cm = await sync_to_async(_gemini_connect, thread_sensitive=True)(user)
    except Exception:
        # Szeroki wyjątek celowo: cokolwiek zawiedzie po drodze (klucz, limit, sieć,
        # niedostępny model), rozmówca ma usłyszeć zdanie zamiast ciszy w słuchawce.
        logger.exception("Voice WS: nie udało się otworzyć sesji modelu (call_sid=%s).", call_sid)
        await _send_text(send, CONNECT_ERROR_MESSAGE, last=True)
        await send({"type": "websocket.close"})
        return

    failures = 0
    async with gemini_cm as gsession:
        while True:
            msg = await _recv_json(receive)
            if msg is None:
                break
            mtype = msg.get("type")
            if mtype == "prompt":
                try:
                    await _handle_prompt(gsession, session, msg, send)
                except Exception:
                    # Jw. — pojedyncza tura może paść z wielu powodów (zerwane
                    # gniazdo do modelu, timeout, błąd narzędzia). Rozmowa jest
                    # kanałem czasu rzeczywistego: lepiej poprosić o powtórzenie
                    # niż zostawić dzwoniącego w ciszy do samego rozłączenia.
                    failures += 1
                    logger.exception(
                        "Voice WS: tura nie powiodła się (call_sid=%s, z rzędu=%s).",
                        call_sid,
                        failures,
                    )
                    # Wisząca akcja pochodzi z przerwanej tury — po błędzie „tak”
                    # nie może potwierdzić czegoś, czego rozmówca nie usłyszał.
                    session.cancel()
                    if failures >= MAX_TURN_FAILURES:
                        await _send_text(send, FATAL_ERROR_MESSAGE, last=True)
                        break
                    await _send_text(send, TURN_ERROR_MESSAGE, last=True)
                else:
                    failures = 0
            elif mtype == "interrupt" and session.has_pending():
                # Barge-in z Twilio: w modelu turowym tura Gemini już jest
                # zamknięta; czyścimy wiszącą akcję, by „tak” po przerwaniu nie
                # potwierdziło czegoś nieaktualnego.
                session.cancel()
            # 'setup'/inne ramki ignorujemy.
    logger.info("Voice WS zakończone: call_sid=%s", call_sid)
