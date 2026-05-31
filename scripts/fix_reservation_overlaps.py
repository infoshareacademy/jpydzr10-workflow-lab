"""Cleanup overlapujacych rezerwacji w seed data.

Niektore rezerwacje (zwlaszcza historyczne fixtures M1 + dodawane recznie
podczas testow) nakladaja sie czasowo na tej samej maszynie. UI normalnie
blokuje takie sytuacje przez ReservationForm + has_conflict(), ale seed data
i bulk import omijaja te walidacje.

Logika:
    1. Iteruje per maszyna (z pominieciem terminalnych statusow maszyny).
    2. Pobiera aktywne rezerwacje (oczekujaca/potwierdzona) sortowane po
       start_date, pk.
    3. Iteruje parami (res[i], res[i+1]): jesli end[i] >= start[i+1] to
       konflikt (system traktuje touching dates jako konflikt, bo maszyna
       potrzebuje 1 dnia na transport).
    4. Wybiera strategie zaleznie od kontekstu wczesniejszej rezerwacji:
       a) jesli new_end (=later.start - 1) < earlier.start - rezerwacja
          zostalaby negatywna -> ANULUJ (status=anulowana, reason=inne).
       b) jesli earlier.status=POTWIERDZONA i rezerwacja jest aktywna
          dzisiaj (start<=today<=end_orig) i new_end<today - ZAKONCZ
          (complete_reservation z actual_return_date=new_end). To jest
          KLUCZOWE: gdyby skrocic zwyklym save'em, daily_sync Pass 1
          (Hard Return Policy) rozszerzylby end_date z powrotem do today
          bo maszyna jest NA_BUDOWIE.
       c) inaczej zwykly SKROC (earlier.end_date = new_end + save).
    5. Po kazdej zmianie re-fetch listy aktywnych (po cancel/complete
       rezerwacja wypada z OCZEKUJACA/POTWIERDZONA, indeksy moga sie
       zmienic).
    6. Petla az przebieg bez zmian (idempotent).
    7. Logging kazdej akcji.

Run: uv run python manage.py shell < scripts/fix_reservation_overlaps.py
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction

from machines.models import Machine
from reservations.models import Reservation
from reservations.services import cancel_reservation, complete_reservation

ACTIVE_STATUSES = (Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
# Statusy maszyn ktore wykluczaja jakakolwiek modyfikacje rezerwacji.
# Maszyny w serwisie / wycofane nie powinny miec aktywnych rezerwacji w ogole,
# ale jesli historycznie maja - zostawiamy w spokoju (osobny problem do
# rozwiazania manualnie).
TERMINAL_MACHINE_STATUSES = ("W serwisie", "Wycofana")

CANCEL_REASON = Reservation.CancellationReason.INNE

TODAY = date.today()


def get_active_for_machine(machine: Machine) -> list[Reservation]:
    """Pobiera posortowane aktywne rezerwacje per maszyna."""
    return list(
        machine.reservations.filter(status__in=ACTIVE_STATUSES).order_by("start_date", "pk")
    )


def shorten_or_cancel(earlier: Reservation, later: Reservation, *, stats: dict[str, int]) -> None:
    """Naprawia konflikt earlier vs later: skroc / zakoncz / anuluj.

    Modyfikuje rekord w DB. Trzy mozliwe scenariusze (kolejnosc decyzji):

    1. ANULUJ (cancel_reservation):
       Jesli new_end < earlier.start - rezerwacja staje sie negatywna,
       wiec nie da sie jej skrocic. Anulujemy z reason=inne.

    2. ZAKONCZ (complete_reservation):
       Jesli earlier.status=POTWIERDZONA + rezerwacja jest aktywna
       dzisiaj (start<=today<=end) + new_end<today. To jest jedyny
       sposob na trwale "skrocenie" aktywnej dzis rezerwacji - inaczej
       daily_sync Pass 1 (Hard Return Policy) rozszerzylby end z powrotem
       do today bo maszyna jest NA_BUDOWIE. complete + actual_return_date
       ustawia status=ZAKONCZONA + zwraca maszyne (jesli zadna inna
       rezerwacja nie jest aktywna).

    3. SKROC (zwykly save):
       Pozostale przypadki - rezerwacja przyszla, oczekujaca, lub
       konczy sie w przyszlosci. Bezpiecznie modyfikujemy end_date.
    """
    new_end = later.start_date - timedelta(days=1)
    old_end = earlier.end_date

    # 1. ANULUJ - rezerwacja by sie zwinela do <0 dni
    if new_end < earlier.start_date:
        note = (
            f"Auto-cleanup: konflikt z rezerwacja #{later.pk} "
            f"({later.start_date} - {later.end_date}). "
            f"Pierwotna data konca: {old_end}."
        )
        cancel_reservation(earlier, reason=CANCEL_REASON, note=note)
        stats["cancelled"] += 1
        print(
            f"  CANCEL #{earlier.pk} ({earlier.machine.uid}, "
            f"{earlier.start_date} - {old_end}) konflikt z #{later.pk} "
            f"start={later.start_date}; new_end={new_end} bylby przed start={earlier.start_date}"
        )
        return

    # 2. ZAKONCZ - aktywna POTWIERDZONA rezerwacja, skrocenie cofa ja przed today
    #    (musimy complete bo inaczej daily_sync rozszerzy z powrotem)
    is_confirmed = earlier.status == Reservation.Status.POTWIERDZONA
    is_active_today = earlier.start_date <= TODAY <= earlier.end_date
    cuts_to_past = new_end < TODAY

    if is_confirmed and is_active_today and cuts_to_past:
        note = (
            f"Auto-cleanup: konflikt z rezerwacja #{later.pk} "
            f"({later.start_date} - {later.end_date}). "
            f"Pierwotna data konca: {old_end}."
        )
        # Zapisujemy note na rezerwacji (complete_reservation nie przyjmuje notes).
        # Dodajemy do istniejacych notes z separator'em.
        existing_notes = (earlier.notes or "").rstrip()
        sep = "\n\n" if existing_notes else ""
        earlier.notes = f"{existing_notes}{sep}[{TODAY}] {note}"
        earlier.save(update_fields=["notes", "updated_at"])
        complete_reservation(earlier, actual_return_date=new_end, today=TODAY)
        stats["completed"] += 1
        print(
            f"  COMPLETE #{earlier.pk} ({earlier.machine.uid}) "
            f"actual_return_date={new_end} (konflikt z #{later.pk} start={later.start_date}, "
            f"aktywna dzisiaj - inaczej daily_sync rozszerzylby)"
        )
        return

    # 3. SKROC - zwykly safe save
    earlier.end_date = new_end
    earlier.save(update_fields=["end_date", "updated_at"])
    stats["shortened"] += 1
    print(
        f"  SHORTEN #{earlier.pk} ({earlier.machine.uid}) end {old_end} -> {new_end} "
        f"(konflikt z #{later.pk} start={later.start_date})"
    )


def fix_machine(machine: Machine, stats: dict[str, int]) -> int:
    """Naprawia overlapy dla jednej maszyny. Zwraca liczbe zmian w tej maszynie."""
    if machine.status in TERMINAL_MACHINE_STATUSES:
        return 0

    changes_in_machine = 0
    # Petla az przebieg bez zmian. Bezpiecznik na petle nieskonczona (max 100
    # iteracji na maszyne - w realnym scenariuszu kilka iteracji wystarczy).
    for _guard in range(100):
        res_list = get_active_for_machine(machine)
        change_this_pass = False

        for i in range(len(res_list) - 1):
            a, b = res_list[i], res_list[i + 1]
            if a.end_date >= b.start_date:
                shorten_or_cancel(a, b, stats=stats)
                changes_in_machine += 1
                change_this_pass = True
                # Re-fetch listy (a moglo zostac anulowane, indeksy zmienione).
                break

        if not change_this_pass:
            break
    else:
        # Petla nie zakonczyla sie break'iem - przekroczono limit iteracji.
        print(f"WARN: {machine.uid} przekroczono 100 iteracji - moze petla?")

    return changes_in_machine


def main() -> None:
    stats = {"shortened": 0, "completed": 0, "cancelled": 0}
    machines_with_changes = 0
    total_machines = Machine.objects.count()

    print(f"Cleanup overlapow rezerwacji - {total_machines} maszyn do sprawdzenia (today={TODAY}).")
    print("=" * 70)

    with transaction.atomic():
        for machine in Machine.objects.order_by("uid"):
            n = fix_machine(machine, stats)
            if n > 0:
                machines_with_changes += 1

    print("=" * 70)
    print(f"Zmienionych maszyn: {machines_with_changes}")
    print(f"  - skrocone rezerwacje:  {stats['shortened']}")
    print(f"  - zakonczone (early):   {stats['completed']}")
    print(f"  - anulowane rezerwacje: {stats['cancelled']}")
    total = stats["shortened"] + stats["completed"] + stats["cancelled"]
    print(f"  - LACZNIE akcji:        {total}")


main()
