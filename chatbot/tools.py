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


class AvailableMachineItem(BaseModel):
    """Pojedyncza maszyna na liście dostępnych w danym okresie."""

    uid: str
    name: str
    machine_type: str
    location: str


class FindAvailableMachinesResult(BaseModel):
    """Wynik :func:`find_available_machines`."""

    start_date: str
    end_date: str
    machine_type: str | None = Field(
        default=None,
        description="Filtr typu jeśli podany (np. 'minikoparka'). None = wszystkie typy.",
    )
    total_found: int
    machines: list[AvailableMachineItem]
    truncated: bool = Field(
        default=False,
        description="True gdy lista została obcięta do limitu (zwykle 20).",
    )
    error: str | None = None


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
    total = sum((r.cost.amount for r in records), Decimal("0"))

    by_type: dict[str, float] = {}
    for r in records:
        key = r.get_record_type_display()
        by_type[key] = round(by_type.get(key, 0.0) + float(r.cost.amount), 2)

    return ServiceCostResult(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        machine_type=machine_type,
        total_cost=float(total),
        record_count=len(records),
        by_type=by_type,
    )


# Limit liczby maszyn zwracanych przez ``find_available_machines`` żeby
# kontekst promptu nie urósł zbyt mocno (oszczędność tokenów). Przy 20+
# wynikach lepiej żeby agent doradził użytkownikowi otwarcie strony
# ``/maszyny/`` niż listował wszystkie.
AVAILABLE_MACHINES_LIMIT = 20


def find_available_machines(
    start_date: str,
    end_date: str,
    machine_type: str | None = None,
) -> FindAvailableMachinesResult:
    """Zwraca listę maszyn dostępnych (bez konfliktów rezerwacji) w okresie
    ``[start_date, end_date]``, opcjonalnie filtrowaną po typie maszyny.

    Używaj tego narzędzia gdy user pyta "jakie maszyny są wolne", "znajdź
    minikoparkę na jutro", "co mam dostępnego w przyszłym tygodniu" itp.

    Args:
        start_date: ISO YYYY-MM-DD (data początku okresu).
        end_date: ISO YYYY-MM-DD (data końca okresu).
        machine_type: Opcjonalny filtr typu — wartość z ``Machine.Type.choices``
            (np. ``"koparka"``, ``"minikoparka"``, ``"agregat prądotwórczy"``,
            ``"podnośnik nożycowy"``, ``"podnośnik teleskopowy"``,
            ``"wózek widłowy"``, ``"walec"``, ``"zagęszczarka"``,
            ``"spawarka"``, ``"inne"``). Akceptujemy też prefix match
            case-insensitive ("minik" → "minikoparka") żeby agent nie musial
            znać dokładnego stringu.

    Returns:
        :class:`FindAvailableMachinesResult` z listą do 20 maszyn. ``truncated=True``
        jeśli było więcej niż 20 spełniających kryteria. Maszyny w statusie
        ``"Wycofana"`` / ``"W serwisie"`` są wykluczone — nie da się ich
        zarezerwować.
    """
    from machines.models import Machine
    from reservations.services import has_conflict

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        return FindAvailableMachinesResult(
            start_date=start_date,
            end_date=end_date,
            machine_type=machine_type,
            total_found=0,
            machines=[],
            error=f"Nieprawidłowy format daty: {exc}",
        )

    if end < start:
        return FindAvailableMachinesResult(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            machine_type=machine_type,
            total_found=0,
            machines=[],
            error="Data końca musi być >= data początku.",
        )

    # Bazowy queryset: tylko maszyny które są w teorii rezerwowalne
    # (W magazynie / Na budowie / Zarezerwowana — wszystkie poza WYCOFANA
    # i W_SERWISIE które są niedostępne na nowe rezerwacje).
    qs = Machine.objects.exclude(status__in=[Machine.Status.WYCOFANA, Machine.Status.W_SERWISIE])

    # Type filter — case-insensitive prefix match.
    resolved_type = None
    if machine_type:
        type_lower = machine_type.strip().lower()
        # Dopasuj do najlepszego z choices.
        for value, _label in Machine.Type.choices:
            if value.lower() == type_lower or value.lower().startswith(type_lower):
                resolved_type = value
                break
        if resolved_type is None:
            return FindAvailableMachinesResult(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                machine_type=machine_type,
                total_found=0,
                machines=[],
                error=(
                    f"Nieznany typ maszyny: '{machine_type}'. Dostępne: "
                    + ", ".join(v for v, _ in Machine.Type.choices)
                ),
            )
        qs = qs.filter(machine_type=resolved_type)

    # Filtrujemy konflikty rezerwacji per maszyna. Wykonujemy w Pythonie,
    # nie w SQL — has_conflict używa złożonej logiki (actual_return_date,
    # legacy compatibility) trudnej do zsubquery'owania.
    available: list[AvailableMachineItem] = []
    truncated = False
    for m in qs.order_by("uid"):
        if has_conflict(machine_id=m.id, start=start, end=end):
            continue
        available.append(
            AvailableMachineItem(
                uid=m.uid,
                name=m.name,
                machine_type=m.get_machine_type_display(),
                location=m.location,
            )
        )
        if len(available) >= AVAILABLE_MACHINES_LIMIT:
            truncated = True
            break

    return FindAvailableMachinesResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        machine_type=resolved_type,
        total_found=len(available),
        machines=available,
        truncated=truncated,
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
    # Faza A — serwis: agent moze wpisac przeglad/naprawe + edytowac istniejacy
    # wpis + przesunac date przegladu maszyny bez tworzenia recordu.
    "create_service_record": ("service.add_servicerecord",),
    "update_service_record": ("service.change_servicerecord",),
    "update_machine_inspection_date": ("machines.change_machine",),
    # Faza B — rezerwacje extras: confirm (pending → confirmed), complete
    # (confirmed → zakonczona + zwrot maszyny), report_breakdown (awaria
    # → zamknij + service entry + maszyna do serwisu), update (zmiana dat).
    "confirm_reservation": ("reservations.change_reservation",),
    "complete_reservation": ("reservations.change_reservation",),
    "update_reservation": ("reservations.change_reservation",),
    "report_breakdown": (
        "reservations.change_reservation",
        "service.add_servicerecord",
        "machines.change_machine",
    ),
    # Faza C — machine CRUD + state transitions: create (nowa maszyna w
    # flocie), update (edycja podstawowych pól), return (z budowy/serwisu
    # do magazynu + zamkniecie aktywnych rezerwacji), close_repair
    # (W_SERWISIE → W_MAGAZYNIE), retire (soft delete na WYCOFANA).
    "create_machine": ("machines.add_machine",),
    "update_machine": ("machines.change_machine",),
    "return_machine": ("machines.change_machine",),
    "close_repair_machine": ("machines.change_machine",),
    "retire_machine": ("machines.change_machine",),
    # Faza D — construction sites CRUD.
    "create_site": ("reservations.add_constructionsite",),
    "update_site": ("reservations.change_constructionsite",),
    "delete_site": ("reservations.delete_constructionsite",),
    # Faza E — accounts (employees): terminate (deactivate + revoke RBAC)
    # i anonymize (GDPR Art.17 — nieodwracalne wymazanie PII).
    "terminate_employee": ("accounts.change_employeeprofile",),
    "anonymize_employee": ("accounts.change_employeeprofile",),
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


# ----------------------------------------------------------------- service
# Limit dla opisu wpisu serwisowego — TextField w DB wytrzyma wiecej, ale
# 2000 znakow to praktyczna granica dla agent-generated content (LLM rzadko
# pisze dluzsze opisy techniczne; jesli user chce — niech uzyje formularza).
_SERVICE_DESCRIPTION_MAX = 2000


