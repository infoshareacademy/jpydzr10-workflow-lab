"""Cron: alerty przeglądowe do administratorów floty.

Usage::

    uv run python manage.py send_inspection_alerts

Dwa rodzaje alertów (każdy = jeden zbiorczy mail z listą maszyn):

* **overdue** — maszyny z przeterminowanym przeglądem; wysyłane przy KAŻDYM
  uruchomieniu (zaległość ma być natrętna, dopóki nie zostanie usunięta).
* **upcoming** — maszyny ze zbliżającym się przeglądem (≤ ``INSPECTION_WARNING_DAYS``);
  idempotentne przez ``Machine.inspection_warning_sent_at`` — jeden alert na okno
  ostrzegawcze. Flaga jest resetowana, gdy maszyna wyjdzie z okna (np. po przeglądzie),
  dzięki czemu kolejne zbliżające się przeglądy znów wywołają alert.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from machines.emails import send_inspection_overdue_email, send_inspection_upcoming_email
from machines.models import INSPECTION_WARNING_DAYS, Machine


class Command(BaseCommand):
    help = "Wysyła alerty o przeterminowanych i zbliżających się przeglądach maszyn."

    def handle(self, *args, **options) -> None:
        # Reset flagi dla maszyn, które wyszły z okna ostrzegawczego (np. po przeglądzie)
        # — bez tego maszyna po kolejnym wpadnięciu w okno nie dostałaby już alertu.
        upcoming_qs = Machine.objects.upcoming_inspection(days=INSPECTION_WARNING_DAYS)
        upcoming_pks = list(upcoming_qs.values_list("pk", flat=True))
        Machine.objects.filter(inspection_warning_sent_at__isnull=False).exclude(
            pk__in=upcoming_pks
        ).update(inspection_warning_sent_at=None)

        overdue = list(Machine.objects.overdue_inspection())
        overdue_sent = send_inspection_overdue_email(overdue)

        upcoming_new = list(upcoming_qs.filter(inspection_warning_sent_at__isnull=True))
        upcoming_sent = send_inspection_upcoming_email(upcoming_new)
        if upcoming_sent:
            Machine.objects.filter(pk__in=[m.pk for m in upcoming_new]).update(
                inspection_warning_sent_at=timezone.now()
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Przeglądy — przeterminowane: {len(overdue)} maszyn "
                f"(mail={'wysłany' if overdue_sent else 'pominięty'}); "
                f"zbliżające się (nowe): {len(upcoming_new)} maszyn "
                f"(mail={'wysłany' if upcoming_sent else 'pominięty'})."
            )
        )
