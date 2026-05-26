"""Narzędzia dla agenta Pydantic AI — READ + WRITE z confirmation step.

Dwie kategorie narzędzi:

1. **READ tools** (4) — czytają dane bez efektów ubocznych:
   :func:`get_machine_status`, :func:`check_availability`,
   :func:`get_inspections_due`, :func:`get_service_costs`.

2. **WRITE tools** (5, Wave 14-C) — proponują zmianę i zwracają JSON
   z ``confirmation_required=true``. **NIE wykonują akcji od razu** —
   warstwa serwisowa (:mod:`chatbot.services`) zapisuje
   ``Conversation.pending_action`` i czeka aż user odpisze
   ``"tak"``/``"potwierdzam"`` w następnej turze rozmowy.
   Lista narzędzi: :func:`propose_create_reservation`,
   :func:`propose_cancel_reservation`, :func:`propose_change_operator`,
   :func:`propose_swap_machine`, :func:`propose_set_machine_to_service`.

   Dispatcher :func:`execute_confirmed_action` wykonuje akcję dopiero gdy
   user potwierdzi — odbywa ponowną weryfikację uprawnień (defense-in-depth)
   i loguje audit trail.

Każde READ narzędzie zwraca model Pydantic — dzięki temu jego JSON
serializacja jest deterministyczna i agent dostaje stabilną odpowiedź.
Każde WRITE narzędzie zwraca ``str`` (JSON dump) z ustaloną strukturą
``{"proposed_action": ..., "params": ..., "preview": ...,
"confirmation_required": true}`` — services layer parsuje to żeby
wyciągnąć ``pending_action`` do persist.

Importy modeli Django są **lazy** (wewnątrz funkcji) z dwóch powodów:

1. unikamy circular imports gdy ``agent.py`` importuje ten moduł na poziomie
   modułu a Django jeszcze nie skończył load app registry;
2. pozwala testować osobno każdą funkcję bez uruchamiania całego stacku.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("chatbot")

# =============================================================================
# OUTPUT SCHEMAS — Pydantic models
# =============================================================================


class MachineStatusResult(BaseModel):
    """Wynik :func:`get_machine_status`."""

    found: bool = Field(description="Czy maszyna o podanym UID istnieje.")
    uid: str
    name: str | None = None
    machine_type: str | None = None
    status: str | None = None
    location: str | None = None
    inspection_date: str | None = None
    inspection_status: str | None = None
    inspection_days_left: int | None = None


class ConflictItem(BaseModel):
    """Pojedynczy konflikt rezerwacji zwracany przez :func:`check_availability`."""

    start: str
    end: str
    person: str
    status: str


class AvailabilityResult(BaseModel):
    """Wynik :func:`check_availability`."""

    machine_uid: str
    machine_found: bool
    start_date: str
    end_date: str
    available: bool
    conflict_count: int
    conflicts: list[ConflictItem]
    error: str | None = None


class InspectionMachineItem(BaseModel):
    """Maszyna pojawiająca się na liście przeglądów."""

    uid: str
    name: str
    inspection_date: str
    days_left: int
    status: str  # "overdue" | "upcoming"


class InspectionDueResult(BaseModel):
    """Wynik :func:`get_inspections_due`."""

    days_ahead: int
    today: str
    overdue_count: int
    upcoming_count: int
    machines: list[InspectionMachineItem]


class ServiceCostResult(BaseModel):
    """Wynik :func:`get_service_costs`."""

    period_start: str
    period_end: str
    machine_type: str | None
    total_cost: float
    record_count: int
    by_type: dict[str, float]


# =============================================================================
# TOOL IMPLEMENTATIONS — wszystkie READ-ONLY
# =============================================================================

# Limit pozycji na liście przeglądów żeby kontekst promptu nie urósł zbyt
# duży (oszczędność tokenów + szybsza odpowiedź agenta).
INSPECTIONS_LIST_LIMIT = 20


def get_machine_status(uid: str) -> MachineStatusResult:
    """Zwraca aktualny status maszyny po jej UID (np. ``KOP-001``).

    Returns:
        :class:`MachineStatusResult` z ``found=False`` gdy maszyna nie istnieje
        (zamiast wyjątku — łatwiej dla agenta złożyć odpowiedź naturalnym
        językiem niż obsługiwać exception).
    """
    from machines.models import Machine

    try:
        m = Machine.objects.get(uid=uid)
    except Machine.DoesNotExist:
        return MachineStatusResult(found=False, uid=uid)

    return MachineStatusResult(
        found=True,
        uid=m.uid,
        name=m.name,
        machine_type=m.get_machine_type_display(),
        status=m.status,
        location=m.location,
        inspection_date=m.inspection_date.isoformat() if m.inspection_date else None,
        inspection_status=m.inspection_status,
        inspection_days_left=m.inspection_days_left,
    )


def check_availability(uid: str, start_date: str, end_date: str) -> AvailabilityResult:
    """Sprawdza dostępność maszyny w okresie ``[start_date, end_date]``.

    Args:
        uid: UID maszyny.
        start_date: ISO YYYY-MM-DD.
        end_date: ISO YYYY-MM-DD.

    Returns:
        :class:`AvailabilityResult` zawierający flag ``available`` plus listę
        do trzech konfliktujących rezerwacji. Gdy maszyna nie istnieje lub
        daty są nieprawidłowe — zwraca ``available=False`` + ``error``.
    """
    from machines.models import Machine
    from reservations.services import get_conflicting_reservations, has_conflict

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        return AvailabilityResult(
            machine_uid=uid,
            machine_found=False,
            start_date=start_date,
            end_date=end_date,
            available=False,
            conflict_count=0,
            conflicts=[],
            error=f"Nieprawidłowy format daty: {exc}",
        )

    if end < start:
        return AvailabilityResult(
            machine_uid=uid,
            machine_found=False,
            start_date=start_date,
            end_date=end_date,
            available=False,
            conflict_count=0,
            conflicts=[],
            error="Data końca musi być >= data początku.",
        )

    try:
        machine = Machine.objects.get(uid=uid)
    except Machine.DoesNotExist:
        return AvailabilityResult(
            machine_uid=uid,
            machine_found=False,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            available=False,
            conflict_count=0,
            conflicts=[],
            error=f"Nie znaleziono maszyny o UID {uid}.",
        )

    conflicts_qs = get_conflicting_reservations(machine_id=machine.id, start=start, end=end)
    available = not has_conflict(machine_id=machine.id, start=start, end=end)

    return AvailabilityResult(
        machine_uid=uid,
        machine_found=True,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        available=available,
        conflict_count=len(conflicts_qs),
        conflicts=[
            ConflictItem(
                start=r.start_date.isoformat(),
                end=r.end_date.isoformat(),
                person=r.person,
                status=r.status,
            )
            for r in conflicts_qs[:3]
        ],
    )


def get_inspections_due(days_ahead: int = 14) -> InspectionDueResult:
    """Lista maszyn z przeglądem w najbliższych ``days_ahead`` dniach + przeterminowane.

    Args:
        days_ahead: Horyzont czasowy w dniach (domyślnie 14 — zgodnie z
            ``machines.models.INSPECTION_WARNING_DAYS``).

    Returns:
        :class:`InspectionDueResult` z licznikami + listą max
        :data:`INSPECTIONS_LIST_LIMIT` pozycji (najpierw overdue, potem
        upcoming, posortowane po dacie rosnąco).
    """
    from machines.models import Machine

    days_ahead = max(1, min(days_ahead, 365))  # clamp — zapobiega absurdalnym horyzontom
    today = date.today()
    horizon = today + timedelta(days=days_ahead)

    overdue_qs = Machine.objects.filter(inspection_date__lt=today).order_by("inspection_date")
    upcoming_qs = Machine.objects.filter(
        inspection_date__gte=today, inspection_date__lte=horizon
    ).order_by("inspection_date")

    overdue_count = overdue_qs.count()
    upcoming_count = upcoming_qs.count()

    items: list[InspectionMachineItem] = []
    for m in list(overdue_qs) + list(upcoming_qs):
        days_left = (m.inspection_date - today).days
        items.append(
            InspectionMachineItem(
                uid=m.uid,
                name=m.name,
                inspection_date=m.inspection_date.isoformat(),
                days_left=days_left,
                status="overdue" if days_left < 0 else "upcoming",
            )
        )
        if len(items) >= INSPECTIONS_LIST_LIMIT:
            break

    return InspectionDueResult(
        days_ahead=days_ahead,
        today=today.isoformat(),
        overdue_count=overdue_count,
        upcoming_count=upcoming_count,
        machines=items,
    )


def get_service_costs(machine_type: str | None = None, days: int = 90) -> ServiceCostResult:
    """Sumaryczne koszty serwisowe w ostatnich ``days`` dniach + breakdown per typ wpisu.

    Args:
        machine_type: Opcjonalnie zawęża do jednego typu maszyny
            (np. ``"koparka"``). Wartość musi pasować do
            :attr:`machines.Machine.Type.value`.
        days: Okno czasowe w dniach (domyślnie 90 = ~3 miesiące).

    Returns:
        :class:`ServiceCostResult` z sumą + słownikiem
        ``{display_name_typu_wpisu: koszt}``.
    """
    from service.models import ServiceRecord

    days = max(1, min(days, 3650))  # clamp 1d..10y
    end = date.today()
    start = end - timedelta(days=days)

    qs = ServiceRecord.objects.filter(performed_date__gte=start, performed_date__lte=end)
    if machine_type:
        qs = qs.filter(machine__machine_type=machine_type)

    records = list(qs.select_related("machine"))
    total = sum((r.cost for r in records), Decimal("0"))

    by_type: dict[str, float] = {}
    for r in records:
        key = r.get_record_type_display()
        by_type[key] = round(by_type.get(key, 0.0) + float(r.cost), 2)

    return ServiceCostResult(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        machine_type=machine_type,
        total_cost=float(total),
        record_count=len(records),
        by_type=by_type,
    )


# =============================================================================
# WRITE TOOLS — Wave 14-C: confirmation-step pattern
# =============================================================================
#
# Każde "propose_*" narzędzie:
#   1. Sprawdza ``user.has_perm(...)`` — wczesny exit jeśli brak uprawnień.
#   2. Waliduje parametry (daty, istnienie obiektów, format).
#   3. **NIE** mutuje bazy — zwraca JSON z opisem proponowanej akcji.
#
# Services layer (:func:`chatbot.services.ask_chatbot`) parsuje wynik, zapisuje
# ``Conversation.pending_action`` i renderuje preview. User w następnej turze
# odpisuje "tak"/"potwierdzam" → :func:`execute_confirmed_action` finalnie
# wykonuje akcję (z **ponowną** weryfikacją uprawnień, defense-in-depth).
#
# Wzorzec inspirowany pydantic-ai 1.97 ``DeferredToolRequests`` ale prostszy:
# pozostawia 100% kontroli w warstwie services bez sprzęgania z Pydantic AI
# internals (łatwiej testować, łatwiej audytować, łatwiej swap'ować model).
# =============================================================================


# Mapowanie action → tuple wymaganych Django permissions.
#
# Wave 14-H Bundle H-4: swap_machine wymaga BOTH change_reservation AND
# add_reservation, bo:
#   1. zamyka starą rezerwację (change_reservation),
#   2. tworzy NOWĄ rezerwację na maszynę zastępczą (add_reservation).
# Stara konfiguracja (tylko change) pozwalała user'om z change_reservation
# (ale BEZ add) tworzyć nowe rezerwacje przez swap_machine — privilege
# escalation gap.
#
# Centralna definicja używana zarówno przez "propose_*" jak i
# :func:`execute_confirmed_action` (defense-in-depth — TWO checks).
WRITE_ACTION_PERMS: dict[str, tuple[str, ...]] = {
    "create_reservation": ("reservations.add_reservation",),
    "cancel_reservation": ("reservations.change_reservation",),
    "change_operator": ("reservations.change_reservation",),
    "swap_machine": (
        "reservations.change_reservation",
        "reservations.add_reservation",
    ),
    "set_machine_to_service": ("machines.change_machine",),
}


# Pydantic Input Schemas — każdy write tool przyjmuje strict schema żeby
# Pydantic AI 1.97 walidował argumenty (typy + Field descriptions w prompt).
#
# Wave 14-H Bundle H-1: pełne ograniczenia (max_length + regex pattern)
# chronią przed DoS-em (bezsensowne 100 MB stringi w argumentach LLM-a) oraz
# wymuszają format zgodny z biznesowymi UID-ami. Pydantic ValidationError
# będzie zwrócony zanim narzędzie cokolwiek zrobi.

# Regexy biznesowe — synchronizowane z core/validators.py.
_MACHINE_UID_PATTERN = r"^[A-Z]+-\d+$"
_PROJECT_NUMBER_PATTERN = r"^BUD-\d{4}-\d+$"
_ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Limity długości — uzasadnione biznesowo (lepiej niż "magic number"):
# - UID maszyny: KOP-001..KOP-9999999999 (15 wystarczy, dajemy 20 bufora).
# - person/responsible_person: typowe "Imię Nazwisko" ~50 znaków, max 100.
# - address: pełny adres dostawy "ul. Bardzo długa 123/45, 00-000 Miasto",
#   bezpieczna granica 300.
# - notes/note/reason: free-text, 500 znaków wystarcza (jeśli user chce
#   napisać esej — niech użyje formularza w UI z większym polem).
_MACHINE_UID_MAX = 20
_PROJECT_NUMBER_MAX = 20
_PERSON_NAME_MAX = 100
_ADDRESS_MAX = 300
_NOTES_MAX = 500


class CreateReservationParams(BaseModel):
    """Parametry :func:`propose_create_reservation`."""

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny (np. KOP-001)",
    )
    start_date: str = Field(
        pattern=_ISO_DATE_PATTERN,
        description="Data od (ISO YYYY-MM-DD)",
    )
    end_date: str = Field(
        pattern=_ISO_DATE_PATTERN,
        description="Data do (ISO YYYY-MM-DD)",
    )
    person: str = Field(
        max_length=_PERSON_NAME_MAX,
        description="Imię i nazwisko osoby rezerwującej",
    )
    site_project_number: str = Field(
        default="",
        max_length=_PROJECT_NUMBER_MAX,
        description="Numer budowy (BUD-RRRR-NNN), opcjonalnie",
    )
    address: str = Field(
        default="",
        max_length=_ADDRESS_MAX,
        description="Adres dostawy, opcjonalnie",
    )
    notes: str = Field(
        default="",
        max_length=_NOTES_MAX,
        description="Notatki, opcjonalnie",
    )
    # Wave 14-H Bundle M-1: responsible_person wymagany przez form,
    # przekazujemy też tu żeby chatbot tworzył kompletne rezerwacje.
    responsible_person: str = Field(
        default="",
        max_length=_PERSON_NAME_MAX,
        description="Osoba odpowiedzialna za rezerwację (kierownik budowy)",
    )


class CancelReservationParams(BaseModel):
    """Parametry :func:`propose_cancel_reservation`."""

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji do anulowania",
    )
    # Literal type → Pydantic enforce'uje że agent wpisze JEDNĄ z dozwolonych
    # wartości (zamiast wolnego stringa). Wartości synchronizowane z
    # Reservation.CancellationReason.choices.
    reason: Literal[
        "klient_zrezygnowal",
        "awaria",
        "zmiana_terminu",
        "brak_dostepnosci",
        "inne",
    ] = Field(
        description=(
            "Powód anulowania — jedno z: klient_zrezygnowal, awaria, "
            "zmiana_terminu, brak_dostepnosci, inne"
        ),
    )
    note: str = Field(
        default="",
        max_length=_NOTES_MAX,
        description="Opcjonalna notatka do powodu",
    )


class ChangeOperatorParams(BaseModel):
    """Parametry :func:`propose_change_operator`."""

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji",
    )
    new_person: str = Field(
        max_length=_PERSON_NAME_MAX,
        description="Nowe imię i nazwisko operatora",
    )


class SwapMachineParams(BaseModel):
    """Parametry :func:`propose_swap_machine`."""

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji do podmiany",
    )
    new_machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID nowej maszyny (np. KOP-002)",
    )
    reason: str = Field(
        default="",
        max_length=_NOTES_MAX,
        description="Powód wymiany, opcjonalnie",
    )


class SetMachineToServiceParams(BaseModel):
    """Parametry :func:`propose_set_machine_to_service`."""

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny do wysłania do serwisu",
    )


# Audit logger — dedicated channel dla write operations chatbota.
# Każda propozycja + każde wykonanie loguje się z user_id, action, params.
_audit_logger = logging.getLogger("chatbot.audit")


def _proposal(action: str, params: dict, preview: str) -> str:
    """Zwraca JSON proposal — stała struktura dla services parsera."""
    return json.dumps(
        {
            "proposed_action": action,
            "params": params,
            "preview": preview,
            "confirmation_required": True,
        },
        ensure_ascii=False,
    )


def _error_json(message: str) -> str:
    """Zwraca JSON z error — agent przekaże w PL do usera."""
    return json.dumps({"error": message}, ensure_ascii=False)


def _check_user_can(user, action: str) -> str | None:
    """Sprawdza authorization usera dla ``action``.

    Wave 14-H Bundle H-4: ``WRITE_ACTION_PERMS`` zawiera **tuple** —
    user musi mieć WSZYSTKIE wymienione permissions (np. swap_machine
    wymaga change_reservation + add_reservation, bo zamyka starą rez.
    i tworzy nową).

    Returns:
        ``None`` jeśli OK, inaczej JSON error string do zwrócenia z narzędzia.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return _error_json("Niezalogowany użytkownik nie może modyfikować danych.")
    if not getattr(user, "is_active", False):
        return _error_json("Konto użytkownika jest nieaktywne.")
    perms = WRITE_ACTION_PERMS.get(action)
    if not perms:
        return _error_json(f"Nieznana akcja: {action}.")
    missing = [p for p in perms if not user.has_perm(p)]
    if missing:
        missing_str = ", ".join(missing)
        return _error_json(f"Brak uprawnień ({missing_str}) do akcji '{action}'.")
    return None