class CreateServiceRecordParams(BaseModel):
    """Parametry :func:`propose_create_service_record`.

    ``record_type`` musi byc jedna z 4 wartosci ``ServiceRecord.RecordType``
    (Literal enforce'uje przez Pydantic). Dla typow ``przeglad_*`` serwis
    layer automatycznie liczy ``next_inspection`` (3/6/12 mc od
    ``performed_date``) i bumpuje ``Machine.inspection_date`` — agent NIE
    przekazuje next_inspection osobno.
    """

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny (np. KOP-001)",
    )
    record_type: Literal[
        "przegląd_kwartalny",
        "przegląd_polroczny",
        "przegląd_roczny",
        "naprawa",
    ] = Field(
        description=(
            "Typ wpisu — jedno z: przegląd_kwartalny (3 mc), "
            "przegląd_polroczny (6 mc), przegląd_roczny (12 mc), naprawa"
        ),
    )
    performed_date: str = Field(
        pattern=_ISO_DATE_PATTERN,
        description="Data wykonania (ISO YYYY-MM-DD)",
    )
    performed_by: str = Field(
        default="",
        max_length=_PERSON_NAME_MAX,
        description="Imię i nazwisko technika / serwisanta",
    )
    description: str = Field(
        default="",
        max_length=_SERVICE_DESCRIPTION_MAX,
        description="Opis pracy (np. 'wymiana baterii', 'wymiana oleju')",
    )
    cost: float = Field(
        default=0.0,
        ge=0.0,
        le=10**9,
        description="Koszt w EUR (>= 0). Dla 0 zostawia puste.",
    )


class UpdateServiceRecordParams(BaseModel):
    """Parametry :func:`propose_update_service_record` — korekta istniejacego wpisu.

    Wszystkie pola opcjonalne — agent przekazuje TYLKO te ktore zmieniaja sie.
    Brak update'u jest valid (no-op).
    """

    record_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK wpisu serwisowego do edycji",
    )
    description: str | None = Field(
        default=None,
        max_length=_SERVICE_DESCRIPTION_MAX,
        description="Nowy opis (None = bez zmiany)",
    )
    cost: float | None = Field(
        default=None,
        ge=0.0,
        le=10**9,
        description="Nowy koszt w EUR (None = bez zmiany)",
    )
    performed_by: str | None = Field(
        default=None,
        max_length=_PERSON_NAME_MAX,
        description="Nowa osoba wykonujaca (None = bez zmiany)",
    )


class UpdateMachineInspectionDateParams(BaseModel):
    """Parametry :func:`propose_update_machine_inspection_date`.

    Uzywane gdy user mowi "przesun przeglad koparki 3 na za 3 miesiace" BEZ
    tworzenia formalnego wpisu serwisowego — tylko korekta daty w maszynie.
    Dla przegladow z wpisem serwisowym lepiej uzyc create_service_record
    (auto-calc next_inspection).
    """

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny (np. KOP-003)",
    )
    next_inspection_date: str = Field(
        pattern=_ISO_DATE_PATTERN,
        description="Nowa data nastepnego przegladu (ISO YYYY-MM-DD)",
    )


# ------------------------------------------------------------ faza B params


class ConfirmReservationParams(BaseModel):
    """Parametry :func:`propose_confirm_reservation` (OCZEKUJACA → POTWIERDZONA)."""

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji do potwierdzenia",
    )


class CompleteReservationParams(BaseModel):
    """Parametry :func:`propose_complete_reservation` (POTWIERDZONA → ZAKONCZONA).

    Maszyna wraca do magazynu w tej samej transakcji. Opcjonalne
    ``actual_return_date`` gdy klient zwraca wczesniej niz planowal
    (Hard Return — date < end_date).
    """

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji do zamkniecia",
    )
    actual_return_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        description=(
            "Faktyczna data zwrotu (ISO YYYY-MM-DD), opcjonalna. "
            "Jesli None — zwrot wpisany jako planowany end_date."
        ),
    )


class UpdateReservationParams(BaseModel):
    """Parametry :func:`propose_update_reservation`.

    Wszystkie pola opcjonalne — agent przekazuje tylko zmienione. Brak
    pol = error (avoid no-op). Status NIE jest edytowalny — uzyj
    dedykowanych confirm/cancel/complete tools.
    """

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK rezerwacji do edycji",
    )
    start_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        description="Nowa data od (ISO YYYY-MM-DD), None = bez zmiany",
    )
    end_date: str | None = Field(
        default=None,
        pattern=_ISO_DATE_PATTERN,
        description="Nowa data do (ISO YYYY-MM-DD), None = bez zmiany",
    )
    person: str | None = Field(
        default=None,
        max_length=_PERSON_NAME_MAX,
        description="Nowa osoba rezerwujaca (None = bez zmiany)",
    )
    notes: str | None = Field(
        default=None,
        max_length=_NOTES_MAX,
        description="Nowe notatki (None = bez zmiany)",
    )


class ReportBreakdownParams(BaseModel):
    """Parametry :func:`propose_report_breakdown` (one-click awaria flow).

    Zamyka rezerwacje dzisiaj, ustawia maszyne na W_SERWISIE, tworzy
    ServiceRecord typu naprawa z opisem awarii. Wszystko w jednej
    transakcji.
    """

    reservation_id: int = Field(
        gt=0,
        lt=10**9,
        description="PK otwartej rezerwacji (OCZEKUJACA lub POTWIERDZONA)",
    )
    description: str = Field(
        min_length=5,
        max_length=_SERVICE_DESCRIPTION_MAX,
        description="Opis awarii (min 5 znakow)",
    )


# ------------------------------------------------------------ faza C params


_MACHINE_NAME_MAX = 100
_MACHINE_LOCATION_MAX = 200
_MACHINE_MANUFACTURER_MAX = 100
_MACHINE_SERIAL_MAX = 100


class CreateMachineParams(BaseModel):
    """Parametry :func:`propose_create_machine` (nowa maszyna w flocie).

    Minimum: ``uid`` + ``name``. Reszta opcjonalna z sensownymi defaultami.
    Typ ``inne`` jako default jesli agent nie zna kategorii.
    """

    uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny (np. KOP-099, M-0050) — unikalny",
    )
    name: str = Field(
        max_length=_MACHINE_NAME_MAX,
        description="Nazwa maszyny (np. 'Koparka CAT 320D')",
    )
    machine_type: Literal[
        "koparka",
        "minikoparka",
        "podnośnik nożycowy",
        "podnośnik teleskopowy",
        "agregat prądotwórczy",
        "wózek widłowy",
        "walec",
        "zagęszczarka",
        "spawarka",
        "inne",
    ] = Field(
        default="inne",
        description="Typ maszyny — jedno z choices Machine.Type. Default 'inne'.",
    )
    model: str = Field(
        default="",
        max_length=_MACHINE_NAME_MAX,
        description="Model (np. 'CAT 320D'), opcjonalnie",
    )
    location: str = Field(
        default="Magazyn",
        max_length=_MACHINE_LOCATION_MAX,
        description="Lokalizacja startowa (default 'Magazyn')",
    )
    manufacturer: str = Field(
        default="",
        max_length=_MACHINE_MANUFACTURER_MAX,
        description="Producent (np. 'Caterpillar'), opcjonalnie",
    )
    serial_number: str = Field(
        default="",
        max_length=_MACHINE_SERIAL_MAX,
        description="Numer seryjny producenta, opcjonalnie",
    )


