"""Verify ze nie ma juz overlapow aktywnych rezerwacji na zadnej maszynie.

Iteruje po wszystkich maszynach + sprawdza pary kolejnych rezerwacji
(oczekujaca/potwierdzona) sortowanych po start_date. Konflikt = end[i] >=
start[i+1] (touching dates traktujemy jako konflikt, zgodnie z has_conflict
w reservations.services).

Wynik:
    - 0 overlapow -> print OK + exit 0
    - >0 overlapow -> wypisz wszystkie + exit 1

Run: uv run python manage.py shell < scripts/verify_no_overlaps.py
"""

from __future__ import annotations

import sys

from machines.models import Machine
from reservations.models import Reservation

ACTIVE_STATUSES = (Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)


def main() -> None:
    overlaps: list[str] = []

    for machine in Machine.objects.order_by("uid"):
        res = list(
            machine.reservations.filter(status__in=ACTIVE_STATUSES).order_by("start_date", "pk")
        )
        for i in range(len(res) - 1):
            a, b = res[i], res[i + 1]
            if a.end_date >= b.start_date:
                overlaps.append(
                    f"OVERLAP: {machine.uid} #{a.pk} "
                    f"({a.start_date} - {a.end_date}) >= #{b.pk} "
                    f"({b.start_date} - {b.end_date})"
                )

    if overlaps:
        print(f"FAIL: znaleziono {len(overlaps)} overlapow:")
        for line in overlaps:
            print(f"  {line}")
        sys.exit(1)
    else:
        print("OK: brak overlapow aktywnych rezerwacji na zadnej maszynie.")


main()