def propose_create_reservation(params: CreateReservationParams, user) -> str:
    """Proponuje utworzenie rezerwacji — zwraca JSON, NIE mutuje DB.

    Validacja: format dat, daty nie w przeszłości, end >= start, istnienie
    maszyny, opcjonalnie istnienie budowy po project_number. Konflikt
    rezerwacji NIE jest sprawdzany na tym etapie — finalne sprawdzenie
    jest pod ``select_for_update`` w :func:`execute_confirmed_action`
    (race-safe approval).
    """
    from machines.models import Machine
    from reservations.models import ConstructionSite

    auth_err = _check_user_can(user, "create_reservation")
    if auth_err:
        return auth_err

    try:
        start = date.fromisoformat(params.start_date)
        end = date.fromisoformat(params.end_date)
    except ValueError:
        return _error_json(
            f"Nieprawidłowy format daty (wymagany ISO YYYY-MM-DD): "
            f"{params.start_date}, {params.end_date}."
        )
    if end < start:
        return _error_json("Data końca musi być >= data początku.")
    if end < date.today():
        return _error_json("Nie można proponować rezerwacji w przeszłości.")
    if not params.person or not params.person.strip():
        return _error_json("Pole 'osoba rezerwująca' nie może być puste.")

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    site_id: int | None = None
    site_label = ""
    if params.site_project_number:
        try:
            site = ConstructionSite.objects.get(project_number=params.site_project_number)
            site_id = site.pk
            site_label = f", budowa {site.project_number} ({site.name})"
        except ConstructionSite.DoesNotExist:
            return _error_json(f"Budowa o numerze '{params.site_project_number}' nie istnieje.")

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
        "site_id": site_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "person": params.person.strip(),
        "address": (params.address or "").strip(),
        "notes": params.notes or "",
        # Wave 14-H Bundle M-1: responsible_person enforce'owany w
        # reservations.services.create_reservation (jeśli pusty → ValidationError).
        "responsible_person": (params.responsible_person or "").strip(),
    }
    preview = (
        f"Utworzę rezerwację maszyny {machine.uid} ({machine.name}) "
        f"od {start.isoformat()} do {end.isoformat()} "
        f"dla osoby '{params.person.strip()}'{site_label}."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE create_reservation user=%s machine=%s start=%s end=%s",
        getattr(user, "pk", None),
        machine.uid,
        start,
        end,
    )
    return _proposal("create_reservation", payload, preview)


