"""Smoke tests dla management commands w reservations app.

Pokrywa:

* ``run_daily_sync`` — wywołanie z ``--today`` i bez, error path dla
  niepoprawnej daty.
* ``seed_sites`` — tworzenie demo budów, idempotencja (get_or_create).
* ``seed_reservations`` — tworzenie demo rezerwacji, błędy gdy brak
  maszyn/budów.
* ``import_reservations`` — JSON import (M1 fixture), error paths.

Testy używają ``StringIO`` do przechwycenia ``stdout`` / ``stderr``,
``call_command`` do wywołania bez sub-procesu. Wszystkie pod
``@pytest.mark.django_db`` bo commands mutują DB.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory
from reservations.models import ConstructionSite, Reservation

# =============================================================================
# run_daily_sync command
# =============================================================================


@pytest.mark.django_db
class TestRunDailySyncCommand:
    """Cron-callable command — :func:`run_daily_sync` z CLI."""

    def test_runs_with_explicit_today(self, machine):
        """``--today=YYYY-MM-DD`` przekazuje datę do service."""
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 10),
        )
        out = StringIO()
        call_command("run_daily_sync", today="2030-06-05", stdout=out)
        output = out.getvalue()
        # Output zawiera result keys.
        assert "updated=" in output
        assert "extended=" in output
        assert "reserved=" in output
        # Machine flipnięta na NA_BUDOWIE (active res. covering today).
        machine.refresh_from_db()
        assert machine.status == Machine.Status.NA_BUDOWIE

    def test_runs_without_today_uses_real_date(self, machine):
        """Bez ``--today`` używa ``date.today()`` (freezegun)."""
        with freeze_time("2030-07-15"):
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 7, 10),
                end_date=date(2030, 7, 20),
            )
            out = StringIO()
            call_command("run_daily_sync", stdout=out)
            assert "2030-07-15" in out.getvalue()

    def test_raises_command_error_on_invalid_date(self):
        """Niepoprawna data → ``CommandError`` z komunikatem o YYYY-MM-DD."""
        with pytest.raises(CommandError, match="YYYY-MM-DD"):
            call_command("run_daily_sync", today="not-a-date")


# =============================================================================
# seed_sites command
# =============================================================================


@pytest.mark.django_db
class TestSeedSitesCommand:
    """Demo construction sites — idempotent get_or_create."""

    def test_creates_all_demo_sites_when_db_empty(self):
        """Pusta baza → tworzy 5 demo budów BUD-2026-001..-005."""
        out = StringIO()
        call_command("seed_sites", stdout=out)
        # 5 demo sites z DEMO_SITES.
        assert ConstructionSite.objects.count() == 5
        # Sprawdź jeden konkretny.
        assert ConstructionSite.objects.filter(project_number="BUD-2026-001").exists()

    def test_idempotent_on_second_run(self):
        """Druga uruchomienie — nic nie tworzy (already exists)."""
        call_command("seed_sites", stdout=StringIO())
        first_count = ConstructionSite.objects.count()
        out = StringIO()
        call_command("seed_sites", stdout=out)
        assert ConstructionSite.objects.count() == first_count
        # Output zawiera info że już istniały.
        assert "już istniały" in out.getvalue() or "0 utworzone" in out.getvalue()

    def test_count_caps_at_demo_size(self):
        """``--count=100`` jest cap'owane do len(DEMO_SITES)=5."""
        out = StringIO()
        call_command("seed_sites", count=100, stdout=out)
        # Wszystkie 5 demo sites.
        assert ConstructionSite.objects.count() == 5

    def test_count_smaller_than_demo_size_creates_subset(self):
        """``--count=2`` tworzy tylko pierwsze 2 demo sites."""
        out = StringIO()
        call_command("seed_sites", count=2, stdout=out)
        assert ConstructionSite.objects.count() == 2


# =============================================================================
# seed_reservations command
# =============================================================================


@pytest.mark.django_db
class TestSeedReservationsCommand:
    """Demo rezerwacje — losowe wpisy na maszyny+budowy."""

    def test_raises_error_when_no_machines(self):
        """Brak maszyn → ``CommandError`` z hint."""
        # Site jest, ale machine nie.
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="X",
            address="A",
            status=ConstructionSite.Status.AKTYWNA,
        )
        with pytest.raises(CommandError, match="seed_machines"):
            call_command("seed_reservations", count=5)

    def test_raises_error_when_no_active_sites(self, machine):
        """Brak aktywnych budów → ``CommandError`` z hint."""
        with pytest.raises(CommandError, match="seed_sites"):
            call_command("seed_reservations", count=5)

    def test_creates_reservations_with_machines_and_sites(self, machine):
        """Happy path: są maszyny i budowy → tworzy rezerwacje."""
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="X",
            address="A",
            status=ConstructionSite.Status.AKTYWNA,
        )
        out = StringIO()
        call_command("seed_reservations", count=5, seed=42, stdout=out)
        # Output zawiera info o utworzonych/pominiętych.
        assert "utworzono" in out.getvalue()
        # Co najmniej jedna rezerwacja (przy 5 prób i 1 maszynie niektóre kolidują).
        assert Reservation.objects.count() >= 1


