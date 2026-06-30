"""Retencja dziennika zdarzeń — usuwa wpisy starsze niż N dni (domyślnie 90).

Przeznaczone do cyklicznego cron-a, np. (co tydzień, niedziela 3:00):

    0 3 * * 0 cd /app && uv run python manage.py prune_audit_log --older-than 90
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import AuditLogEntry

DEFAULT_RETENTION_DAYS = 90


class Command(BaseCommand):
    help = "Usuwa wpisy dziennika zdarzeń (AuditLogEntry) starsze niż N dni."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--older-than",
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=f"Wiek w dniach, powyżej którego wpisy są usuwane (domyślnie {DEFAULT_RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż ile wpisów zostałoby usuniętych, ale nie usuwaj.",
        )

    def handle(self, *args, **options) -> None:
        days = options["older_than"]
        if days < 0:
            raise CommandError("--older-than musi być liczbą nieujemną.")

        cutoff = timezone.now() - timedelta(days=days)
        stale = AuditLogEntry.objects.filter(timestamp__lt=cutoff)
        count = stale.count()

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] Do usunięcia: {count} wpisów starszych niż {days} dni "
                    f"(przed {cutoff:%Y-%m-%d %H:%M})."
                )
            )
            return

        stale.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Usunięto {count} wpisów dziennika zdarzeń starszych niż {days} dni."
            )
        )
