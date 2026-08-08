"""Doprowadza dane pokazowe do stanu spójnego z kalendarzem.

Dane demo są generowane raz, a potem starzeją się razem z upływem czasu: rezerwacje
kończą się i nikt ich nie domyka, terminy przeglądów mijają, a maszyna potrafi
„pracować" na budowie na podstawie wniosku, którego nikt nie zatwierdził. Efekt
wygląda jak zaniedbana instalacja, a nie jak system, z którego ktoś korzysta.

Komenda usuwa cztery klasy niespójności:

1. Rezerwacja trwająca dziś nie może mieć statusu „oczekująca" — skoro maszyna
   fizycznie stoi na budowie, ktoś ten wniosek zatwierdził.
2. Zwrot spóźniony o tygodnie to nie realizm, tylko porzucone dane. Zostawiamy
   kilka świeżych opóźnień (w wypożyczalni zawsze ktoś się spóźnia), resztę
   domykamy datą planowanego końca.
3. Maszyna na budowie z przeterminowanym przeglądem przeczy komunikatowi samej
   aplikacji („nie może legalnie pracować"). Takim maszynom przesuwamy termin;
   przeterminowane zostają wyłącznie te stojące w magazynie — tam alert ma sens.
4. Po korektach status maszyn wyrównuje ``run_daily_sync``.

Na końcu każdy rekord przechodzi walidację modelu, więc wiadomo, czy dane
pokazowe spełniają te same reguły co dane wprowadzone przez formularz.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from machines.models import Machine
from reservations.models import Reservation
from reservations.services import run_daily_sync

# Ile spóźnionych zwrotów zostawiamy. Zero wyglądałoby sterylnie — w wypożyczalni
# zawsze kilka maszyn wraca po terminie i alert „do zwrotu" ma wtedy sens.
DEFAULT_KEEP_OVERDUE = 3
# Jak daleko w przyszłość przesuwamy przegląd maszyny pracującej na budowie.
INSPECTION_SHIFT_DAYS = 120


class Command(BaseCommand):
    help = "Porządkuje dane pokazowe: statusy rezerwacji, spóźnione zwroty, terminy przeglądów."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-overdue",
            type=int,
            default=DEFAULT_KEEP_OVERDUE,
            help=(
                f"Ile spóźnionych zwrotów zostawić dla realizmu (domyślnie {DEFAULT_KEEP_OVERDUE})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż, co zostałoby zmienione, bez zapisu.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        today = date.today()
        dry = opts["dry_run"]
        self.stdout.write(self.style.WARNING(f"Porządkowanie danych pokazowych ({today})…"))

        confirmed = self._confirm_ongoing(today, dry)
        closed = self._close_stale_returns(today, opts["keep_overdue"], dry)
        shifted = self._fix_inspections_on_site(today, dry)

        if dry:
            self.stdout.write(self.style.WARNING("Tryb podglądu — nic nie zapisano."))
            transaction.set_rollback(True)
            return

        stats = run_daily_sync(today=today)
        self.stdout.write(
            "• Synchronizacja statusów maszyn: "
            f"zmienione={stats['updated']}, przedłużone={stats['extended']}, "
            f"zarezerwowane={stats['reserved']}"
        )
        self._report_validation()
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Gotowe: zatwierdzone {confirmed}, domknięte {closed}, "
                f"przesunięte przeglądy {shifted}."
            )
        )

    # ------------------------------------------------------------------
    def _confirm_ongoing(self, today: date, dry: bool) -> int:
        """Rezerwacja obejmująca dzisiejszy dzień nie może czekać na zatwierdzenie."""
        qs = Reservation.objects.filter(
            status=Reservation.Status.OCZEKUJACA,
            start_date__lte=today,
            end_date__gte=today,
        )
        count = qs.count()
        for res in qs.select_related("machine")[:5]:
            self.stdout.write(
                f"    {res.machine.uid} {res.start_date}–{res.end_date} → potwierdzona"
            )
        if not dry:
            qs.update(status=Reservation.Status.POTWIERDZONA)
        self.stdout.write(f"• Wnioski trwające dziś → potwierdzone: {count}")
        return count

    def _close_stale_returns(self, today: date, keep: int, dry: bool) -> int:
        """Domknij zwroty zaległe od dawna, zostawiając kilka świeżych opóźnień."""
        overdue = list(
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA, end_date__lt=today
            ).order_by("-end_date")
        )
        # Najświeższe opóźnienia zostają — to one wyglądają wiarygodnie na liście
        # „do zwrotu"; zaległości sprzed tygodni tylko zaśmiecają pulpit.
        to_close = overdue[keep:]
        for res in to_close[:5]:
            self.stdout.write(f"    {res.machine.uid} koniec {res.end_date} → zakończona")
        if not dry:
            for res in to_close:
                Reservation.objects.filter(pk=res.pk).update(
                    status=Reservation.Status.ZAKONCZONA,
                    actual_return_date=res.end_date,
                )
        self.stdout.write(
            f"• Zaległe zwroty domknięte: {len(to_close)} (zostawione jako spóźnione: "
            f"{min(keep, len(overdue))})"
        )
        return len(to_close)

    def _fix_inspections_on_site(self, today: date, dry: bool) -> int:
        """Maszyna pracująca na budowie musi mieć ważny przegląd."""
        qs = Machine.objects.filter(
            inspection_date__lt=today,
            status__in=[Machine.Status.NA_BUDOWIE, Machine.Status.ZAREZERWOWANA],
        )
        count = qs.count()
        for machine in qs[:5]:
            self.stdout.write(
                f"    {machine.uid} {machine.name}: przegląd {machine.inspection_date} → "
                f"{today + timedelta(days=INSPECTION_SHIFT_DAYS)}"
            )
        if not dry:
            qs.update(inspection_date=today + timedelta(days=INSPECTION_SHIFT_DAYS))
        self.stdout.write(f"• Przeglądy maszyn w pracy przesunięte: {count}")
        return count

    def _report_validation(self) -> None:
        """Sprawdź, czy dane pokazowe spełniają reguły walidacji modelu."""
        invalid: list[str] = []
        for res in Reservation.objects.select_related("machine").iterator():
            try:
                res.full_clean(exclude=["created_by", "site", "replaced_by"])
            except ValidationError as exc:
                invalid.append(f"#{res.pk} {res.machine.uid}: {exc.messages[0]}")
        if invalid:
            self.stdout.write(
                self.style.WARNING(f"• Rekordy niezgodne z walidacją: {len(invalid)}")
            )
            for line in invalid[:8]:
                self.stdout.write(f"    {line}")
        else:
            self.stdout.write("• Walidacja rezerwacji: wszystkie rekordy poprawne")