class UpdateMachineParams(BaseModel):
    """Parametry :func:`propose_update_machine` — edycja istniejacej maszyny.

    Tylko bezpieczny subset (nazwa/lokalizacja/notatki/producent/SN). UID
    NIE jest edytowalny (zlamałoby audit trail + URL routing). Status
    edytowany przez dedykowane tools (set_machine_to_service,
    return_machine, close_repair_machine, retire_machine).
    """

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny do edycji",
    )
    name: str | None = Field(
        default=None,
        max_length=_MACHINE_NAME_MAX,
        description="Nowa nazwa (None = bez zmiany)",
    )
    location: str | None = Field(
        default=None,
        max_length=_MACHINE_LOCATION_MAX,
        description="Nowa lokalizacja (None = bez zmiany)",
    )
    notes: str | None = Field(
        default=None,
        max_length=_NOTES_MAX,
        description="Nowe notatki (None = bez zmiany)",
    )
    manufacturer: str | None = Field(
        default=None,
        max_length=_MACHINE_MANUFACTURER_MAX,
        description="Nowy producent (None = bez zmiany)",
    )
    serial_number: str | None = Field(
        default=None,
        max_length=_MACHINE_SERIAL_MAX,
        description="Nowy numer seryjny (None = bez zmiany)",
    )


class ReturnMachineParams(BaseModel):
    """Parametry :func:`propose_return_machine` (zwrot z budowy lub serwisu)."""

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny do zwrotu",
    )


class CloseRepairMachineParams(BaseModel):
    """Parametry :func:`propose_close_repair_machine` (W_SERWISIE → W_MAGAZYNIE)."""

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny w serwisie",
    )


class RetireMachineParams(BaseModel):
    """Parametry :func:`propose_retire_machine` (soft delete — status WYCOFANA)."""

    machine_uid: str = Field(
        max_length=_MACHINE_UID_MAX,
        pattern=_MACHINE_UID_PATTERN,
        description="UID maszyny do wycofania z floty",
    )
    reason: str = Field(
        default="",
        max_length=_NOTES_MAX,
        description="Powod wycofania (opcjonalne, idzie do notes jako [WYCOFANA] <reason>)",
    )


# ------------------------------------------------------------ faza D params


_SITE_NAME_MAX = 200
_SITE_CITY_MAX = 100


class CreateSiteParams(BaseModel):
    """Parametry :func:`propose_create_site` (nowa budowa)."""

    project_number: str = Field(
        max_length=_PROJECT_NUMBER_MAX,
        pattern=_PROJECT_NUMBER_PATTERN,
        description="Numer projektu BUD-RRRR-NNN (np. BUD-2026-099) — unikalny",
    )
    name: str = Field(
        max_length=_SITE_NAME_MAX,
        description="Nazwa budowy (np. 'Magazyn Lubella')",
    )
    address: str = Field(
        max_length=_ADDRESS_MAX,
        description="Adres budowy (np. 'ul. Przemysłowa 5, Lublin')",
    )
    client_name: str = Field(
        default="",
        max_length=_SITE_NAME_MAX,
        description="Nazwa klienta (np. 'Lubella S.A.'), opcjonalnie",
    )
    city: str = Field(
        default="",
        max_length=_SITE_CITY_MAX,
        description="Miasto, opcjonalnie",
    )


class UpdateSiteParams(BaseModel):
    """Parametry :func:`propose_update_site` (edycja istniejacej budowy)."""

    project_number: str = Field(
        max_length=_PROJECT_NUMBER_MAX,
        pattern=_PROJECT_NUMBER_PATTERN,
        description="Numer projektu BUD-RRRR-NNN istniejacej budowy",
    )
    name: str | None = Field(
        default=None,
        max_length=_SITE_NAME_MAX,
        description="Nowa nazwa (None = bez zmiany)",
    )
    address: str | None = Field(
        default=None,
        max_length=_ADDRESS_MAX,
        description="Nowy adres (None = bez zmiany)",
    )
    client_name: str | None = Field(
        default=None,
        max_length=_SITE_NAME_MAX,
        description="Nowy klient (None = bez zmiany)",
    )
    city: str | None = Field(
        default=None,
        max_length=_SITE_CITY_MAX,
        description="Nowe miasto (None = bez zmiany)",
    )
    notes: str | None = Field(
        default=None,
        max_length=_NOTES_MAX,
        description="Nowe notatki (None = bez zmiany)",
    )


class DeleteSiteParams(BaseModel):
    """Parametry :func:`propose_delete_site` (raise jesli ma aktywne rezerwacje)."""

    project_number: str = Field(
        max_length=_PROJECT_NUMBER_MAX,
        pattern=_PROJECT_NUMBER_PATTERN,
        description="Numer projektu BUD-RRRR-NNN budowy do usuniecia",
    )


# ------------------------------------------------------------ faza E params


_USERNAME_MAX = 150  # Django default User.username


class TerminateEmployeeParams(BaseModel):
    """Parametry :func:`propose_terminate_employee`.

    Identyfikator po username (preferowane bo czytelne dla operatora) lub
    user_id (fallback). Reason wymagany dla audit trail.
    """

    username: str = Field(
        max_length=_USERNAME_MAX,
        description="Username pracownika (np. 'jkowalski')",
    )
    reason: str = Field(
        min_length=3,
        max_length=_NOTES_MAX,
        description="Powod zakonczenia zatrudnienia (min 3 znaki, wymagany dla audit)",
    )


class AnonymizeEmployeeParams(BaseModel):
    """Parametry :func:`propose_anonymize_employee` (GDPR Art.17).

    NIEODWRACALNE — PII (imię, nazwisko, email, telefon) zostana wymazane.
    User account pozostaje (dla FK integrity w rezerwacjach), ale konto jest
    deactivated. Nie wymaga reason (GDPR Art.17 to prawo usera, nie wymaga
    uzasadnienia ze strony admina).
    """

    username: str = Field(
        max_length=_USERNAME_MAX,
        description="Username pracownika do anonimizacji (NIEODWRACALNE)",
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


# ----------------------------------------------------------------- service
# Faza A: trzy narzedzia pozwalajace agentowi w pelni zarzadzac wpisami
# serwisowymi + data nastepnego przegladu maszyny.


def propose_create_service_record(params: CreateServiceRecordParams, user) -> str:
    """Proponuje utworzenie nowego wpisu serwisowego (przeglad lub naprawa).

    Dla typow ``przeglad_*`` serwis layer automatycznie liczy ``next_inspection``
    (3/6/12 mc od ``performed_date``) i bumpuje ``Machine.inspection_date``.
    Dla ``naprawa`` ``next_inspection`` zostaje NULL i ``Machine`` nie jest
    dotykany.
    """
    from machines.models import Machine

    auth_err = _check_user_can(user, "create_service_record")
    if auth_err:
        return auth_err

    try:
        performed = date.fromisoformat(params.performed_date)
    except ValueError:
        return _error_json(
            f"Nieprawidłowy format daty (wymagany ISO YYYY-MM-DD): {params.performed_date}."
        )
    if performed > date.today():
        return _error_json("Data wykonania nie może być w przyszłości.")

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    type_label = dict(
        [
            ("przegląd_kwartalny", "Przegląd kwartalny (3 mc)"),
            ("przegląd_polroczny", "Przegląd półroczny (6 mc)"),
            ("przegląd_roczny", "Przegląd roczny (12 mc)"),
            ("naprawa", "Naprawa"),
        ]
    )[params.record_type]

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
        "record_type": params.record_type,
        "performed_date": params.performed_date,
        "performed_by": params.performed_by,
        "description": params.description,
        "cost": float(params.cost),
    }
    cost_str = f"{params.cost:.2f} EUR" if params.cost > 0 else "bez kosztu"
    preview_lines = [
        f"Dopiszę wpis serwisowy do {machine.uid} ({machine.name}):",
        f"  • typ: {type_label}",
        f"  • wykonano: {params.performed_date}",
    ]
    if params.performed_by:
        preview_lines.append(f"  • technik: {params.performed_by}")
    if params.description:
        preview_lines.append(f"  • opis: {params.description}")
    preview_lines.append(f"  • koszt: {cost_str}")
    if params.record_type != "naprawa":
        # Konsystentny z service.services.INSPECTION_INTERVAL_MONTHS.
        months = {"przegląd_kwartalny": 3, "przegląd_polroczny": 6, "przegląd_roczny": 12}[
            params.record_type
        ]
        preview_lines.append(
            f"Po wykonaniu data następnego przeglądu maszyny zostanie "
            f"przesunięta o {months} mc od {params.performed_date}."
        )
    preview = "\n".join(preview_lines)

    _audit_logger.info(
        "CHATBOT PROPOSE create_service_record user=%s machine=%s type=%s cost=%s",
        getattr(user, "pk", None),
        machine.uid,
        params.record_type,
        params.cost,
    )
    return _proposal("create_service_record", payload, preview)


