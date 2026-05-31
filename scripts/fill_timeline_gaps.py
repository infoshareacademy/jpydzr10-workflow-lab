"""Dopelnia dziury w timeline rezerwacji - tworzy nowe rezerwacje w dziurach >10 dni.

Kontekst: poprzedni cleanup overlapow zostawi maszyny z duzymi dziurami w timeline
(czesc rezerwacji byla skracana/anulowana/zakanczana). Wynikiem jest pusty timeline
ktory wyglada nieatrakcyjnie na prezentacji. Ten skrypt DODAJE nowe rezerwacje w
dziurach uzywajac WYLACZNIE istniejacych osob (person), osob odpowiedzialnych
(responsible_person) i budow (ConstructionSite) z bazy.

Logika:
    1. Iteracja po maszynach z `is_reservable=True` i statusem nie w
       (W_SERWISIE, WYCOFANA).
    2. Per maszyna: sortuj aktywne rezerwacje (oczekujaca/potwierdzona) po start.
    3. Znajdz dziury:
       a) od `today` do pierwszej rezerwacji jesli pierwsza > today + 10 dni
       b) miedzy res[i].end_date a res[i+1].start_date jesli gap > 10 dni
          (tylko gdy res[i].end_date >= today - dziury w przeszlosci omijamy)
       c) od ostatniej rezerwacji w przyszlosc do today+90 dni jesli gap > 10 dni
          (lub od today jesli wszystkie rezerwacje sa w przeszlosci)
    4. W kazdej dziurze stworz 1-2 rezerwacje (zaleznie od dlugosci dziury).
    5. Walidacja przez `create_reservation` (sprawdza `has_conflict`).

Wybor danych:
    - person: losowy z istniejacych unique `Reservation.objects.values_list('person')`
    - responsible_person: losowy z istniejacych unique (pomijamy puste)
    - site: losowy z `ConstructionSite.objects.filter(status=AKTYWNA)`
    - address: site.address (NIE losowy, NIE wymyslony)
    - status: 60% potwierdzona / 40% oczekujaca
    - notes: "Dopelnienie linii czasu 2026-05-31"

Deterministycznie: `random.seed(2026)`.

Run: uv run python manage.py shell < scripts/fill_timeline_gaps.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.db import transaction

from machines.models import Machine
from reservations.models import ConstructionSite, Reservation
from reservations.services import create_reservation

# ---------------------------------------------------------------------------
# Konfiguracja
# ---------------------------------------------------------------------------

random.seed(2026)

TODAY = date.today()
HORIZON_DAYS = 90  # dokad w przyszlosc dopelniamy
GAP_THRESHOLD_DAYS = 10  # minimalna dziura do wypelnienia
MIN_RES_DURATION = 4  # min dni rezerwacji
MAX_RES_DURATION = 14  # max dni rezerwacji
BUFFER_DAYS = 1  # min przerwa miedzy rezerwacjami (touching dates = konflikt)

ACTIVE_STATUSES = (Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
EXCLUDED_MACHINE_STATUSES = (Machine.Status.W_SERWISIE, Machine.Status.WYCOFANA)

NOTES_TAG = "Dopelnienie linii czasu 2026-05-31"


# ---------------------------------------------------------------------------
# Pule danych z bazy (tylko istniejace osoby i budowy)
# ---------------------------------------------------------------------------


def get_pools() -> tuple[list[str], list[str], list[ConstructionSite]]:
    """Pobiera unikalne pula person, responsible_person i aktywnych budow."""
    persons = sorted(
        {
            p
            for p in Reservation.objects.values_list("person", flat=True).distinct()
            if p and p.strip()
        }
    )
    responsibles = sorted(
        {
            r
            for r in Reservation.objects.values_list("responsible_person", flat=True).distinct()
            if r and r.strip()
        }
    )
    sites = list(
        ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA).order_by(
            "project_number"
        )
    )
    return persons, responsibles, sites


# ---------------------------------------------------------------------------
# Wyznaczanie dziur per maszyna
# ---------------------------------------------------------------------------


def find_gaps(machine: Machine) -> list[tuple[date, date]]:
    """Zwraca liste dziur (gap_start, gap_end) >= GAP_THRESHOLD_DAYS dla maszyny.

    Dziury sa zawsze >= today (nie tworzymy rezerwacji w przeszlosci).
    Horyzont: today..today+HORIZON_DAYS.

    gap_start = pierwszy wolny dzien (po BUFFER_DAYS od poprzedniej rezerwacji
                lub today).
    gap_end   = ostatni wolny dzien (BUFFER_DAYS przed nastepna rezerwacja
                lub horizon).
    """
    horizon = TODAY + timedelta(days=HORIZON_DAYS)
    active = list(
        machine.reservations.filter(status__in=ACTIVE_STATUSES).order_by("start_date", "pk")
    )
    # Tylko rezerwacje ktore "siegaja" do >= today - rezerwacje skonczone w
    # przeszlosci nie blokuja dziury "od today do nastepnej".
    future_or_current = [r for r in active if r.end_date >= TODAY]

    gaps: list[tuple[date, date]] = []

    if not future_or_current:
        # Brak aktywnych w przyszlosci - cala dziura od today do horizon.
        gap_start = TODAY
        gap_end = horizon
        if (gap_end - gap_start).days >= GAP_THRESHOLD_DAYS:
            gaps.append((gap_start, gap_end))
        return gaps

    # Dziura przed pierwsza rezerwacja (jesli pierwsza > today + threshold).
    first = future_or_current[0]
    if first.start_date > TODAY + timedelta(days=GAP_THRESHOLD_DAYS + BUFFER_DAYS):
        gap_start = TODAY
        gap_end = first.start_date - timedelta(days=BUFFER_DAYS + 1)
        if (gap_end - gap_start).days >= GAP_THRESHOLD_DAYS:
            gaps.append((gap_start, gap_end))

    # Dziury miedzy kolejnymi rezerwacjami.
    for i in range(len(future_or_current) - 1):
        a, b = future_or_current[i], future_or_current[i + 1]
        gap_start = a.end_date + timedelta(days=BUFFER_DAYS + 1)
        gap_end = b.start_date - timedelta(days=BUFFER_DAYS + 1)
        if (gap_end - gap_start).days >= GAP_THRESHOLD_DAYS:
            gaps.append((gap_start, gap_end))

    # Dziura po ostatniej rezerwacji do horizon.
    last = future_or_current[-1]
    if last.end_date < horizon - timedelta(days=GAP_THRESHOLD_DAYS):
        gap_start = last.end_date + timedelta(days=BUFFER_DAYS + 1)
        gap_end = horizon
        if (gap_end - gap_start).days >= GAP_THRESHOLD_DAYS:
            gaps.append((gap_start, gap_end))

    return gaps


# ---------------------------------------------------------------------------
# Generacja rezerwacji wypelniajacych dziure
# ---------------------------------------------------------------------------


def plan_reservations_for_gap(
    gap_start: date, gap_end: date
) -> list[tuple[date, date]]:
    """Planuje 1-2 zakresy dat wewnatrz dziury.

    Jesli dziura < 25 dni -> 1 rezerwacja (4..min(14, gap)).
    Jesli dziura >= 25 dni -> 2 rezerwacje rozdzielone BUFFER_DAYS.
    """
    gap_days = (gap_end - gap_start).days + 1
    plans: list[tuple[date, date]] = []

    if gap_days < 25:
        # 1 rezerwacja - randomowy start i dlugosc w obrebie dziury.
        max_dur = min(MAX_RES_DURATION, gap_days)
        duration = random.randint(MIN_RES_DURATION, max(MIN_RES_DURATION, max_dur))
        # losuj start tak zeby rezerwacja zmiescila sie w dziurze
        max_start_offset = gap_days - duration
        start_offset = random.randint(0, max(0, max_start_offset))
        s = gap_start + timedelta(days=start_offset)
        e = s + timedelta(days=duration - 1)
        if e > gap_end:
            e = gap_end
        plans.append((s, e))
    else:
        # 2 rezerwacje - podziel dziure na pol z buforem.
        half = gap_days // 2
        # Rez 1: w pierwszej polowie
        dur1 = random.randint(MIN_RES_DURATION, min(MAX_RES_DURATION, half - BUFFER_DAYS))
        max_off1 = half - dur1 - BUFFER_DAYS
        off1 = random.randint(0, max(0, max_off1))
        s1 = gap_start + timedelta(days=off1)
        e1 = s1 + timedelta(days=dur1 - 1)
        plans.append((s1, e1))

        # Rez 2: w drugiej polowie, po e1 + BUFFER + 1
        second_start = e1 + timedelta(days=BUFFER_DAYS + 1)
        if second_start <= gap_end:
            remaining = (gap_end - second_start).days + 1
            if remaining >= MIN_RES_DURATION:
                dur2 = random.randint(MIN_RES_DURATION, min(MAX_RES_DURATION, remaining))
                max_off2 = remaining - dur2
                off2 = random.randint(0, max(0, max_off2))
                s2 = second_start + timedelta(days=off2)
                e2 = s2 + timedelta(days=dur2 - 1)
                if e2 > gap_end:
                    e2 = gap_end
                plans.append((s2, e2))

    return plans


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    persons, responsibles, sites = get_pools()

    print(f"Pula danych z bazy:")
    print(f"  - person:             {len(persons)} unique")
    print(f"  - responsible_person: {len(responsibles)} unique")
    print(f"  - sites (aktywne):    {len(sites)}")

    if not persons or not responsibles or not sites:
        print("BLAD: pula person/responsible/sites jest pusta - nie da sie generowac.")
        return

    machines = list(
        Machine.objects.filter(is_reservable=True)
        .exclude(status__in=EXCLUDED_MACHINE_STATUSES)
        .order_by("uid")
    )
    print(f"Maszyn do sprawdzenia: {len(machines)} (today={TODAY}, horizon={HORIZON_DAYS}d)")
    print("=" * 70)

    created = 0
    machines_filled = 0
    failed = 0

    with transaction.atomic():
        for machine in machines:
            gaps = find_gaps(machine)
            if not gaps:
                continue

            machine_created = 0
            for gap_start, gap_end in gaps:
                plans = plan_reservations_for_gap(gap_start, gap_end)
                for s, e in plans:
                    # 60% potwierdzona, 40% oczekujaca
                    will_confirm = random.random() < 0.6
                    person = random.choice(persons)
                    responsible = random.choice(responsibles)
                    site = random.choice(sites)
                    try:
                        res = create_reservation(
                            machine_id=machine.pk,
                            site_id=site.pk,
                            start_date=s,
                            end_date=e,
                            person=person,
                            responsible_person=responsible,
                            address=site.address,
                            notes=NOTES_TAG,
                            today=TODAY,
                        )
                        if will_confirm:
                            # Bezposrednio ustawiamy status na potwierdzona zeby
                            # uniknac calego flow confirm_reservation (ktory robi
                            # select_for_update + log). Tu wypelniamy seed data.
                            res.status = Reservation.Status.POTWIERDZONA
                            res.save(update_fields=["status", "updated_at"])
                        created += 1
                        machine_created += 1
                    except Exception as exc:
                        failed += 1
                        print(
                            f"  FAIL {machine.uid} {s}..{e}: {type(exc).__name__}: {exc}"
                        )

            if machine_created > 0:
                machines_filled += 1
                print(
                    f"  + {machine.uid}: dodano {machine_created} rezerwacji "
                    f"(dziur: {len(gaps)})"
                )

    print("=" * 70)
    print(f"Maszyn z dodanymi rezerwacjami: {machines_filled} / {len(machines)}")
    print(f"Lacznie dodanych rezerwacji:     {created}")
    print(f"Bledow walidacji:                {failed}")


main()
