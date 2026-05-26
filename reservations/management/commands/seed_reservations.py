"""Seed N demo reservations spread across all machines and demo sites.

Usage::

    uv run python manage.py seed_reservations
    uv run python manage.py seed_reservations --count=50

Requires at least one :class:`machines.Machine` and one
:class:`reservations.ConstructionSite` in the DB — run ``seed_machines`` and
``seed_sites`` first. Skips machines that already have a conflicting
reservation in the random date range so the script is re-runnable.
"""

from __future__ import annotations

from datetime import date, timedelta
from random import choice, randint
from random import seed as random_seed

from django.core.management.base import BaseCommand, CommandError

from machines.models import Machine
from reservations.factories import (
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import ConstructionSite
from reservations.services import has_conflict


class Command(BaseCommand):
    help = "Tworzy N losowych rezerwacji rozrzuconych po maszynach i budowach."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--count", type=int, default=30)
        parser.add_argument(
            "--seed", type=int, default=42, help="Random seed (dla powtarzalności)."
        )

    def handle(self, *args, **options) -> None:
        random_seed(options["seed"])
        count = options["count"]

        machines = list(Machine.objects.exclude(status=Machine.Status.W_SERWISIE))
        sites = list(ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA))
        if not machines:
            raise CommandError("Brak dostępnych maszyn — uruchom najpierw seed_machines.")
        if not sites:
            raise CommandError("Brak aktywnych budów — uruchom najpierw seed_sites.")

        created = 0
        skipped = 0
        today = date.today()

        # 70% confirmed, 30% pending — realistic split for a demo.
        for _ in range(count):
            machine = choice(machines)
            site = choice(sites)
            start = today + timedelta(days=randint(-20, 60))
            end = start + timedelta(days=randint(1, 14))
            if has_conflict(machine_id=machine.pk, start=start, end=end):
                skipped += 1
                continue

            factory_cls = (
                ConfirmedReservationFactory if randint(1, 10) <= 7 else PendingReservationFactory
            )
            factory_cls(
                machine=machine,
                site=site,
                start_date=start,
                end_date=end,
            )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo rezerwacje: utworzono {created}, pominięto {skipped} (konflikt)."
            )
        )
