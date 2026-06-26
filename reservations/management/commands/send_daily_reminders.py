"""Cron: przypomnienia T-1 o rezerwacjach startujących jutro (idempotentne).

Usage::

    uv run python manage.py send_daily_reminders
    uv run python manage.py send_daily_reminders --today=2026-07-01

Wysyła e-mail do twórcy każdej potwierdzonej rezerwacji, która zaczyna się
jutro i nie miała jeszcze wysłanego przypomnienia (``reminder_sent_at IS NULL``).
Flaga jest ustawiana dopiero po skutecznej wysyłce, więc trzykrotne uruchomienie
pod rząd wyśle dokładnie jeden mail na rezerwację.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from reservations.emails import send_reservation_reminder_email
from reservations.models import Reservation


class Command(BaseCommand):
    help = "Wysyła przypomnienia T-1 o rezerwacjach startujących jutro (idempotentne)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--today",
            help="Opcjonalna data ISO (YYYY-MM-DD) traktowana jako 'dziś'. Domyślnie date.today().",
        )

    def handle(self, *args, **options) -> None:
        raw = options.get("today")
        try:
            today = date.fromisoformat(raw) if raw else date.today()
        except ValueError as exc:
            raise CommandError(f"Niepoprawna data --today: {raw!r}") from exc

        tomorrow = today + timedelta(days=1)
        pending_pks = list(
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                start_date=tomorrow,
                reminder_sent_at__isnull=True,
            ).values_list("pk", flat=True)
        )

        sent_count = 0
        for pk in pending_pks:
            if send_reservation_reminder_email(pk):
                Reservation.objects.filter(pk=pk).update(reminder_sent_at=timezone.now())
                sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Przypomnienia T-1 na {tomorrow:%d.%m.%Y}: wysłano {sent_count} "
                f"z {len(pending_pks)} kwalifikujących się rezerwacji."
            )
        )
