"""
Logika biznesowa: wykrywanie konfliktów, synchronizacja statusów.

Nie zawiera żadnych funkcji I/O (input/print) — te są w ui.py.
"""

from datetime import date

from models import Machine, Reservation
from utils import parse_date

# =============================================================================
# LOGIKA REZERWACJI
# =============================================================================


def has_conflict(
    reservations: list[Reservation],
    machine_id: str,
    start: str,
    end: str,
    exclude_id: str = "",
) -> bool:
    """Sprawdza czy maszyna jest zajęta w podanym terminie.

    Dwa zakresy się nakładają gdy: start_a <= end_b ORAZ end_a >= start_b

    Uwaga: stykające się daty (end_a == start_b) SĄ traktowane jako konflikt.
    W branży budowlanej maszyna potrzebuje transportu i przygotowania,
    więc rezerwacja "dzień na dzień" nie jest praktyczna.
    """
    new_start = parse_date(start)
    new_end = parse_date(end)

    for res in reservations:
        if res.machine_id != machine_id:
            continue
        if res.status in ("anulowana", "zakończona"):
            continue
        if res.id == exclude_id:
            continue
        res_start = parse_date(res.start_date)
        res_end = parse_date(res.end_date)
        if new_start <= res_end and new_end >= res_start:
            return True
    return False


# =============================================================================
# SYNCHRONIZACJA STATUSÓW (Hard Return Policy)
# =============================================================================


def run_daily_sync(
    machines: list[Machine],
    reservations: list[Reservation],
) -> dict[str, int]:
    """Codzienna synchronizacja statusów.

    Reguły (w kolejności priorytetu):
    1. Maszyny ze statusem 'W serwisie' — pomijane (serwis > automatyka)
    2. Rezerwacja aktywna (start <= dziś <= end) → maszyna 'Na budowie'
    3. Rezerwacja przeterminowana (end < dziś, maszyna nie wróciła)
       → przedłuż end_date do dziś (Hard Return Policy)
    4. Maszyna z rezerwacją w przyszłości → status 'Zarezerwowana'

    Returns:
        dict z kluczami: updated, extended, reserved
    """
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    updated = extended = reserved = 0

    machine_map: dict[str, Machine] = {m.uid: m for m in machines}

    for res in reservations:
        if res.status != "potwierdzona":
            continue

        machine = machine_map.get(res.machine_id)
        if not machine:
            continue

        # Maszyna w serwisie — nie ruszamy jej statusu
        if machine.status == "W serwisie":
            continue

        start = parse_date(res.start_date)
        end = parse_date(res.end_date)

        if start <= today <= end:
            if machine.status != "Na budowie":
                machine.status = "Na budowie"
                machine.location = res.address or machine.location
                updated += 1

        elif end < today:
            # Rezerwacja przeterminowana — maszyna nie wróciła
            if machine.status == "Na budowie":
                res.end_date = today_str
                extended += 1

        elif start > today and machine.status == "W magazynie":
            machine.status = "Zarezerwowana"
            reserved += 1

    return {"updated": updated, "extended": extended, "reserved": reserved}