def propose_update_service_record(params: UpdateServiceRecordParams, user) -> str:
    """Proponuje edycję istniejącego wpisu serwisowego (opis / koszt / technik)."""
    from service.models import ServiceRecord

    auth_err = _check_user_can(user, "update_service_record")
    if auth_err:
        return auth_err

    try:
        record = ServiceRecord.objects.select_related("machine").get(pk=params.record_id)
    except ServiceRecord.DoesNotExist:
        return _error_json(f"Wpis serwisowy #{params.record_id} nie istnieje.")

    changes: list[str] = []
    if params.description is not None and params.description != record.description:
        changes.append(f"opis: '{record.description[:60]}' → '{params.description[:60]}'")
    if params.cost is not None and float(params.cost) != float(record.cost.amount):
        changes.append(f"koszt: {record.cost.amount} EUR → {params.cost:.2f} EUR")
    if params.performed_by is not None and params.performed_by != record.performed_by:
        changes.append(f"technik: '{record.performed_by}' → '{params.performed_by}'")

    if not changes:
        return _error_json(
            f"Brak zmian do wykonania na wpisie #{params.record_id} (przekazane wartości "
            f"są identyczne z aktualnymi)."
        )

    payload = {
        "record_id": params.record_id,
        "description": params.description,
        "cost": float(params.cost) if params.cost is not None else None,
        "performed_by": params.performed_by,
    }
    preview = (
        f"Zaktualizuję wpis #{params.record_id} ({record.machine.uid}):\n  • "
        + "\n  • ".join(changes)
    )

    _audit_logger.info(
        "CHATBOT PROPOSE update_service_record user=%s record=%s changes=%s",
        getattr(user, "pk", None),
        params.record_id,
        len(changes),
    )
    return _proposal("update_service_record", payload, preview)


def propose_update_machine_inspection_date(params: UpdateMachineInspectionDateParams, user) -> str:
    """Proponuje przesunięcie daty następnego przeglądu maszyny BEZ tworzenia
    wpisu serwisowego.

    Use-case: przegląd był wykonany off-system (np. przez zewnętrznego
    serwisanta bez wystawienia papierów) i operator chce tylko zaktualizować
    przypomnienie o następnym przeglądzie. Dla typowego flow (przegląd + auto
    przesunięcie daty) lepiej użyć :func:`propose_create_service_record`.
    """
    from machines.models import Machine

    auth_err = _check_user_can(user, "update_machine_inspection_date")
    if auth_err:
        return auth_err

    try:
        new_date = date.fromisoformat(params.next_inspection_date)
    except ValueError:
        return _error_json(
            f"Nieprawidłowy format daty (wymagany ISO YYYY-MM-DD): {params.next_inspection_date}."
        )

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    old_date_str = machine.inspection_date.isoformat() if machine.inspection_date else "brak"

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
        "next_inspection_date": params.next_inspection_date,
    }
    preview = (
        f"Przesunę datę następnego przeglądu maszyny {machine.uid} ({machine.name}):\n"
        f"  • obecna: {old_date_str}\n"
        f"  • nowa: {params.next_inspection_date}"
    )
    if new_date < date.today():
        preview += "\n⚠ Nowa data jest w przeszłości — maszyna od razu będzie przeterminowana."

    _audit_logger.info(
        "CHATBOT PROPOSE update_machine_inspection_date user=%s machine=%s new_date=%s",
        getattr(user, "pk", None),
        machine.uid,
        params.next_inspection_date,
    )
    return _proposal("update_machine_inspection_date", payload, preview)


# ------------------------------------------------------------ faza B propose
# Cztery propose dla rezerwacji: confirm (pending → confirmed), complete
# (confirmed → zakonczona + zwrot maszyny), update (zmiana dat/osoby/notes),
# report_breakdown (awaria → zamknij + service entry).


def propose_confirm_reservation(params: ConfirmReservationParams, user) -> str:
    """Proponuje potwierdzenie rezerwacji (OCZEKUJACA → POTWIERDZONA)."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "confirm_reservation")
    if auth_err:
        return auth_err

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.status != Reservation.Status.OCZEKUJACA:
        return _error_json(
            f"Rezerwacja #{reservation.pk} ma status "
            f"'{reservation.get_status_display()}' — można potwierdzić tylko OCZEKUJACA."
        )

    payload = {"reservation_id": reservation.pk}
    preview = (
        f"Potwierdzę rezerwację #{reservation.pk}: maszyna {reservation.machine.uid} "
        f"({reservation.machine.name}) od {reservation.start_date} "
        f"do {reservation.end_date} dla '{reservation.person}'.\n"
        f"Status: Oczekująca → Potwierdzona."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE confirm_reservation user=%s reservation=%s",
        getattr(user, "pk", None),
        reservation.pk,
    )
    return _proposal("confirm_reservation", payload, preview)


def propose_complete_reservation(params: CompleteReservationParams, user) -> str:
    """Proponuje zakonczenie rezerwacji (POTWIERDZONA → ZAKONCZONA) + zwrot maszyny."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "complete_reservation")
    if auth_err:
        return auth_err

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.status != Reservation.Status.POTWIERDZONA:
        return _error_json(
            f"Rezerwacja #{reservation.pk} ma status "
            f"'{reservation.get_status_display()}' — można zakończyć tylko POTWIERDZONA."
        )

    actual_str = ""
    if params.actual_return_date:
        try:
            actual = date.fromisoformat(params.actual_return_date)
        except ValueError:
            return _error_json(f"Nieprawidłowy format daty: {params.actual_return_date}.")
        if actual < reservation.start_date:
            return _error_json("Faktyczna data zwrotu nie może być wcześniejsza niż start.")
        if actual > date.today():
            return _error_json("Faktyczna data zwrotu nie może być w przyszłości.")
        actual_str = f", faktyczny zwrot: {params.actual_return_date}"

    payload = {
        "reservation_id": reservation.pk,
        "actual_return_date": params.actual_return_date,
    }
    preview = (
        f"Zakończę rezerwację #{reservation.pk}: maszyna {reservation.machine.uid} "
        f"({reservation.machine.name}) wraca do magazynu{actual_str}.\n"
        f"Status: Potwierdzona → Zakończona."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE complete_reservation user=%s reservation=%s actual=%s",
        getattr(user, "pk", None),
        reservation.pk,
        params.actual_return_date,
    )
    return _proposal("complete_reservation", payload, preview)


