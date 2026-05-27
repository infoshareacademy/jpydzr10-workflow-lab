"""Top-up rezerwacji dla maszyn, które nie mają jeszcze ani jednej.

Komplementarny do ``seed_reservations_demo`` — tamten resetuje wszystko i
re-buduje, ten tylko dosypuje dla nowych maszyn (np. po
``refresh_machine_catalog`` dodał 18 nowych egzemplarzy dla 6 typów).

Zachowanie:

* iteruje ``Machine.objects.exclude(status='Wycofana').filter(reservations=None)``,
* dla każdej generuje rezerwacje w przedziale 01.04.2026..30.09.2026,
  tym samym algorytmem density/duration co podstawowy demo seed,
* status: zakończona (przed dziś), potwierdzona (przed 15.06), mix
  potwierdzona/oczekująca (po 15.06),
* idempotent: jeśli maszyna już ma rezerwacje — pomijana.

Usage::

    uv run python manage.py seed_reservations_topup
    uv run python manage.py seed_reservations_topup --seed 42
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from machines.models import Machine
from reservations.management.commands.seed_reservations_demo import (
    DENSITY_BY_MONTH,
    GAP_MAX_DAYS,
    GAP_MIN_DAYS,
    HORIZON_END,
    PERSONS_OFFICE,
    PRESENTATION_DATE,
    RESPONSIBLE_PERSONS,
    _decide_status,
    _random_address,
    _random_duration,
)
from reservations.models import ConstructionSite, Reservation

# Start dla nowych maszyn — kilka tygodni przed dziś, żeby były wpisy historyczne
# w timeline (kontekst "ta maszyna już była wynajmowana wcześniej").
TOPUP_START = date(2026, 4, 1)


class Command(BaseCommand):
    help = (
        "Dodaje rezerwacje tylko dla maszyn bez ani jednej rezerwacji "
        "(idempotentne; uzupelnia po refresh_machine_catalog)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--seed",
            type=int,
            default=14062026,
            help="Random seed (default 14062026).",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])

        sites = list(ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA))
        if not sites:
            raise CommandError("Brak aktywnych budow — uruchom seed_sites lub seed_demo.")

        machines = list(
            Machine.objects.exclude(status=Machine.Status.WYCOFANA)
            .filter(reservations__isnull=True)
            .order_by("uid")
        )
        if not machines:
            self.stdout.write(self.style.WARNING("Brak maszyn bez rezerwacji — nic do zrobienia."))
            return

        self.stdout.write(f"Maszyn do uzupełnienia: {len(machines)}")

        created = 0
        skipped = 0

        for machine in machines:
            cursor = TOPUP_START
            machine_count = 0

            while cursor < HORIZON_END:
                duration = _random_duration()
                end_date = cursor + timedelta(days=duration)
                if end_date > HORIZON_END:
                    break

                density = DENSITY_BY_MONTH.get(cursor.month, 1.0)
                if random.random() > density:
                    cursor = end_date + timedelta(days=random.randint(GAP_MIN_DAYS, GAP_MAX_DAYS))
                    skipped += 1
                    continue

                status = _decide_status(cursor, end_date)

                Reservation.objects.create(
                    machine=machine,
                    site=random.choice(sites),
                    start_date=cursor,
                    end_date=end_date,
                    person=random.choice(PERSONS_OFFICE),
                    responsible_person=random.choice(RESPONSIBLE_PERSONS),
                    address=_random_address(),
                    status=status,
                    notes=f"Rezerwacja demo prezentacja {PRESENTATION_DATE.isoformat()}",
                )
                created += 1
                machine_count += 1

                cursor = end_date + timedelta(days=random.randint(GAP_MIN_DAYS, GAP_MAX_DAYS))

            self.stdout.write(f"  {machine.uid} ({machine.name}): {machine_count} rezerwacji")

        # Po dodaniu rezerwacji — przelicz status maszyn na 14.06.2026.
        on_site_ids = set(
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                start_date__lte=PRESENTATION_DATE,
                end_date__gte=PRESENTATION_DATE,
            )
            .values_list("machine_id", flat=True)
            .distinct()
        )
        for machine in machines:
            if machine.status in (Machine.Status.W_SERWISIE, Machine.Status.WYCOFANA):
                continue
            if machine.pk in on_site_ids:
                new_status = Machine.Status.NA_BUDOWIE.value
            else:
                has_upcoming = Reservation.objects.filter(
                    machine=machine,
                    status=Reservation.Status.POTWIERDZONA,
                    start_date__gt=PRESENTATION_DATE,
                    start_date__lte=PRESENTATION_DATE + timedelta(days=14),
                ).exists()
                new_status = (
                    Machine.Status.ZAREZERWOWANA.value
                    if has_upcoming
                    else Machine.Status.W_MAGAZYNIE.value
                )
            if machine.status != new_status:
                machine.status = new_status
                machine.save(update_fields=["status"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Utworzono {created} rezerwacji ({skipped} slotow pominietych przez density)."
            )
        )

        counts = Counter(Reservation.objects.values_list("status", flat=True))
        self.stdout.write("Rozklad statusow (cala baza):")
        for status_val, n in sorted(counts.items()):
            self.stdout.write(f"  {status_val}: {n}")
