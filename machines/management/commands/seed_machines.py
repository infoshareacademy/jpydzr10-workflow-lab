"""Management command — populate the database with demo machines via factory_boy.

Idempotent by design: if the database already has any machines, the command
exits with a no-op message. Use ``--force`` to top up regardless.

Usage::

    uv run python manage.py seed_machines           # tworzy 20 maszyn jeśli baza pusta
    uv run python manage.py seed_machines --count 50  # 50 maszyn
    uv run python manage.py seed_machines --force   # zawsze dosypuje
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from machines.factories import (
    AvailableMachineFactory,
    InServiceMachineFactory,
    OnSiteMachineFactory,
    OverdueInspectionMachineFactory,
)
from machines.models import Machine


class Command(BaseCommand):
    """Seed demo machines using factory_boy + Faker pl_PL."""

    help = "Wypełnij bazę 20 (lub --count N) demo maszynami z polskimi danymi."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=20, help="Ilość maszyn do utworzenia.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Twórz nawet jeśli baza już zawiera maszyny.",
        )

    def handle(self, *args, **options):
        existing = Machine.objects.count()
        if existing and not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Baza zawiera już {existing} maszyn — pomijam seed. Użyj --force żeby dosypać."
                )
            )
            return

        count = options["count"]
        # Rough split: 60% available, 20% on-site, 10% in-service, 10% overdue inspection.
        plan = (
            (AvailableMachineFactory, int(count * 0.6)),
            (OnSiteMachineFactory, int(count * 0.2)),
            (InServiceMachineFactory, int(count * 0.1)),
            (OverdueInspectionMachineFactory, int(count * 0.1)),
        )

        # Make sure rounding does not leave us short.
        produced = sum(c for _, c in plan)
        leftover = max(count - produced, 0)

        for factory, n in plan:
            factory.create_batch(n)
        if leftover:
            AvailableMachineFactory.create_batch(leftover)

        self.stdout.write(
            self.style.SUCCESS(f"Utworzono {Machine.objects.count() - existing} maszyn.")
        )