def propose_update_reservation(params: UpdateReservationParams, user) -> str:
    """Proponuje edycje rezerwacji (daty/osoba/notes — NIE status)."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "update_reservation")
    if auth_err:
        return auth_err

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.status in {
        Reservation.Status.ZAKONCZONA,
        Reservation.Status.ANULOWANA,
    }:
        return _error_json(
            f"Rezerwacja #{reservation.pk} jest terminalna "
            f"({reservation.get_status_display()}) — nie można edytować."
        )

    changes: list[str] = []
    if params.start_date is not None and params.start_date != reservation.start_date.isoformat():
        changes.append(f"data od: {reservation.start_date} → {params.start_date}")
    if params.end_date is not None and params.end_date != reservation.end_date.isoformat():
        changes.append(f"data do: {reservation.end_date} → {params.end_date}")
    if params.person is not None and params.person != reservation.person:
        changes.append(f"osoba: '{reservation.person}' → '{params.person}'")
    if params.notes is not None and params.notes != reservation.notes:
        changes.append(f"notatki: zmiana (długość {len(params.notes)} znaków)")

    if not changes:
        return _error_json(f"Brak zmian do wykonania na rezerwacji #{reservation.pk}.")

    # Walidacja dat — start/end musi być sensowne nawet PRZED execute.
    new_start = (
        date.fromisoformat(params.start_date) if params.start_date else reservation.start_date
    )
    new_end = date.fromisoformat(params.end_date) if params.end_date else reservation.end_date
    if new_end < new_start:
        return _error_json("Data końca musi być >= data początku.")

    payload = {
        "reservation_id": reservation.pk,
        "start_date": params.start_date,
        "end_date": params.end_date,
        "person": params.person,
        "notes": params.notes,
    }
    preview = (
        f"Zaktualizuję rezerwację #{reservation.pk} ({reservation.machine.uid}):\n  • "
        + "\n  • ".join(changes)
    )
    _audit_logger.info(
        "CHATBOT PROPOSE update_reservation user=%s reservation=%s changes=%s",
        getattr(user, "pk", None),
        reservation.pk,
        len(changes),
    )
    return _proposal("update_reservation", payload, preview)


def propose_report_breakdown(params: ReportBreakdownParams, user) -> str:
    """Proponuje zgloszenie awarii rezerwacji (zamkniecie + service entry + maszyna do serwisu)."""
    from reservations.models import Reservation

    auth_err = _check_user_can(user, "report_breakdown")
    if auth_err:
        return auth_err

    try:
        reservation = Reservation.objects.select_related("machine").get(pk=params.reservation_id)
    except Reservation.DoesNotExist:
        return _error_json(f"Rezerwacja #{params.reservation_id} nie istnieje.")

    if reservation.is_closed:
        return _error_json(
            f"Rezerwacja #{reservation.pk} jest już zamknięta "
            f"({reservation.get_status_display()}) — nie można zgłosić awarii."
        )

    payload = {
        "reservation_id": reservation.pk,
        "description": params.description,
    }
    preview = (
        f"Zgłoszę awarię rezerwacji #{reservation.pk} ({reservation.machine.uid}):\n"
        f"  • opis: {params.description[:200]}{'…' if len(params.description) > 200 else ''}\n"
        f"  • rezerwacja zostanie zamknięta dzisiejszą datą\n"
        f"  • maszyna {reservation.machine.uid} → status W serwisie\n"
        f"  • zostanie utworzony wpis serwisowy typu Naprawa"
    )
    _audit_logger.info(
        "CHATBOT PROPOSE report_breakdown user=%s reservation=%s desc_len=%s",
        getattr(user, "pk", None),
        reservation.pk,
        len(params.description),
    )
    return _proposal("report_breakdown", payload, preview)


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
            return _execute_create_reservation(params, user)
        if action == "cancel_reservation":
            return _execute_cancel_reservation(params)
        if action == "change_operator":
            return _execute_change_operator(params, user)
        if action == "swap_machine":
            return _execute_swap_machine(params, user)
        if action == "set_machine_to_service":
            return _execute_set_machine_to_service(params)
        if action == "create_service_record":
            return _execute_create_service_record(params)
        if action == "update_service_record":
            return _execute_update_service_record(params)
        if action == "update_machine_inspection_date":
            return _execute_update_machine_inspection_date(params)
        if action == "confirm_reservation":
            return _execute_confirm_reservation(params)
        if action == "complete_reservation":
            return _execute_complete_reservation(params)
        if action == "update_reservation":
            return _execute_update_reservation(params)
        if action == "report_breakdown":
            return _execute_report_breakdown(params, user)
        if action == "create_machine":
            return _execute_create_machine(params)
        if action == "update_machine":
            return _execute_update_machine(params)
        if action == "return_machine":
            return _execute_return_machine(params)
        if action == "close_repair_machine":
            return _execute_close_repair_machine(params)
        if action == "retire_machine":
            return _execute_retire_machine(params)
        if action == "create_site":
            return _execute_create_site(params)
        if action == "update_site":
            return _execute_update_site(params)
        if action == "delete_site":
            return _execute_delete_site(params)
        if action == "terminate_employee":
            return _execute_terminate_employee(params, user)
        if action == "anonymize_employee":
            return _execute_anonymize_employee(params, user)
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


def _execute_create_reservation(params: dict, user) -> str:
    """Wykonuje create_reservation z params zarówno z text-parsed JSON
    (legacy, z ``machine_id`` PK) jak i z ToolCallPart args (Wave 14-H C-1,
    z ``machine_uid`` string).

    ``user`` (zalogowany użytkownik / dzwoniący zidentyfikowany po caller-ID)
    jest zapisywany jako ``created_by`` rezerwacji — decyduje o adresacie
    e-maila potwierdzającego po jej potwierdzeniu."""
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
        created_by=user if getattr(user, "is_authenticated", False) else None,
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


def _execute_create_service_record(params: dict) -> str:
    """Tworzy wpis serwisowy (przegląd/naprawa) — wywoła service layer ktory dla
    typow przeglad_* automatycznie liczy next_inspection i bumpuje Machine."""
    from decimal import Decimal

    from machines.models import Machine
    from service.services import create_service_record

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)

    record = create_service_record(
        machine=machine,
        record_type=params["record_type"],
        performed_date=date.fromisoformat(params["performed_date"]),
        performed_by=params.get("performed_by", ""),
        description=params.get("description", ""),
        cost=Decimal(str(params.get("cost", 0))),
    )
    cost_str = f"{record.cost.amount} EUR" if record.cost else "bez kosztu"
    if record.next_inspection:
        next_str = f", nast. przegląd: {record.next_inspection.isoformat()}"
    else:
        next_str = ""
    return (
        f"Wpis serwisowy #{record.pk} utworzony dla {machine.uid}: "
        f"{record.get_record_type_display()} ({cost_str}){next_str}."
    )


def _execute_update_service_record(params: dict) -> str:
    """Edytuje istniejacy wpis serwisowy (opis/koszt/technik)."""
    from decimal import Decimal

    from service.models import ServiceRecord
    from service.services import update_service_record

    record = ServiceRecord.objects.select_related("machine").get(pk=params["record_id"])
    changes: dict = {}
    if params.get("description") is not None:
        changes["description"] = params["description"]
    if params.get("cost") is not None:
        changes["cost"] = Decimal(str(params["cost"]))
    if params.get("performed_by") is not None:
        changes["performed_by"] = params["performed_by"]

    update_service_record(record, **changes)
    return f"Wpis #{record.pk} ({record.machine.uid}) zaktualizowany ({', '.join(changes.keys())})."


def _execute_update_machine_inspection_date(params: dict) -> str:
    """Aktualizuje Machine.inspection_date bez tworzenia ServiceRecord."""
    from machines.models import Machine

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)

    new_date = date.fromisoformat(params["next_inspection_date"])
    machine.inspection_date = new_date
    machine.save(update_fields=["inspection_date", "updated_at"])
    return (
        f"Data przeglądu maszyny {machine.uid} zaktualizowana na {params['next_inspection_date']}."
    )


def _execute_confirm_reservation(params: dict) -> str:
    from reservations.models import Reservation
    from reservations.services import confirm_reservation

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    confirm_reservation(reservation)
    return f"Rezerwacja #{reservation.pk} potwierdzona."


def _execute_complete_reservation(params: dict) -> str:
    from reservations.models import Reservation
    from reservations.services import complete_reservation

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    actual = (
        date.fromisoformat(params["actual_return_date"])
        if params.get("actual_return_date")
        else None
    )
    complete_reservation(reservation, actual_return_date=actual)
    actual_str = f" (zwrot: {actual.isoformat()})" if actual else ""
    return f"Rezerwacja #{reservation.pk} zakończona, maszyna wraca do magazynu{actual_str}."


def _execute_update_reservation(params: dict) -> str:
    from reservations.models import Reservation
    from reservations.services import update_reservation

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    fields: dict = {}
    if params.get("start_date") is not None:
        fields["start_date"] = date.fromisoformat(params["start_date"])
    if params.get("end_date") is not None:
        fields["end_date"] = date.fromisoformat(params["end_date"])
    if params.get("person") is not None:
        fields["person"] = params["person"]
    if params.get("notes") is not None:
        fields["notes"] = params["notes"]

    update_reservation(reservation, **fields)
    return f"Rezerwacja #{reservation.pk} zaktualizowana ({', '.join(fields.keys())})."


def _execute_create_machine(params: dict) -> str:
    from machines.services import create_machine

    machine = create_machine(
        uid=params["uid"],
        name=params["name"],
        machine_type=params.get("machine_type", "inne"),
        model=params.get("model", ""),
        location=params.get("location", "Magazyn"),
        manufacturer=params.get("manufacturer", ""),
        serial_number=params.get("serial_number", ""),
    )
    return f"Maszyna {machine.uid} ({machine.name}) utworzona w flocie."


def _execute_update_machine(params: dict) -> str:
    from machines.models import Machine
    from machines.services import update_machine

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)

    changes: dict = {}
    for field in ("name", "location", "notes", "manufacturer", "serial_number"):
        if params.get(field) is not None:
            changes[field] = params[field]
    update_machine(machine, **changes)
    return f"Maszyna {machine.uid} zaktualizowana ({', '.join(changes.keys())})."


def _execute_return_machine(params: dict) -> str:
    from machines.models import Machine
    from machines.services import return_machine_to_warehouse

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)
    result = return_machine_to_warehouse(machine)
    closed = result.get("closed", 0)
    closed_str = f" + zamknięto {closed} aktywnych rezerwacji" if closed else ""
    return f"Maszyna {machine.uid} wróciła do magazynu{closed_str}."


def _execute_close_repair_machine(params: dict) -> str:
    from machines.models import Machine
    from machines.services import close_repair

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)
    close_repair(machine)
    return f"Naprawa maszyny {machine.uid} zakończona, status: W magazynie."


def _execute_create_site(params: dict) -> str:
    from reservations.services import create_site

    site = create_site(
        project_number=params["project_number"],
        name=params["name"],
        address=params["address"],
        client_name=params.get("client_name", ""),
        city=params.get("city", ""),
    )
    return f"Budowa {site.project_number} ({site.name}) utworzona."


def _execute_update_site(params: dict) -> str:
    from reservations.models import ConstructionSite
    from reservations.services import update_site

    site_id = params.get("site_id")
    project_number = params.get("project_number")
    if site_id:
        site = ConstructionSite.objects.get(pk=site_id)
    else:
        site = ConstructionSite.objects.get(project_number=project_number)

    changes: dict = {}
    for field in ("name", "address", "client_name", "city", "notes"):
        if params.get(field) is not None:
            changes[field] = params[field]
    update_site(site, **changes)
    return f"Budowa {site.project_number} zaktualizowana ({', '.join(changes.keys())})."


def _execute_delete_site(params: dict) -> str:
    from reservations.models import ConstructionSite
    from reservations.services import delete_site

    site_id = params.get("site_id")
    project_number = params.get("project_number")
    if site_id:
        site = ConstructionSite.objects.get(pk=site_id)
    else:
        site = ConstructionSite.objects.get(project_number=project_number)
    project = site.project_number
    delete_site(site)
    return f"Budowa {project} usunięta."


def _execute_terminate_employee(params: dict, user) -> str:
    from accounts.models import EmployeeProfile
    from accounts.services import terminate_employee

    profile = EmployeeProfile.objects.select_related("user").get(user__username=params["username"])
    terminate_employee(profile, reason=params.get("reason", ""), actor=user)
    return f"Zatrudnienie pracownika '{params['username']}' zakończone."


def _execute_anonymize_employee(params: dict, user) -> str:
    from accounts.models import EmployeeProfile
    from accounts.services import anonymize_employee

    profile = EmployeeProfile.objects.select_related("user").get(user__username=params["username"])
    anonymize_employee(profile, actor=user)
    return f"Pracownik '{params['username']}' zanonimizowany (GDPR Art.17)."


def _execute_retire_machine(params: dict) -> str:
    from machines.models import Machine
    from machines.services import retire_machine

    machine_id = params.get("machine_id")
    machine_uid = params.get("machine_uid")
    if machine_id:
        machine = Machine.objects.get(pk=machine_id)
    else:
        machine = Machine.objects.get(uid=machine_uid)
    retire_machine(machine, reason=params.get("reason", ""))
    return f"Maszyna {machine.uid} wycofana z floty."


def _execute_report_breakdown(params: dict, user) -> str:
    from reservations.models import Reservation
    from reservations.services import report_breakdown

    reservation = Reservation.objects.get(pk=params["reservation_id"])
    result = report_breakdown(reservation, description=params["description"], actor=user)
    return (
        f"Awaria zgłoszona: rezerwacja #{result['reservation_id']} zamknięta, "
        f"maszyna {result['machine_uid']} → W serwisie, "
        f"wpis serwisowy #{result['service_record_id']} utworzony."
    )


# ------------------------------------------------------------ faza C propose
# Pelen cykl zarzadzania flotą maszyn: create / update / state transitions.


def propose_create_machine(params: CreateMachineParams, user) -> str:
    """Proponuje utworzenie nowej maszyny w flocie."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "create_machine")
    if auth_err:
        return auth_err

    if Machine.objects.filter(uid=params.uid).exists():
        return _error_json(f"Maszyna o UID '{params.uid}' juz istnieje w flocie.")

    payload = {
        "uid": params.uid,
        "name": params.name,
        "machine_type": params.machine_type,
        "model": params.model,
        "location": params.location,
        "manufacturer": params.manufacturer,
        "serial_number": params.serial_number,
    }
    preview_lines = [
        "Utworzę nową maszynę:",
        f"  • UID: {params.uid}",
        f"  • nazwa: {params.name}",
        f"  • typ: {params.machine_type}",
    ]
    if params.model:
        preview_lines.append(f"  • model: {params.model}")
    if params.manufacturer:
        preview_lines.append(f"  • producent: {params.manufacturer}")
    if params.serial_number:
        preview_lines.append(f"  • nr seryjny: {params.serial_number}")
    preview_lines.append(f"  • lokalizacja: {params.location}")
    preview_lines.append("Status startowy: W magazynie.")
    preview = "\n".join(preview_lines)

    _audit_logger.info(
        "CHATBOT PROPOSE create_machine user=%s uid=%s type=%s",
        getattr(user, "pk", None),
        params.uid,
        params.machine_type,
    )
    return _proposal("create_machine", payload, preview)


