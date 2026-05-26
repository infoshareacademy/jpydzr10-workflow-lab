"""Cron-callable command that runs :func:`reservations.services.run_daily_sync`.

Usage::

    uv run python manage.py run_daily_sync
    uv run python manage.py run_daily_sync --today=2026-05-20

The ``--today`` flag lets ops re-run the sync as if it were a specific date
(useful for catching up missed runs).
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from reservations.services import run_daily_sync


class Command(BaseCommand):
    help = "Synchronizuje statusy maszyn z aktywnymi rezerwacjami (Hard Return Policy)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--today",
            help="Optional ISO date (YYYY-MM-DD) to use as 'today'. Defaults to date.today().",
        )

    def handle(self, *args, **options) -> None:
        if options.get("today"):
            try:
                today = date.fromisoformat(options["today"])
            except ValueError as exc:
                raise CommandError(f"Invalid --today value (expected YYYY-MM-DD): {exc}") from exc
        else:
            today = None

        result = run_daily_sync(today=today)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sync {result['today']}: updated={result['updated']} "
                f"extended={result['extended']} reserved={result['reserved']}"
            )
        )
