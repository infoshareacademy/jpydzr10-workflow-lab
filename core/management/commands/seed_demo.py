"""Bulk seed demo data — uruchamia wszystkie seed commands w prawidłowej kolejności.

Uruchomienie:
    uv run python manage.py seed_demo                  # tylko nowe rekordy
    uv run python manage.py seed_demo --reset          # wyczyść + zaseeduj od nowa
    uv run python manage.py seed_demo --import-m1      # zaimportuj demo z archive/milestone-1/
"""

from __future__ import annotations

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

# Ścieżka do M1 demo data (kursowe repo)
M1_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "Repo-Github-zaliczenie"
    / "jpydzr10-workflow-lab"
    / "archive"
    / "milestone-1"
    / "data"
)


class Command(BaseCommand):
    help = "Bulk seed demo data: superuser, budowy, maszyny, rezerwacje."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wyczyść istniejące dane przed seedem.",
        )
        parser.add_argument(
            "--import-m1",
            action="store_true",
            help="Zamiast generować przez factory, zaimportuj demo z archive/milestone-1/",
        )
        parser.add_argument(
            "--machines",
            type=int,
            default=20,
            help="Liczba maszyn do wygenerowania (domyślnie 20).",
        )
        parser.add_argument(
            "--sites",
            type=int,
            default=5,
            help="Liczba budów do wygenerowania (domyślnie 5).",
        )
        parser.add_argument(
            "--reservations",
            type=int,
            default=30,
            help="Liczba rezerwacji do wygenerowania (domyślnie 30).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            self._reset()

        self._ensure_superuser()

        if opts["import_m1"]:
            self._import_from_m1()
            return

        self.stdout.write(self.style.WARNING("Seedowanie demo data..."))
        call_command("seed_machines", count=opts["machines"], stdout=self.stdout)
        call_command("seed_sites", count=opts["sites"], stdout=self.stdout)
        call_command("seed_reservations", count=opts["reservations"], stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("✓ Demo data zaseedowane."))

    def _reset(self):
        from machines.models import Machine
        from reservations.models import ConstructionSite, Reservation
        from service.models import ServiceRecord

        self.stdout.write(self.style.WARNING("Resetowanie danych demo..."))
        # Delete order matters — FK są PROTECT (brak CASCADE), więc kasujemy
        # od najgłębszych zależności w górę.
        ServiceRecord.objects.all().delete()  # service → machine FK PROTECT
        Reservation.objects.all().delete()  # reservation → machine + site FK PROTECT
        ConstructionSite.objects.all().delete()
        Machine.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("✓ Dane wyczyszczone."))

    def _ensure_superuser(self):
        if not User.objects.filter(username="sebastian").exists():
            User.objects.create_superuser(
                username="sebastian",
                email="sebastian@planer.local",
                password="Planer2026!",
                first_name="Sebastian",
                last_name="Nowak",
            )
            self.stdout.write(
                self.style.SUCCESS("✓ Utworzono superusera 'sebastian'/'Planer2026!'")
            )
        else:
            self.stdout.write("• Superuser 'sebastian' już istnieje.")

    def _import_from_m1(self):
        machines_json = M1_DATA_DIR / "machines.json"
        reservations_json = M1_DATA_DIR / "reservations.json"

        if not machines_json.exists():
            self.stdout.write(
                self.style.ERROR(f"Brak pliku {machines_json} — sprawdź ścieżkę M1 archive.")
            )
            return

        self.stdout.write(self.style.WARNING(f"Import z {M1_DATA_DIR}..."))
        call_command("import_machines", str(machines_json), stdout=self.stdout)

        # Najpierw budowy — rezerwacje na nie wskazują (FK PROTECT)
        # M1 nie miał budów, więc tworzymy 3 demo dla rezerwacji
        from reservations.factories import ConstructionSiteFactory

        for _ in range(3):
            ConstructionSiteFactory()
        self.stdout.write(self.style.SUCCESS("✓ Utworzono 3 demo budowy."))

        if reservations_json.exists():
            call_command("import_reservations", str(reservations_json), stdout=self.stdout)
        else:
            self.stdout.write(f"• Brak {reservations_json} — pomijam.")

        self.stdout.write(self.style.SUCCESS("✓ Import z M1 zakończony."))