def propose_update_machine(params: UpdateMachineParams, user) -> str:
    """Proponuje edycję maszyny (bezpieczny subset bez statusu/UID)."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "update_machine")
    if auth_err:
        return auth_err

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    changes: list[str] = []
    if params.name is not None and params.name != machine.name:
        changes.append(f"nazwa: '{machine.name}' → '{params.name}'")
    if params.location is not None and params.location != machine.location:
        changes.append(f"lokalizacja: '{machine.location}' → '{params.location}'")
    if params.notes is not None and params.notes != machine.notes:
        changes.append(f"notatki: zmiana (długość {len(params.notes)} znaków)")
    if params.manufacturer is not None and params.manufacturer != machine.manufacturer:
        changes.append(f"producent: '{machine.manufacturer}' → '{params.manufacturer}'")
    if params.serial_number is not None and params.serial_number != machine.serial_number:
        changes.append(f"nr seryjny: '{machine.serial_number}' → '{params.serial_number}'")

    if not changes:
        return _error_json(f"Brak zmian do wykonania na maszynie {machine.uid}.")

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
        "name": params.name,
        "location": params.location,
        "notes": params.notes,
        "manufacturer": params.manufacturer,
        "serial_number": params.serial_number,
    }
    preview = f"Zaktualizuję maszynę {machine.uid}:\n  • " + "\n  • ".join(changes)
    _audit_logger.info(
        "CHATBOT PROPOSE update_machine user=%s machine=%s changes=%s",
        getattr(user, "pk", None),
        machine.uid,
        len(changes),
    )
    return _proposal("update_machine", payload, preview)


def propose_return_machine(params: ReturnMachineParams, user) -> str:
    """Proponuje zwrot maszyny z budowy/serwisu do magazynu."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "return_machine")
    if auth_err:
        return auth_err

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    if machine.status == Machine.Status.W_MAGAZYNIE:
        return _error_json(f"Maszyna {machine.uid} juz jest w magazynie.")
    if machine.status == Machine.Status.WYCOFANA:
        return _error_json(f"Maszyna {machine.uid} jest wycofana z floty.")

    payload = {"machine_id": machine.pk, "machine_uid": machine.uid}
    preview = (
        f"Zwrócę maszynę {machine.uid} ({machine.name}) do magazynu:\n"
        f"  • obecny status: {machine.get_status_display()} → W magazynie\n"
        f"  • aktywne rezerwacje pokrywające dzisiaj zostaną zamknięte"
    )
    _audit_logger.info(
        "CHATBOT PROPOSE return_machine user=%s machine=%s from_status=%s",
        getattr(user, "pk", None),
        machine.uid,
        machine.status,
    )
    return _proposal("return_machine", payload, preview)