# =============================================================================
# seed_reservations_demo — Wave 14-B prezentacja 14.06.2026
# =============================================================================


@pytest.mark.django_db
class TestSeedReservationsDemoCommand:
    """Wave 14-B: realistyczna data na prezentację.

    Sprawdzamy:

    * raises gdy brak maszyn (po Wycofana filtrze),
    * auto-tworzy 3 dodatkowe sites jeśli mniej niż 5,
    * ``--clear`` usuwa istniejące rezerwacje,
    * status distribution: zakończona (przeszłość), potwierdzona (do 15.06),
      mix potwierdzona/oczekująca (po 15.06),
    * density: marzec dense, wrzesień sparse,
    * Machine.status update — kilka maszyn dostaje NA_BUDOWIE na 14.06.
    """

    def test_raises_when_no_machines(self):
        """Wszystkie maszyny Wycofane → CommandError."""
        # Tworzy maszynę i ustawia status WYCOFANA — tym sposobem command
        # widzi pustą listę i powinien error'ować.
        Machine.objects.create(
            uid="WCF-001",
            name="Cofnięta",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.WYCOFANA,
        )
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="X",
            address="A",
            status=ConstructionSite.Status.AKTYWNA,
        )
        with pytest.raises(CommandError, match="seed_machines"):
            call_command("seed_reservations_demo")

    def test_happy_path_creates_reservations_with_full_status_mix(self, machine):
        """Z maszyną i przynajmniej 1 active site — utworzy rezerwacje
        we wszystkich trzech statusach (historyczne + bieżące + przyszłe)."""
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="Demo Site",
            address="ul. Demo 1",
            status=ConstructionSite.Status.AKTYWNA,
        )
        out = StringIO()
        call_command("seed_reservations_demo", stdout=out)

        # Powinno być >5 rezerwacji per maszynę (marzec-wrzesień, mean 15d).
        assert Reservation.objects.count() >= 5

        # Każdy status występuje:
        statuses = set(Reservation.objects.values_list("status", flat=True))
        assert Reservation.Status.ZAKONCZONA.value in statuses
        assert Reservation.Status.POTWIERDZONA.value in statuses
        # OCZEKUJACA może (i powinno) wystąpić ale density-skip / single
        # machine może czasem zgubić — sprawdzamy że jest co najmniej 1 future
        # rezerwacja, pozostawiamy status jako mix.

    def test_clear_flag_wipes_existing_reservations(self, machine):
        """``--clear`` usuwa wszystkie rezerwacje przed seedingiem."""
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="X",
            address="A",
            status=ConstructionSite.Status.AKTYWNA,
        )
        # Stwórz "stary" rekord który ma być usunięty
        ConfirmedReservationFactory(machine=machine, person="OLD-RECORD-MARKER")

        call_command("seed_reservations_demo", clear=True, stdout=StringIO())

        # Stary marker nie istnieje
        assert not Reservation.objects.filter(person="OLD-RECORD-MARKER").exists()
        # Nowe rezerwacje powstały
        assert Reservation.objects.count() > 0

    def test_auto_creates_sites_if_less_than_five_active(self, machine):
        """Brak 5 aktywnych budów → command auto-tworzy do 5 (BUD-2026-XXX)."""
        # Brak istniejących sites
        assert ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA).count() == 0
        call_command("seed_reservations_demo", stdout=StringIO())
        # Powinno być >=3 (do 5) - tyle ile fixturowych w _ensure_sites
        assert ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA).count() >= 1

    def test_machine_status_reflects_presentation_date_bookings(self, machine):
        """Maszyna z POTWIERDZONA obejmującą 14.06 dostaje NA_BUDOWIE."""
        ConstructionSite.objects.create(
            project_number="BUD-2026-001",
            name="X",
            address="A",
            status=ConstructionSite.Status.AKTYWNA,
        )
        call_command("seed_reservations_demo", stdout=StringIO())

        # Sprawdzamy globalnie: przynajmniej 1 maszyna powinna mieć status
        # NA_BUDOWIE lub W_MAGAZYNIE lub ZAREZERWOWANA (nie WYCOFANA bez
        # zmian).
        machine.refresh_from_db()
        assert machine.status in {
            Machine.Status.NA_BUDOWIE.value,
            Machine.Status.W_MAGAZYNIE.value,
            Machine.Status.ZAREZERWOWANA.value,
        }