def propose_cancel_reservation(params: CancelReservationParams, user) -> str:
    """Proponuje anulowanie rezerwacji — zwraca JSON, NIE mutuje DB."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "cancel_reservation")
    if auth_err:
        return auth_err

    valid_reasons = {choice for choice, _label in Reservation.CancellationReason.choices}
    if params.reason not in valid_reasons:
        return _error_json(
            f"Nieznany powód anulowania '{params.reason}'. "
            f"Dozwolone: {', '.join(sorted(valid_reasons))}."
        )

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.status in {
        Reservation.Status.ANULOWANA,
        Reservation.Status.ZAKONCZONA,
    }:
        return _error_json(
            f"Rezerwacja #{reservation.pk} ma status '{reservation.get_status_display()}' "
            f"— nie można jej anulować."
        )

    payload = {
        "reservation_id": reservation.pk,
        "reason": params.reason,
        "note": params.note or "",
    }
    preview = (
        f"Anuluję rezerwację #{reservation.pk} maszyny {reservation.machine.uid} "
        f"({reservation.start_date} - {reservation.end_date}, "
        f"osoba '{reservation.person}'). Powód: {params.reason}."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE cancel_reservation user=%s reservation=%s reason=%s",
        getattr(user, "pk", None),
        reservation.pk,
        params.reason,
    )
    return _proposal("cancel_reservation", payload, preview)


def propose_change_operator(params: ChangeOperatorParams, user) -> str:
    """Proponuje zmianę osoby rezerwacji — zwraca JSON, NIE mutuje DB."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "change_operator")
    if auth_err:
        return auth_err

    new_person = (params.new_person or "").strip()
    if not new_person:
        return _error_json("Nowa osoba jest wymagana.")
    if len(new_person) < 3:
        return _error_json("Imię i nazwisko musi mieć co najmniej 3 znaki.")

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.is_closed:
        return _error_json(
            f"Rezerwacja #{reservation.pk} jest zamknięta "
            f"({reservation.get_status_display()}) — nie można zmienić operatora."
        )
    if new_person.casefold() == reservation.person.strip().casefold():
        return _error_json("Nowa osoba musi się różnić od obecnej.")

    payload = {
        "reservation_id": reservation.pk,
        "new_person": new_person,
    }
    preview = (
        f"Zmienię osobę rezerwacji #{reservation.pk} ({reservation.machine.uid}, "
        f"{reservation.start_date} - {reservation.end_date}) "
        f"z '{reservation.person}' na '{new_person}'."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE change_operator user=%s reservation=%s new_person=%s",
        getattr(user, "pk", None),
        reservation.pk,
        new_person,
    )
    return _proposal("change_operator", payload, preview)