def propose_close_repair_machine(params: CloseRepairMachineParams, user) -> str:
    """Proponuje zakonczenie naprawy maszyny (W_SERWISIE → W_MAGAZYNIE)."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "close_repair_machine")
    if auth_err:
        return auth_err

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    if machine.status != Machine.Status.W_SERWISIE:
        return _error_json(
            f"Maszyna {machine.uid} ma status '{machine.get_status_display()}' "
            f"— można zakończyć naprawę tylko dla 'W serwisie'."
        )

    payload = {"machine_id": machine.pk, "machine_uid": machine.uid}
    preview = (
        f"Zakończę naprawę maszyny {machine.uid} ({machine.name}):\n"
        f"  • status: W serwisie → W magazynie"
    )
    _audit_logger.info(
        "CHATBOT PROPOSE close_repair_machine user=%s machine=%s",
        getattr(user, "pk", None),
        machine.uid,
    )
    return _proposal("close_repair_machine", payload, preview)


def propose_create_site(params: CreateSiteParams, user) -> str:
    """Proponuje utworzenie nowej budowy (project_number unikalny BUD-RRRR-NNN)."""
    from reservations.models import ConstructionSite

    auth_err = _check_user_can(user, "create_site")
    if auth_err:
        return auth_err

    if ConstructionSite.objects.filter(project_number=params.project_number).exists():
        return _error_json(f"Budowa o numerze '{params.project_number}' juz istnieje.")

    payload = {
        "project_number": params.project_number,
        "name": params.name,
        "address": params.address,
        "client_name": params.client_name,
        "city": params.city,
    }
    preview_lines = [
        "Utworzę nową budowę:",
        f"  • numer projektu: {params.project_number}",
        f"  • nazwa: {params.name}",
        f"  • adres: {params.address}",
    ]
    if params.client_name:
        preview_lines.append(f"  • klient: {params.client_name}")
    if params.city:
        preview_lines.append(f"  • miasto: {params.city}")
    preview_lines.append("Status startowy: Aktywna.")
    preview = "\n".join(preview_lines)

    _audit_logger.info(
        "CHATBOT PROPOSE create_site user=%s project=%s",
        getattr(user, "pk", None),
        params.project_number,
    )
    return _proposal("create_site", payload, preview)


def propose_update_site(params: UpdateSiteParams, user) -> str:
    """Proponuje edycję istniejącej budowy."""
    from reservations.models import ConstructionSite

    auth_err = _check_user_can(user, "update_site")
    if auth_err:
        return auth_err

    try:
        site = ConstructionSite.objects.get(project_number=params.project_number)
    except ConstructionSite.DoesNotExist:
        return _error_json(f"Budowa o numerze '{params.project_number}' nie istnieje.")

    changes: list[str] = []
    if params.name is not None and params.name != site.name:
        changes.append(f"nazwa: '{site.name}' → '{params.name}'")
    if params.address is not None and params.address != site.address:
        changes.append(f"adres: '{site.address}' → '{params.address}'")
    if params.client_name is not None and params.client_name != site.client_name:
        changes.append(f"klient: '{site.client_name}' → '{params.client_name}'")
    if params.city is not None and params.city != site.city:
        changes.append(f"miasto: '{site.city}' → '{params.city}'")
    if params.notes is not None and params.notes != site.notes:
        changes.append(f"notatki: zmiana (długość {len(params.notes)} znaków)")

    if not changes:
        return _error_json(f"Brak zmian do wykonania na budowie {site.project_number}.")

    payload = {
        "site_id": site.pk,
        "project_number": site.project_number,
        "name": params.name,
        "address": params.address,
        "client_name": params.client_name,
        "city": params.city,
        "notes": params.notes,
    }
    preview = f"Zaktualizuję budowę {site.project_number}:\n  • " + "\n  • ".join(changes)
    _audit_logger.info(
        "CHATBOT PROPOSE update_site user=%s project=%s changes=%s",
        getattr(user, "pk", None),
        site.project_number,
        len(changes),
    )
    return _proposal("update_site", payload, preview)


def propose_delete_site(params: DeleteSiteParams, user) -> str:
    """Proponuje usunięcie budowy (raise jeśli ma aktywne rezerwacje)."""
    from reservations.models import ConstructionSite

    auth_err = _check_user_can(user, "delete_site")
    if auth_err:
        return auth_err

    try:
        site = ConstructionSite.objects.get(project_number=params.project_number)
    except ConstructionSite.DoesNotExist:
        return _error_json(f"Budowa o numerze '{params.project_number}' nie istnieje.")

    if site.has_active_reservations:
        return _error_json(
            f"Nie można usunąć budowy {site.project_number}: ma "
            f"{site.active_reservation_count} aktywnych rezerwacji."
        )

    payload = {"site_id": site.pk, "project_number": site.project_number}
    preview = (
        f"Usunę budowę {site.project_number} ({site.name}).\n"
        f"⚠ Operacja nieodwracalna. Wszystkie zamknięte rezerwacje "
        f"powiązane z tą budową zostaną osierocone (FK SET NULL)."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE delete_site user=%s project=%s",
        getattr(user, "pk", None),
        site.project_number,
    )
    return _proposal("delete_site", payload, preview)


# ------------------------------------------------------------ faza E propose


def _resolve_employee_profile(username: str):
    """Resolve username → EmployeeProfile lub raise tuple z error JSON."""
    from accounts.models import EmployeeProfile

    try:
        return EmployeeProfile.objects.select_related("user").get(user__username=username)
    except EmployeeProfile.DoesNotExist:
        return None


def propose_terminate_employee(params: TerminateEmployeeParams, user) -> str:
    """Proponuje zakończenie zatrudnienia pracownika (deactivate + revoke RBAC)."""
    auth_err = _check_user_can(user, "terminate_employee")
    if auth_err:
        return auth_err

    profile = _resolve_employee_profile(params.username)
    if profile is None:
        return _error_json(f"Pracownik o username '{params.username}' nie istnieje.")

    if profile.is_anonymized:
        return _error_json(
            f"Pracownik '{params.username}' jest już zanonimizowany — nie można zwalniać."
        )
    if not profile.is_active_employee:
        return _error_json(
            f"Pracownik '{params.username}' już jest zwolniony "
            f"(data zakończenia: {profile.termination_date or 'nieznana'})."
        )

    # Self-termination protection — admin nie może zwolnić siebie.
    if profile.user.pk == getattr(user, "pk", None):
        return _error_json("Nie można zakończyć zatrudnienia samego siebie.")

    payload = {
        "user_id": profile.user.pk,
        "username": params.username,
        "reason": params.reason,
    }
    full_name = profile.user.get_full_name() or params.username
    preview = (
        f"Zakończę zatrudnienie pracownika '{full_name}' ({params.username}):\n"
        f"  • powód: {params.reason}\n"
        f"  • konto zostanie deaktywowane (blokada login)\n"
        f"  • członkostwa w grupach (RBAC) zostaną usunięte\n"
        f"  • aktywne sesje pracownika zostaną zamknięte"
    )
    _audit_logger.info(
        "CHATBOT PROPOSE terminate_employee actor=%s target_user=%s reason_len=%s",
        getattr(user, "pk", None),
        profile.user.pk,
        len(params.reason),
    )
    return _proposal("terminate_employee", payload, preview)


def propose_anonymize_employee(params: AnonymizeEmployeeParams, user) -> str:
    """Proponuje anonimizację pracownika (GDPR Art.17 — NIEODWRACALNE wymazanie PII)."""
    auth_err = _check_user_can(user, "anonymize_employee")
    if auth_err:
        return auth_err

    profile = _resolve_employee_profile(params.username)
    if profile is None:
        return _error_json(f"Pracownik o username '{params.username}' nie istnieje.")

    if profile.is_anonymized:
        return _error_json(
            f"Pracownik '{params.username}' jest już zanonimizowany "
            f"(data: {profile.anonymized_at})."
        )

    # Self-anonymization protection.
    if profile.user.pk == getattr(user, "pk", None):
        return _error_json("Nie można zanonimizować samego siebie.")

    payload = {
        "user_id": profile.user.pk,
        "username": params.username,
    }
    full_name = profile.user.get_full_name() or params.username
    preview = (
        f"⚠ NIEODWRACALNA OPERACJA GDPR Art.17 ⚠\n\n"
        f"Zanonimizuję pracownika '{full_name}' ({params.username}):\n"
        f"  • imię/nazwisko/email/username → zastąpione hashem 'anon-XXXX...'\n"
        f"  • telefon → wyczyszczony\n"
        f"  • konto zostanie deaktywowane (jeśli nie było)\n"
        f"  • historia rezerwacji/serwisu pozostanie (FK integrity)\n\n"
        f"Po wykonaniu PII tego pracownika NIE da się odtworzyć."
    )
    _audit_logger.info(
        "CHATBOT PROPOSE anonymize_employee actor=%s target_user=%s",
        getattr(user, "pk", None),
        profile.user.pk,
    )
    return _proposal("anonymize_employee", payload, preview)


def propose_retire_machine(params: RetireMachineParams, user) -> str:
    """Proponuje wycofanie maszyny z floty (soft delete — status WYCOFANA)."""
    from machines.models import Machine

    auth_err = _check_user_can(user, "retire_machine")
    if auth_err:
        return auth_err

    try:
        machine = Machine.objects.get(uid=params.machine_uid)
    except Machine.DoesNotExist:
        return _error_json(f"Maszyna o UID '{params.machine_uid}' nie istnieje.")

    if machine.status == Machine.Status.WYCOFANA:
        return _error_json(f"Maszyna {machine.uid} jest juz wycofana z floty.")

    payload = {
        "machine_id": machine.pk,
        "machine_uid": machine.uid,
        "reason": params.reason,
    }
    preview_lines = [
        f"Wycofam maszynę {machine.uid} ({machine.name}) z floty:",
        f"  • obecny status: {machine.get_status_display()} → Wycofana",
    ]
    if params.reason:
        preview_lines.append(f"  • powód: {params.reason}")
    preview_lines.append(
        "⚠ Wycofana maszyna nie pojawia się na liście dostępnych — "
        "soft delete (rekord pozostaje w DB dla historii rezerwacji/serwisu)."
    )
    preview = "\n".join(preview_lines)

    _audit_logger.info(
        "CHATBOT PROPOSE retire_machine user=%s machine=%s reason_len=%s",
        getattr(user, "pk", None),
        machine.uid,
        len(params.reason),
    )
    return _proposal("retire_machine", payload, preview)


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
    # Faza A — service write tools.
    "propose_create_service_record": propose_create_service_record,
    "propose_update_service_record": propose_update_service_record,
    "propose_update_machine_inspection_date": propose_update_machine_inspection_date,
    # Faza B — reservation extras.
    "propose_confirm_reservation": propose_confirm_reservation,
    "propose_complete_reservation": propose_complete_reservation,
    "propose_update_reservation": propose_update_reservation,
    "propose_report_breakdown": propose_report_breakdown,
    # Faza C — machine CRUD + state transitions.
    "propose_create_machine": propose_create_machine,
    "propose_update_machine": propose_update_machine,
    "propose_return_machine": propose_return_machine,
    "propose_close_repair_machine": propose_close_repair_machine,
    "propose_retire_machine": propose_retire_machine,
    # Faza D — construction sites CRUD.
    "propose_create_site": propose_create_site,
    "propose_update_site": propose_update_site,
    "propose_delete_site": propose_delete_site,
    # Faza E — accounts (GDPR-careful).
    "propose_terminate_employee": propose_terminate_employee,
    "propose_anonymize_employee": propose_anonymize_employee,
}