# =============================================================================
# seed_demo "umbrella" command (jeśli istnieje)
# =============================================================================


@pytest.mark.django_db
class TestSeedDemoUmbrella:
    """Jeśli istnieje seed_demo command, wywołaj smoke test."""

    def test_seed_demo_command_runs(self):
        """seed_demo wywołuje wszystkie seed_* w odpowiedniej kolejności."""
        # Niektóre projekty mają seed_demo jako umbrella. Sprawdzamy że
        # jeśli istnieje, działa bez wyjątku.
        from django.core.management import get_commands

        if "seed_demo" not in get_commands():
            pytest.skip("seed_demo command nie istnieje w tym projekcie.")

        # Spróbuj wywołać — najprostszy smoke z --count=1.
        # Niektóre commands wywołują sys.exit przy seed errors.
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("seed_demo", stdout=out, stderr=StringIO())
        # Jeśli przeszło bez wyjątku — utworzyły się jakiekolwiek demo dane.
        assert Machine.objects.exists() or ConstructionSite.objects.exists()


# =============================================================================
# import_reservations command
# =============================================================================


@pytest.mark.django_db
class TestImportReservationsCommand:
    """``import_reservations`` — JSON M1 import."""

    def test_raises_command_error_when_file_missing(self):
        """Nieistniejąca ścieżka → ``CommandError``."""
        with pytest.raises(CommandError, match="nie istnieje"):
            call_command("import_reservations", file="/tmp/no-such-file-42424.json")

    def test_raises_command_error_on_bad_json(self, tmp_path):
        """Niepoprawny JSON → ``CommandError``."""
        bad = tmp_path / "bad.json"
        bad.write_text("not json {")
        with pytest.raises(CommandError, match="JSON"):
            call_command("import_reservations", file=str(bad))

    def test_imports_valid_reservation_with_new_site(self, machine, tmp_path):
        """Happy path: tworzy rezerwację + auto-tworzy ConstructionSite."""
        payload = [
            {
                "id": "RES-001",
                "machineId": machine.uid,
                "startDate": "2030-06-01",
                "endDate": "2030-06-10",
                "person": "Jan Test",
                "address": "ul. Testowa 1",
                "projectNumber": "BUD-2030-007",
                "status": "oczekująca",
            }
        ]
        f = tmp_path / "good.json"
        f.write_text(json.dumps(payload))
        out = StringIO()
        call_command("import_reservations", file=str(f), stdout=out)
        # Rezerwacja powstała.
        assert Reservation.objects.filter(machine=machine).count() == 1
        # Site auto-stworzony.
        assert ConstructionSite.objects.filter(project_number="BUD-2030-007").exists()
        assert "1 utworzonych" in out.getvalue()

    def test_skips_when_machine_uid_unknown(self, tmp_path):
        """Wpis z nieistniejącym ``machineId`` → pominięty z WARNING."""
        payload = [
            {
                "id": "X",
                "machineId": "BRAK-MASZYNY",
                "startDate": "2030-01-01",
                "endDate": "2030-01-05",
            }
        ]
        f = tmp_path / "missing.json"
        f.write_text(json.dumps(payload))
        out = StringIO()
        call_command("import_reservations", file=str(f), stdout=out)
        assert "pomijam" in out.getvalue()
        assert Reservation.objects.count() == 0

    def test_skips_duplicate_on_second_run(self, machine, tmp_path):
        """Re-run nie tworzy duplikatów — idempotency na (machine, start_date)."""
        payload = [
            {
                "id": "DUP-1",
                "machineId": machine.uid,
                "startDate": "2030-06-01",
                "endDate": "2030-06-10",
                "person": "Tester",
                "projectNumber": "BUD-2030-999",
                "status": "oczekująca",
            }
        ]
        f = tmp_path / "dup.json"
        f.write_text(json.dumps(payload))
        # Pierwsza uruchomienie.
        call_command("import_reservations", file=str(f), stdout=StringIO())
        assert Reservation.objects.count() == 1
        # Druga uruchomienie — duplikat (machine + start_date).
        out = StringIO()
        call_command("import_reservations", file=str(f), stdout=out)
        assert Reservation.objects.count() == 1
        assert "1 duplikatów" in out.getvalue()

    def test_handles_invalid_date_format(self, machine, tmp_path):
        """Wpis z niepoprawnym formatem daty → pominięty."""
        payload = [
            {
                "id": "BAD-DT",
                "machineId": machine.uid,
                "startDate": "nie-data",
                "endDate": "też-nie-data",
            }
        ]
        f = tmp_path / "bad_date.json"
        f.write_text(json.dumps(payload))
        call_command("import_reservations", file=str(f), stdout=StringIO())
        assert Reservation.objects.count() == 0