def propose_swap_machine(params: SwapMachineParams, user) -> str:
    """Proponuje wymianę maszyny mid-reservation — zwraca JSON, NIE mutuje DB."""
    from machines.models import Machine
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "swap_machine")
    if auth_err:
        return auth_err

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.is_closed:
        return _error_json(
            f"Rezerwacja #{reservation.pk} jest zamknięta "
            f"({reservation.get_status_display()}) — nie można wymienić maszyny."
        )

    try:
        new_machine = Machine.objects.get(uid=params.new_machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna zastępcza o UID '{params.new_machine_uid}' nie istnieje.")

    if new_machine.pk == reservation.machine_id:
        return _error_json("Maszyna zastępcza musi się różnić od obecnej.")
    if new_machine.status == Machine.Status.WYCOFANA:
        return _error_json(
            f"Maszyna {new_machine.uid} jest wycofana z floty — nie może być zastępcą."
        )

    payload = {
        "reservation_id": reservation.pk,
        "new_machine_id": new_machine.pk,
        "new_machine_uid": new_machine.uid,
        "reason": (params.reason or "").strip(),
    }
    preview = (
        f"Wymienię maszynę rezerwacji #{reservation.pk}: "
        f"{reservation.machine.uid} → {new_machine.uid} ({new_machine.name}). "
        f"Stara rezerwacja zostanie zamknięta dzisiaj, nowa pokryje pozostały okres "
        f"do {reservation.end_date}."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE swap_machine user=%s reservation=%s old=%s new=%s",
        getattr(user, "pk", None),
        reservation.pk,
        reservation.machine.uid,
        new_machine.uid,
    )
    return _proposal("swap_machine", payload, preview)


def propose_set_machine_to_service(params: SetMachineToServiceParams, user) -> str:
    """Proponuje wysłanie maszyny do serwisu — zwraca JSON, NIE mutuje DB."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "set_machine_to_service")
    if auth_err:
        return auth_err

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    if machine.status == Machine.Status.W_SERWISIE:
        return _error_json(f"Maszyna {machine.uid} jest już w serwisie.")
    if machine.status == Machine.Status.NA_BUDOWIE:
        return _error_json(f"Maszyna {machine.uid} jest na budowie — najpierw zarejestruj zwrot.")
    if machine.status == Machine.Status.WYCOFANA:
        return _error_json(f"Maszyna {machine.uid} jest wycofana z floty.")

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
    }
    preview = (
        f"Wyślę maszynę {machine.uid} ({machine.name}) do serwisu. "
        f"Obecny status: {machine.get_status_display()} → W serwisie."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE set_machine_to_service user=%s machine=%s",
        getattr(user, "pk", None),
        machine.uid,
    )
    return _proposal("set_machine_to_service", payload, preview)


# =============================================================================
# EXECUTOR — finalne wykonanie po potwierdzeniu usera
# =============================================================================


def execute_confirmed_action(action: str, params: dict, user) -> str:
    """Wykonuje potwierdzoną akcję write — wywoływane PO confirmation usera.

    **Defense-in-depth**: ponowna weryfikacja uprawnień + flagi konta nawet
    jeśli sprawdzono je w :func:`propose_*`. User mógł stracić uprawnienia
    między proposal a confirmation; my-nie-ufaj-LLM.

    Returns:
        Polski string z opisem wyniku (sukces / błąd). Wracam string a nie
        JSON żeby agent mógł bezpośrednio "przekazać" go do usera bez
        dodatkowego parsowania.
    """
    from django.core.exceptions import ValidationError

    if not user or not getattr(user, "is_authenticated", False):
        return "Sesja wygasła — zaloguj się ponownie."
    if not getattr(user, "is_active", False):
        return "Konto użytkownika jest nieaktywne."
    perms = WRITE_ACTION_PERMS.get(action)
    if not perms:
        return f"Nieznana akcja: {action}."
    # Wave 14-H Bundle H-4: ALL permissions must hold (defense-in-depth +
    # privilege gap fix dla swap_machine).
    missing = [p for p in perms if not user.has_perm(p)]
    if missing:
        missing_str = ", ".join(missing)
        return f"Brak uprawnień ({missing_str}) do wykonania akcji '{action}'."

    _audit_logger.info(
        "CHATBOT EXECUTE %s user=%s params=%s",
        action,
        getattr(user, "pk", None),
        params,
    )

    try:
        if action == "create_reservation":
            return _execute_create_reservation(params)
        if action == "cancel_reservation":
            return _execute_cancel_reservation(params)
        if action == "change_operator":
            return _execute_change_operator(params, user)
        if action == "swap_machine":
            return _execute_swap_machine(params, user)
        if action == "set_machine_to_service":
            return _execute_set_machine_to_service(params)
    except ValidationError as exc:
        # Polski string z listą message'y (bez wycieku class name / tracebacka).
        messages = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        _audit_logger.warning(
            "CHATBOT EXECUTE %s validation_error user=%s msg=%s",
            action,
            getattr(user, "pk", None),
            messages,
        )
        return f"Nie udało się wykonać akcji: {messages}"
    except Exception:
        logger.exception(
            "Chatbot execute_confirmed_action exception user=%s action=%s",
            getattr(user, "pk", None),
            action,
        )
        return "Wystąpił nieoczekiwany błąd podczas wykonywania akcji."

    return f"Akcja '{action}' nie jest obsługiwana."


def _execute_create_reservation(params: dict) -> str:
    """Wykonuje create_reservation z params zarówno z text-parsed JSON
    (legacy, z ``machine_id`` PK) jak i z ToolCallPart args (Wave 14-H C-1,
    z ``machine_uid`` string)."""
    from machines.models import Machine
    from reservations.models import ConstructionSite
    from reservations.services import create_reservation

    # Resolve machine_id z machine_uid jeśli trzeba (Wave 14-H C-1 flow:
    # ToolCallPart args mają tylko machine_uid).
    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id is None and machine_uid:
        machine = Machine.objects.get(uid=machine_uid)
        machine_id = machine.pk
        machine_uid = machine.uid

    # Resolve site_id z site_project_number jeśli trzeba.
    site_id = params.get("site_id")
    site_project_number = params.get("site_project_number")
    if site_id is None and site_project_number:
        try:
            site = ConstructionSite.objects.get(project_number=site_project_number)
            site_id = site.pk
        except ConstructionSite.DoesNotExist:
            return f"Budowa o numerze '{site_project_number}' nie istnieje."

    reservation = create_reservation(
        machine_id=machine_id,
        site_id=site_id,
        start_date=date.fromisoformat(params["start_date"]),
        end_date=date.fromisoformat(params["end_date"]),
        person=params["person"],
        address=params.get("address", ""),
        notes=params.get("notes", ""),
        responsible_person=params.get("responsible_person", ""),
        # Wave 14-H Bundle M-1: chatbot — wymagamy address + responsible_person
        # bo flow chatbota nie ma "quick reserve" semantics jak QuickReserveView.
        require_full_fields=True,
    )
    return (
        f"Rezerwacja #{reservation.pk} utworzona: "
        f"{machine_uid} {params['start_date']} - {params['end_date']} "
        f"dla '{params['person']}'."
    )


def _execute_cancel_reservation(params: dict) -> str:
    from reservations.models import Reservation
    from reservations.services import cancel_reservation

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    cancel_reservation(
        reservation,
        reason=params["reason"],
        note=params.get("note", ""),
    )
    return f"Rezerwacja #{reservation.pk} anulowana (powód: {params['reason']})."


def _execute_change_operator(params: dict, user) -> str:
    from reservations.models import Reservation
    from reservations.services import change_operator

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    change_operator(reservation, new_person=params["new_person"], actor=user)
    return f"Operator rezerwacji #{reservation.pk} zmieniony na '{params['new_person']}'."


def _execute_swap_machine(params: dict, user) -> str:
    """Swap machine — resolves new_machine_id z new_machine_uid jeśli trzeba."""
    from machines.models import Machine
    from reservations.models import Reservation
    from reservations.services import swap_machine

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    new_machine_id = params.get("new_machine_id")
    new_machine_uid = params.get("new_machine_uid")
    if new_machine_id:
        new_machine = Machine.objects.get(pk=new_machine_id)
    else:
        new_machine = Machine.objects.get(uid=new_machine_uid)
    result = swap_machine(
        reservation,
        new_machine=new_machine,
        reason=params.get("reason", ""),
        actor=user,
    )
    return (
        f"Maszyna wymieniona: rezerwacja #{result['original_id']} zamknięta, "
        f"nowa rezerwacja #{result['new_id']} na maszynę {new_machine.uid}."
    )


def _execute_set_machine_to_service(params: dict) -> str:
    """Set machine to service — resolves machine_id z machine_uid jeśli trzeba."""
    from machines.models import Machine
    from machines.services import set_machine_to_service

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)
    set_machine_to_service(machine)
    return f"Maszyna {machine.uid} wysłana do serwisu."


# =============================================================================
# Pomocniczy registry — używany przez ``agent.py`` do rejestracji w Agent
# =============================================================================

ALL_TOOLS: dict[str, Any] = {
    "get_machine_status": get_machine_status,
    "check_availability": check_availability,
    "get_inspections_due": get_inspections_due,
    "get_service_costs": get_service_costs,
    # Wave 14-C write tools — return JSON proposal, do NOT mutate DB.
    "propose_create_reservation": propose_create_reservation,
    "propose_cancel_reservation": propose_cancel_reservation,
    "propose_change_operator": propose_change_operator,
    "propose_swap_machine": propose_swap_machine,
    "propose_set_machine_to_service": propose_set_machine_to_service,
}
