"""Bulk seed demo data — uruchamia wszystkie seed commands w prawidłowej kolejności.

Uruchomienie:
    uv run python manage.py seed_demo                  # tylko nowe rekordy
    uv run python manage.py seed_demo --reset          # wyczyść + zaseeduj od nowa
    uv run python manage.py seed_demo --import-m1      # zaimportuj demo z archive/milestone-1/
"""

from __future__ import annotations

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

# Ścieżka do M1 demo data — wyprowadzona z BASE_DIR (korzeń repo), dzięki
# czemu import działa na świeżym klonie niezależnie od nazwy katalogu nadrzędnego.
M1_DATA_DIR = settings.BASE_DIR / "archive" / "milestone-1" / "data"


class Command(BaseCommand):
    help = "Bulk seed demo data: superuser, budowy, maszyny, rezerwacje, serwis."

    # Domyślna liczba wpisów serwisowych na maszynę (delegowane do
    # ``seed_service``). Przy ~40 maszynach daje ~120 rekordów — zdrowy zbiór
    # dla feature raportów (koszt per maszyna + wykres top-N + Excel z filtrami).
    SERVICE_PER_MACHINE_DEFAULT = 3

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
        parser.add_argument(
            "--service-per-machine",
            type=int,
            default=self.SERVICE_PER_MACHINE_DEFAULT,
            help=(
                "Liczba wpisów serwisowych na maszynę "
                f"(domyślnie {self.SERVICE_PER_MACHINE_DEFAULT})."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            self._reset()

        self._ensure_superuser()
        self._ensure_demo_accounts()

        if opts["import_m1"]:
            self._import_from_m1()
            return

        self.stdout.write(self.style.WARNING("Seedowanie demo data..."))
        call_command("seed_machines", count=opts["machines"], stdout=self.stdout)
        call_command("seed_sites", count=opts["sites"], stdout=self.stdout)
        call_command("seed_reservations", count=opts["reservations"], stdout=self.stdout)
        # Wpisy serwisowe — fundament feature raportów (koszt per maszyna +
        # wykres top-N + Excel z filtrami). ``seed_service`` jest idempotentne
        # (pomija jeśli wpisy już istnieją), więc bezpiecznie wołać przy każdym
        # ``seed_demo``. Po ``--reset`` baza wpisów jest pusta → zostaną utworzone.
        call_command(
            "seed_service",
            per_machine=opts["service_per_machine"],
            stdout=self.stdout,
        )
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

    # Skrzynka demonstracyjna — adresat e-maili potwierdzających podczas pokazu.
    # Pobierana ze środowiska (gitignored ``.env``), nigdy hardkodowana.
    DEMO_INBOX = os.environ.get("DEMO_KIEROWNIK_EMAIL", "demo@planer.local")
    # Hasło kont demo — słaby default, nadpisywalny ze środowiska. Nigdy nie
    # commitujemy realnego hasła w kodzie seeda.
    DEMO_PASSWORD = os.environ.get("DEMO_SEED_PASSWORD", "Planer2026!")
    # Numery, z których prowadzący zadzwoni na scenie — caller-ID ról. Czytane ze
    # środowiska (gitignored ``.env``); realne numery telefonów to dane osobowe i
    # NIGDY nie trafiają do publicznego repo. Defaulty to placeholdery.
    ADMIN_PHONE = os.environ.get("DEMO_ADMIN_PHONE", "+48600000001")
    MONTER_PHONE = os.environ.get("DEMO_MONTER_PHONE", "+48600000013")

    def _ensure_superuser(self):
        admin, created = User.objects.get_or_create(
            username="sebastian",
            defaults={
                "email": self.DEMO_INBOX,
                "first_name": "Sebastian",
                "last_name": "Nowak",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password(self.DEMO_PASSWORD)
            admin.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS("✓ Utworzono superusera 'sebastian'"))
        else:
            # Idempotentnie wyrównujemy e-mail (adresat powiadomień na pokazie).
            if admin.email != self.DEMO_INBOX:
                admin.email = self.DEMO_INBOX
                admin.save(update_fields=["email"])
            self.stdout.write("• Superuser 'sebastian' już istnieje.")

        # Telefon administratora (caller-ID na scenie) na profilu pracownika.
        profile = admin.profile
        if profile.phone != self.ADMIN_PHONE:
            profile.function = profile.Function.ADMIN
            profile.phone = self.ADMIN_PHONE
            profile.save(update_fields=["function", "phone", "updated_at"])

    def _ensure_demo_accounts(self):
        """Tworzy trzy konta ról (kierownik / magazynier / montażysta) używane do
        pokazania zróżnicowanego RBAC. Idempotentne — ponowny seed nie duplikuje.

        ``seba1``/``seba2`` (kierownik/magazynik) mają e-mail skrzynki demo, aby
        utworzona przez nich rezerwacja wysłała potwierdzenie na pokazową skrzynkę.
        """
        from accounts.models import EmployeeProfile

        accounts = [
            (
                "seba1",
                EmployeeProfile.Function.KIEROWNIK,
                "Seba",
                "Kierownik",
                "+48600000011",
                self.DEMO_INBOX,
            ),
            (
                "seba2",
                EmployeeProfile.Function.MAGAZYNIER,
                "Seba",
                "Magazynier",
                "+48600000012",
                self.DEMO_INBOX,
            ),
            (
                "seba3",
                EmployeeProfile.Function.MONTAZYSTA,
                "Seba",
                "Montażysta",
                self.MONTER_PHONE,
                "seba3@planer.local",
            ),
        ]
        for username, function, first, last, phone, email in accounts:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": first,
                    "last_name": last,
                    "is_staff": False,
                    "is_superuser": False,
                },
            )
            if created:
                user.set_password(self.DEMO_PASSWORD)
                user.save(update_fields=["password"])
            profile = user.profile
            profile.function = function
            profile.phone = phone
            profile.save(update_fields=["function", "phone", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                "✓ Konta demo ról: seba1 (kierownik), seba2 (magazynier), seba3 (montażysta)."
            )
        )
        self._preenroll_2fa()

    # Stałe sekrety TOTP dla kont demo wymagających 2FA (kierownik/magazynier) —
    # dzięki temu rola jest "gotowa do pokazu" bez ręcznego skanowania QR.
    # Wartości base32 do wpisania w aplikacji authenticator są udokumentowane lokalnie.
    DEMO_TOTP_KEYS = {
        "seba1": "1234567890abcdef1234567890abcdef12345678",
        "seba2": "fedcba0987654321fedcba0987654321fedcba09",
    }

    def _preenroll_2fa(self):
        """Tworzy potwierdzone urządzenia TOTP dla seba1/seba2 (stałe sekrety)."""
        from django_otp.plugins.otp_totp.models import TOTPDevice

        for username, key in self.DEMO_TOTP_KEYS.items():
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                continue
            TOTPDevice.objects.update_or_create(
                user=user,
                name="default",
                defaults={"key": key, "confirmed": True},
            )
        self.stdout.write(self.style.SUCCESS("✓ 2FA pre-enroll: seba1, seba2 (TOTP)."))

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
