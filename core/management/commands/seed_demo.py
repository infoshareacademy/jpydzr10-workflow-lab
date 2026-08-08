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

# Loginy kont pokazowych — krótkie i jednoznaczne, bo podczas prezentacji wpisuje
# się je na żywo przy przełączaniu ról. Hasło każdego konta jest równe loginowi
# (patrz ``Command._demo_password``): to środowisko demonstracyjne z danymi
# syntetycznymi, nie instalacja produkcyjna.
ADMIN_USERNAME = "adm"
KIEROWNIK_USERNAME = "kier"
MAGAZYNIER_USERNAME = "mag"
MONTER_USERNAME = "mont"


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
    KIEROWNIK_PHONE = os.environ.get("DEMO_KIER_PHONE", "+48600000011")
    MONTER_PHONE = os.environ.get("DEMO_MONTER_PHONE", "+48600000013")

    @staticmethod
    def _demo_password(username: str) -> str:
        """Hasło konta pokazowego = jego login (nadpisywalne ``DEMO_SEED_PASSWORD``).

        Prezentacja wymaga kilku przelogowań pod presją czasu, a dane są w całości
        syntetyczne — krótki, przewidywalny login/hasło eliminuje literówki na scenie.
        """
        return os.environ.get("DEMO_SEED_PASSWORD") or username

    def _role_inbox(self, role: str) -> str:
        """Adres roli w skrzynce pokazowej — wariant „+rola" tej samej skrzynki.

        Poczta obsługuje sufiks po ``+`` jako ten sam adres docelowy, więc wszystkie
        powiadomienia lądują w jednym miejscu (jeden ekran na pokazie), a mimo to w
        nagłówku „Do:" widać, do której roli system je skierował — bez zakładania
        osobnych kont pocztowych.
        """
        local, _, domain = self.DEMO_INBOX.partition("@")
        if not domain or "+" in local:
            return self.DEMO_INBOX
        return f"{local}+{role}@{domain}"

    @staticmethod
    def _release_phone(phone: str, keep_user_id: int) -> None:
        """Zwolnij numer trzymany przez innego pracownika (``phone`` jest unique).

        Bez tego przepięcie numeru między rolami (np. z administratora na
        kierownika) wywracałoby seed na ``IntegrityError`` przy każdym kolejnym
        uruchomieniu.
        """
        from accounts.models import EmployeeProfile

        if not phone:
            return
        EmployeeProfile.objects.filter(phone=phone).exclude(user_id=keep_user_id).update(phone=None)

    def _ensure_superuser(self):
        admin_inbox = self._role_inbox("admin")
        admin, created = User.objects.get_or_create(
            username=ADMIN_USERNAME,
            defaults={
                "email": admin_inbox,
                "first_name": "Sebastian",
                "last_name": "Nowak",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"✓ Utworzono superusera '{ADMIN_USERNAME}'"))
        else:
            # Idempotentnie wyrównujemy e-mail (adresat powiadomień na pokazie).
            if admin.email != admin_inbox:
                admin.email = admin_inbox
                admin.save(update_fields=["email"])
            self.stdout.write(f"• Superuser '{ADMIN_USERNAME}' już istnieje.")
        # Hasło wyrównujemy zawsze — konta pokazowe mają być przewidywalne nawet
        # po ręcznej zmianie w panelu.
        admin.set_password(self._demo_password(ADMIN_USERNAME))
        admin.save(update_fields=["password"])

        # Telefon administratora (caller-ID na scenie) na profilu pracownika.
        profile = admin.profile
        if profile.phone != self.ADMIN_PHONE:
            self._release_phone(self.ADMIN_PHONE, admin.pk)
            profile.function = profile.Function.ADMIN
            profile.phone = self.ADMIN_PHONE
            profile.save(update_fields=["function", "phone", "updated_at"])

    def _ensure_demo_accounts(self):
        """Tworzy trzy konta ról (kierownik / magazynier / montażysta) używane do
        pokazania zróżnicowanego RBAC. Idempotentne — ponowny seed nie duplikuje.

        Kierownik i magazynier mają e-mail skrzynki pokazowej, aby złożony wniosek
        i jego zatwierdzenie były widoczne w jednym miejscu.
        """
        from accounts.models import EmployeeProfile

        accounts = [
            (
                KIEROWNIK_USERNAME,
                EmployeeProfile.Function.KIEROWNIK,
                "Seba",
                "Kierownik",
                self.KIEROWNIK_PHONE,
                self.DEMO_INBOX,
            ),
            (
                MAGAZYNIER_USERNAME,
                EmployeeProfile.Function.MAGAZYNIER,
                "Seba",
                "Magazynier",
                "+48600000012",
                self._role_inbox("magazynier"),
            ),
            (
                MONTER_USERNAME,
                EmployeeProfile.Function.MONTAZYSTA,
                "Seba",
                "Montażysta",
                self.MONTER_PHONE,
                f"{MONTER_USERNAME}@planer.local",
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
            if not created and user.email != email:
                user.email = email
            user.set_password(self._demo_password(username))
            user.save(update_fields=["password", "email"])
            profile = user.profile
            self._release_phone(phone, user.pk)
            profile.function = function
            profile.phone = phone
            profile.save(update_fields=["function", "phone", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Konta demo ról: {KIEROWNIK_USERNAME} (kierownik), "
                f"{MAGAZYNIER_USERNAME} (magazynier), {MONTER_USERNAME} (montażysta)."
            )
        )
        self._preenroll_2fa()
        self._preenroll_voice_pins()

    # Stałe sekrety TOTP dla kont demo wymagających 2FA (kierownik/magazynier) —
    # dzięki temu rola jest "gotowa do pokazu" bez ręcznego skanowania QR.
    # Wartości base32 do wpisania w aplikacji authenticator są udokumentowane lokalnie.
    DEMO_TOTP_KEYS = {
        KIEROWNIK_USERNAME: "1234567890abcdef1234567890abcdef12345678",
        MAGAZYNIER_USERNAME: "fedcba0987654321fedcba0987654321fedcba09",
    }

    def _preenroll_2fa(self):
        """Tworzy potwierdzone urządzenia TOTP dla kierownika i magazyniera."""
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
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ 2FA pre-enroll: {KIEROWNIK_USERNAME}, {MAGAZYNIER_USERNAME} (TOTP)."
            )
        )

    # Stałe PIN-y głosowe (drugi czynnik DTMF) kont demo — rola „gotowa do pokazu"
    # bez ręcznego ustawiania. Realne wartości pokazu czytamy z env (gitignored);
    # defaulty to NIE-realne placeholdery, by publiczny seed nie ujawniał PIN-ów demo.
    DEMO_VOICE_PINS = {
        ADMIN_USERNAME: os.environ.get("DEMO_ADMIN_VOICE_PIN", "4729"),
        KIEROWNIK_USERNAME: os.environ.get("DEMO_KIER_VOICE_PIN", "8317"),
        MAGAZYNIER_USERNAME: os.environ.get("DEMO_MAG_VOICE_PIN", "6284"),
        MONTER_USERNAME: os.environ.get("DEMO_MONTER_VOICE_PIN", "5193"),
    }

    def _preenroll_voice_pins(self):
        """Ustawia stałe PIN-y głosowe kont demo (idempotentnie, przez serwis).

        Bez tego kroku PIN-y ustawione ręcznie znikają przy re-seedzie (pole
        ``voice_pin_hash`` nie ma backfillu) — a wtedy pokaz głosowy przestaje
        działać, bo dzwoniący nie przejdzie bramy DTMF.
        """
        from accounts.services import set_voice_pin

        for username, pin in self.DEMO_VOICE_PINS.items():
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                continue
            set_voice_pin(user.profile, pin)
        self.stdout.write(
            self.style.SUCCESS("✓ PIN głosowy pre-enroll: " + ", ".join(self.DEMO_VOICE_PINS) + ".")
        )

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
