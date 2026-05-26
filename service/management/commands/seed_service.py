"""Seed demo service records — 3 wpisy na każdą maszynę w DB.

Idempotent — jeśli baza już ma wpisy serwisowe, pomijamy (chyba że
``--force``). Wpisy są rozrzucone na ostatnie 3 lata wstecz, z mixem
przeglądów i napraw, żeby raporty wyglądały realistycznie.

Usage::

    uv run python manage.py seed_service
    uv run python manage.py seed_service --per-machine 5
    uv run python manage.py seed_service --force
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from random import choice, randint, uniform
from random import seed as random_seed

from django.core.management.base import BaseCommand, CommandError

from machines.models import Machine
from service.factories import (
    AnnualInspectionFactory,
    HalfYearInspectionFactory,
    InspectionFactory,
    RepairFactory,
)
from service.models import ServiceRecord


class Command(BaseCommand):
    """Seed demo service records using factory_boy."""

    help = "Tworzy N wpisów serwisowych na każdą maszynę (domyślnie 3)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--per-machine",
            type=int,
            default=3,
            help="Ile wpisów na maszynę (domyślnie 3).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Twórz nawet jeśli baza już ma wpisy serwisowe.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed dla powtarzalności.",
        )

    def handle(self, *args, **options) -> None:
        random_seed(options["seed"])

        existing = ServiceRecord.objects.count()
        if existing and not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Baza zawiera już {existing} wpisów serwisowych — pomijam seed. "
                    "Użyj --force żeby dosypać."
                )
            )
            return

        machines = list(Machine.objects.all())
        if not machines:
            raise CommandError("Brak maszyn w bazie — uruchom najpierw seed_machines.")

        per_machine = options["per_machine"]
        today = date.today()
        # Pulling factories instead of writing manual creates keeps the
        # distribution realistic (factory_boy + Faker).
        factories = (
            (InspectionFactory, 0.35),
            (HalfYearInspectionFactory, 0.15),
            (AnnualInspectionFactory, 0.20),
            (RepairFactory, 0.30),
        )

        created = 0
        for machine in machines:
            for _ in range(per_machine):
                factory = _weighted_pick(factories)
                # Rozrzuć daty na ostatnie 3 lata.
                performed = today - timedelta(days=randint(1, 3 * 365))
                next_insp = (
                    performed + timedelta(days=randint(60, 360))
                    if factory is not RepairFactory
                    else None
                )
                factory(
                    machine=machine,
                    performed_date=performed,
                    next_inspection=next_insp,
                    cost=Decimal(str(round(uniform(150, 4500), 2))),
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Utworzono {created} wpisów serwisowych (po ~{per_machine} na maszynę)."
            )
        )


def _weighted_pick(items):
    """Pick a factory class from ``[(factory, weight), ...]`` honouring weights."""
    factories, weights = zip(*items, strict=True)
    cumulative = []
    total = 0.0
    for w in weights:
        total += w
        cumulative.append(total)
    pick = uniform(0, total)
    for factory, threshold in zip(factories, cumulative, strict=True):
        if pick <= threshold:
            return factory
    return choice(factories)  # pragma: no cover — defensive fallback
