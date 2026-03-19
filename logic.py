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
    więc rezerwacja "dzień na dzień" nie jest praktyczna. Jeśli wymagania
    się zmienią, zamień <= na < w jednym z warunków.
    """
    new_start = parse_date(start)
    new_end = parse_date(end)

    for res in reservations:
        if res.machine_id != machine_id:
            continue
        if res.status in ("rejected", "completed"):
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
    1. Maszyny ze statusem 'In Herstelling' — pomijane (serwis > automatyka)
    2. Rezerwacja aktywna (start <= dziś <= end) → maszyna 'Op de werf'
    3. Rezerwacja przeterminowana (end < dziś, maszyna nie wróciła)
       → przedłuż end_date do dziś (Hard Return Policy)
    4. Maszyna z rezerwacją w przyszłości → status 'Gereserveerd'

    Uwaga dotycząca kolejności iteracji:
    Jeśli maszyna ma jednocześnie aktywną i przeterminowaną rezerwację,
    wynik zależy od kolejności rezerwacji na liście. To jest intencjonalne:
    - Aktywna rezerwacja ustawi 'Op de werf'
    - Przeterminowana (przetworzona później) przedłuży end_date do dziś,
      bo maszyna jest już 'Op de werf'
    W obu przypadkach maszyna poprawnie pozostaje na budowie.

    Returns:
        dict z kluczami: updated, extended, reserved
    """
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    updated = extended = reserved = 0

    # Zbierz aktywne rezerwacje per maszyna, żeby uniknąć wielokrotnych zmian
    machine_map: dict[str, Machine] = {m.uid: m for m in machines}

    for res in reservations:
        if res.status != "confirmed":
            continue

        machine = machine_map.get(res.machine_id)
        if not machine:
            continue

        # Maszyna w serwisie — nie ruszamy jej statusu
        if machine.status == "In Herstelling":
            continue

        start = parse_date(res.start_date)
        end = parse_date(res.end_date)

        if start <= today <= end:
            # Rezerwacja aktywna — maszyna powinna być na budowie
            # UWAGA: Lokalizacja aktualizowana tylko przy zmianie statusu.
            # Jeśli maszyna jest już "Op de werf" z innym adresem (np. przeniesiona
            # między budowami), lokalizacja NIE zostanie zmieniona automatycznie.
            # To jest intencjonalne — ręczna zmiana lokalizacji przez edit_machine.
            if machine.status != "Op de werf":
                machine.status = "Op de werf"
                machine.location = res.address or machine.location
                updated += 1

        elif end < today:
            # Rezerwacja przeterminowana — maszyna nie wróciła
            # Przedłuż rezerwację do dziś (Hard Return Policy)
            if machine.status == "Op de werf":
                res.end_date = today_str
                extended += 1

        elif start > today:
            # Rezerwacja w przyszłości — oznacz maszynę jako zarezerwowaną
            # (tylko jeśli nie jest już na budowie z inną rezerwacją)
            if machine.status == "In Magazijn":
                machine.status = "Gereserveerd"
                reserved += 1

    return {"updated": updated, "extended": extended, "reserved": reserved}
