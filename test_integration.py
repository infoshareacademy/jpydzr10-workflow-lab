"""Testy integracyjne: pełne scenariusze biznesowe end-to-end."""

import json
import os
from datetime import date, timedelta

import pytest

from datastore import DataStore
from logic import has_conflict, run_daily_sync
from models import Machine, Reservation, ServiceRecord
from utils import generate_unique_id, parse_date


def _date_str(offset=0):
    return (date.today() + timedelta(days=offset)).strftime("%Y-%m-%d")


# =============================================================================
# Scenariusze biznesowe end-to-end
# =============================================================================


class TestFullReservationLifecycle:
    """Pełny cykl życia rezerwacji: utworzenie → sync → zwrot."""

    def test_create_confirm_return(self):
        """Maszyna: magazyn → zarezerwowana → na budowie → zwrot do magazynu."""
        m = Machine("M001", "Koparka", "koparka")
        assert m.status == "W magazynie"

        # Rezerwacja w przyszłości
        r = Reservation(
            "RES-001", "M001", _date_str(5), _date_str(15),
            "Jan", "BUD-001", "Warszawa", "potwierdzona",
        )

        # Sync — maszyna powinna być Zarezerwowana
        run_daily_sync([m], [r])
        assert m.status == "Zarezerwowana"

        # Symulacja: przesuwamy rezerwację na "teraz"
        r.start_date = _date_str(-2)
        r.end_date = _date_str(5)
        m.status = "W magazynie"  # reset
        run_daily_sync([m], [r])
        assert m.status == "Na budowie"

        # Zwrot
        r.status = "zakończona"
        m.status = "W magazynie"
        m.location = "Magazyn"
        assert m.status == "W magazynie"
        assert m.location == "Magazyn"

    def test_multiple_reservations_same_machine(self):
        """Kilka rezerwacji pod rząd na tę samą maszynę."""
        m = Machine("M001", "Koparka", "koparka")

        r1 = Reservation(
            "RES-001", "M001", _date_str(-20), _date_str(-10),
            "Jan", "BUD-001", status="zakończona",
        )
        r2 = Reservation(
            "RES-002", "M001", _date_str(-2), _date_str(5),
            "Anna", "BUD-002", "Kraków", "potwierdzona",
        )
        r3 = Reservation(
            "RES-003", "M001", _date_str(10), _date_str(20),
            "Piotr", "BUD-003", status="potwierdzona",
        )

        run_daily_sync([m], [r1, r2, r3])

        # Aktywna rezerwacja wygrywa
        assert m.status == "Na budowie"
        assert m.location == "Kraków"

    def test_overdue_hard_return_policy(self):
        """Maszyna nie wróciła — end_date przedłużony do dziś."""
        m = Machine("M001", "Koparka", "koparka", status="Na budowie")
        r = Reservation(
            "RES-001", "M001", _date_str(-30), _date_str(-5),
            "Jan", "BUD-001", status="potwierdzona",
        )

        result = run_daily_sync([m], [r])
        assert r.end_date == _date_str(0)
        assert result["extended"] == 1

    def test_service_blocks_reservation_sync(self):
        """Maszyna w serwisie — sync nie zmienia jej statusu."""
        m = Machine("M001", "Koparka", "koparka", status="W serwisie")
        r = Reservation(
            "RES-001", "M001", _date_str(-2), _date_str(5),
            "Jan", "BUD-001", "Warszawa", "potwierdzona",
        )

        run_daily_sync([m], [r])
        assert m.status == "W serwisie"


class TestConflictDetection:
    """Zaawansowane testy wykrywania konfliktów."""

    def test_no_conflict_with_cancelled(self):
        """Anulowana rezerwacja nie blokuje terminu."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="anulowana",
        )
        assert not has_conflict([r], "M001", _date_str(0), _date_str(10))

    def test_no_conflict_with_completed(self):
        """Zakończona rezerwacja nie blokuje terminu."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="zakończona",
        )
        assert not has_conflict([r], "M001", _date_str(0), _date_str(10))

    def test_conflict_one_day_overlap(self):
        """Nakładanie się o jeden dzień — IS konflikt."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="potwierdzona",
        )
        assert has_conflict([r], "M001", _date_str(10), _date_str(20))

    def test_conflict_contained_inside(self):
        """Nowa rezerwacja całkowicie zawiera się w istniejącej."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(20),
            "Jan", "BUD-001", status="potwierdzona",
        )
        assert has_conflict([r], "M001", _date_str(5), _date_str(15))

    def test_conflict_wraps_around(self):
        """Nowa rezerwacja obejmuje całą istniejącą."""
        r = Reservation(
            "RES-001", "M001", _date_str(5), _date_str(10),
            "Jan", "BUD-001", status="potwierdzona",
        )
        assert has_conflict([r], "M001", _date_str(0), _date_str(20))

    def test_no_conflict_different_machines(self):
        """Różne maszyny — brak konfliktu nawet przy tych samych datach."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="potwierdzona",
        )
        assert not has_conflict([r], "M002", _date_str(0), _date_str(10))

    def test_exclude_self_during_edit(self):
        """Edycja rezerwacji — nie koliduje sama ze sobą."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="potwierdzona",
        )
        assert not has_conflict(
            [r], "M001", _date_str(0), _date_str(15),
            exclude_id="RES-001",
        )

    def test_multiple_reservations_complex(self):
        """Wiele rezerwacji — konflikt z jedną, nie z drugą."""
        r1 = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(5),
            "Jan", "BUD-001", status="potwierdzona",
        )
        r2 = Reservation(
            "RES-002", "M001", _date_str(10), _date_str(15),
            "Anna", "BUD-002", status="potwierdzona",
        )
        # Między rezerwacjami — brak konfliktu
        assert not has_conflict([r1, r2], "M001", _date_str(6), _date_str(9))
        # Nakłada się z drugą
        assert has_conflict([r1, r2], "M001", _date_str(8), _date_str(12))

    def test_waiting_reservation_also_blocks(self):
        """Rezerwacja oczekująca też blokuje termin."""
        r = Reservation(
            "RES-001", "M001", _date_str(0), _date_str(10),
            "Jan", "BUD-001", status="oczekująca",
        )
        assert has_conflict([r], "M001", _date_str(5), _date_str(15))


# =============================================================================
# Persystencja end-to-end
# =============================================================================


class TestPersistenceRoundTrip:
    """Zapis → odczyt → porównanie dla wszystkich modeli."""

    @pytest.fixture
    def store(self, tmp_path):
        return DataStore(data_dir=str(tmp_path))

    def test_machines_full_roundtrip(self, store):
        """Maszyna z wszystkimi polami przeżywa zapis/odczyt."""
        m = Machine(
            "KOP-001", "Koparka CAT 320", "Koparka gąsienicowa",
            model="320 GC", capacity=22000,
            inspection_date="2026-06-15", location="Magazyn",
            status="W magazynie", manufacturer="Caterpillar",
            serial_number="CAT123", build_year=2019,
            notes="Uwaga testowa",
        )
        store.save_machines([m])
        loaded = store.load_machines()

        assert len(loaded) == 1
        lm = loaded[0]
        assert lm.uid == "KOP-001"
        assert lm.manufacturer == "Caterpillar"
        assert lm.serial_number == "CAT123"
        assert lm.build_year == 2019
        assert lm.notes == "Uwaga testowa"
        assert lm.capacity == 22000
        assert lm.inspection_date == "2026-06-15"

    def test_reservations_roundtrip(self, store):
        reservations = [
            Reservation(
                "RES-001", "M001", "2026-04-01", "2026-04-15",
                "Jan Kowalski", "BUD-2026-001",
                "Warszawa ul. Testowa 1", "potwierdzona",
            ),
            Reservation(
                "RES-002", "M002", "2026-05-01", "2026-05-30",
                "Anna Nowak", "BUD-2026-002",
                status="oczekująca",
            ),
        ]
        store.save_reservations(reservations)
        loaded = store.load_reservations()

        assert len(loaded) == 2
        assert loaded[0].person == "Jan Kowalski"
        assert loaded[0].address == "Warszawa ul. Testowa 1"
        assert loaded[1].status == "oczekująca"

    def test_service_records_roundtrip(self, store):
        records = [
            ServiceRecord(
                "SRV-001", "M001", "2026-01-15", "przegląd",
                "Przegląd roczny UDT", 500.0, "2027-01-15",
            ),
            ServiceRecord(
                "SRV-002", "M001", "2026-03-10", "naprawa",
                "Wymiana filtra hydraulicznego", 2350.50,
            ),
        ]
        store.save_service_records(records)
        loaded = store.load_service_records()

        assert len(loaded) == 2
        assert loaded[0].record_type == "przegląd"
        assert loaded[0].next_inspection == "2027-01-15"
        assert loaded[1].cost == 2350.50

    def test_20_machines_roundtrip(self, store):
        """20 maszyn z różnymi statusami przeżywa roundtrip."""
        machines = []
        statuses = list(Machine.VALID_STATUSES)
        for i in range(20):
            machines.append(Machine(
                f"M{i:03d}", f"Maszyna {i}", "testowa",
                status=statuses[i % len(statuses)],
                manufacturer=f"Producent {i}",
                build_year=2010 + i,
            ))
        store.save_machines(machines)
        loaded = store.load_machines()
        assert len(loaded) == 20
        for i, m in enumerate(loaded):
            assert m.uid == f"M{i:03d}"
            assert m.build_year == 2010 + i

    def test_empty_collections_roundtrip(self, store):
        """Puste kolekcje poprawnie się zapisują i wczytują."""
        store.save_machines([])
        store.save_reservations([])
        store.save_service_records([])

        assert store.load_machines() == []
        assert store.load_reservations() == []
        assert store.load_service_records() == []


# =============================================================================
# Walidacja modeli — edge cases
# =============================================================================


class TestMachineValidation:
    def test_all_statuses_accepted(self):
        for status in Machine.VALID_STATUSES:
            m = Machine("M001", "Test", "test", status=status)
            assert m.status == status

    def test_status_change_chain(self):
        """Maszyna przechodzi przez wszystkie statusy."""
        m = Machine("M001", "Test", "test")
        m.status = "Zarezerwowana"
        m.status = "Na budowie"
        m.status = "W serwisie"
        m.status = "W magazynie"
        assert m.status == "W magazynie"

    def test_capacity_zero_allowed(self):
        m = Machine("M001", "Test", "test", capacity=0)
        assert m.capacity == 0

    def test_large_capacity(self):
        m = Machine("M001", "Test", "test", capacity=100000)
        assert m.capacity == 100000

    def test_unicode_in_name(self):
        m = Machine("M001", "Żuraw gąsienicowy ŁÓDŹ", "żuraw")
        assert "Żuraw" in m.name
        assert "ŁÓDŹ" in m.name

    def test_from_dict_with_extra_fields(self):
        """from_dict ignoruje nieznane pola bez błędu."""
        d = {
            "uid": "M001", "name": "Test", "type": "test",
            "unknownField": "ignored", "anotherOne": 42,
            "status": "W magazynie",
        }
        m = Machine.from_dict(d)
        assert m.uid == "M001"

    def test_from_dict_minimal(self):
        """from_dict z samym UID (reszta domyślna)."""
        m = Machine.from_dict({"uid": "M001"})
        assert m.uid == "M001"
        assert m.name == ""
        assert m.status == "W magazynie"
        assert m.manufacturer == ""
        assert m.build_year == 0

    def test_str_format(self):
        m = Machine(
            "KOP-001", "Koparka CAT", "koparka",
            location="Magazyn", status="W magazynie",
        )
        s = str(m)
        assert "KOP-001" in s
        assert "Koparka CAT" in s
        assert "W magazynie" in s

    def test_notes_preserved(self):
        m = Machine("M001", "Test", "test", notes="Ważna uwaga!")
        d = m.to_dict()
        m2 = Machine.from_dict(d)
        assert m2.notes == "Ważna uwaga!"


class TestReservationValidation:
    def test_title_property(self):
        r = Reservation(
            "RES-001", "M001", "2026-01-01", "2026-01-10",
            "Jan Kowalski", "BUD-2026-001",
        )
        assert r.title == "BUD-2026-001 / Jan Kowalski"

    def test_status_transitions(self):
        """Rezerwacja może przechodzić między statusami."""
        r = Reservation(
            "RES-001", "M001", "2026-01-01", "2026-01-10",
            "Jan", "BUD-001",
        )
        assert r.status == "oczekująca"
        r.status = "potwierdzona"
        r.status = "zakończona"
        assert r.status == "zakończona"

    def test_all_reservation_statuses(self):
        for status in Reservation.VALID_STATUSES:
            r = Reservation(
                "RES-001", "M001", "2026-01-01", "2026-01-10",
                "Jan", "BUD-001", status=status,
            )
            assert r.status == status

    def test_date_range_same_day_valid(self):
        assert Reservation.validate_date_range("2026-06-15", "2026-06-15")

    def test_date_range_reversed_invalid(self):
        assert not Reservation.validate_date_range("2026-06-20", "2026-06-15")

    def test_long_address(self):
        addr = "Warszawa, ul. Bardzo Długa Nazwa Ulicy 123/45, budynek C, piętro 3"
        r = Reservation(
            "RES-001", "M001", "2026-01-01", "2026-01-10",
            "Jan", "BUD-001", address=addr,
        )
        d = r.to_dict()
        r2 = Reservation.from_dict(d)
        assert r2.address == addr


class TestServiceRecordValidation:
    def test_both_types_accepted(self):
        s1 = ServiceRecord("SRV-001", "M001", "2026-01-01", "przegląd")
        s2 = ServiceRecord("SRV-002", "M001", "2026-01-01", "naprawa")
        assert s1.record_type == "przegląd"
        assert s2.record_type == "naprawa"

    def test_zero_cost(self):
        s = ServiceRecord(
            "SRV-001", "M001", "2026-01-01", "przegląd", cost=0.0,
        )
        assert s.cost == 0.0

    def test_high_cost(self):
        s = ServiceRecord(
            "SRV-001", "M001", "2026-01-01", "naprawa",
            "Generalna naprawa silnika", 45000.00,
        )
        assert s.cost == 45000.00

    def test_next_inspection_calculation(self):
        # 6 miesięcy = 180 dni od 2026-01-01
        result = ServiceRecord.calculate_next_inspection("2026-01-01", 6)
        expected = (date(2026, 1, 1) + timedelta(days=180)).strftime("%Y-%m-%d")
        assert result == expected

    def test_next_inspection_1_month(self):
        result = ServiceRecord.calculate_next_inspection("2026-06-15", 1)
        expected = (date(2026, 6, 15) + timedelta(days=30)).strftime("%Y-%m-%d")
        assert result == expected

    def test_next_inspection_12_months(self):
        result = ServiceRecord.calculate_next_inspection("2026-01-01", 12)
        expected = (date(2026, 1, 1) + timedelta(days=360)).strftime("%Y-%m-%d")
        assert result == expected

    def test_str_with_cost(self):
        s = ServiceRecord(
            "SRV-001", "M001", "2026-03-15", "naprawa",
            "Wymiana filtra", 1500.0,
        )
        text = str(s)
        assert "1500.00 PLN" in text
        assert "Wymiana filtra" in text

    def test_str_without_cost(self):
        s = ServiceRecord(
            "SRV-001", "M001", "2026-03-15", "przegląd",
            "Przegląd roczny",
        )
        text = str(s)
        assert "---" in text


# =============================================================================
# Testy inspection_status z datami granicznymi
# =============================================================================


class TestInspectionStatusBoundary:
    def test_exactly_14_days(self):
        d = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(d) == "warning"

    def test_exactly_15_days(self):
        d = (date.today() + timedelta(days=15)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(d) == "ok"

    def test_today(self):
        d = date.today().strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(d) == "warning"

    def test_yesterday(self):
        d = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(d) == "overdue"

    def test_tomorrow(self):
        d = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(d) == "warning"

    def test_far_future(self):
        assert Machine.check_inspection_status("2099-12-31") == "ok"

    def test_invalid_date_string(self):
        assert Machine.check_inspection_status("nie-data") == "overdue"

    def test_partial_date(self):
        assert Machine.check_inspection_status("2026-13-01") == "overdue"


# =============================================================================
# Testy generate_unique_id
# =============================================================================


class TestIdGeneration:
    def test_1000_unique_ids(self):
        ids = set()
        existing = set()
        for _ in range(1000):
            new_id = generate_unique_id("TST-", existing)
            assert new_id not in ids
            ids.add(new_id)
            existing.add(new_id)
        assert len(ids) == 1000

    def test_different_prefixes(self):
        id1 = generate_unique_id("RES-", set())
        id2 = generate_unique_id("SRV-", set())
        assert id1.startswith("RES-")
        assert id2.startswith("SRV-")
        assert id1 != id2


# =============================================================================
# Testy sync z wieloma maszynami
# =============================================================================


class TestSyncMultipleMachines:
    def test_sync_10_machines_mixed(self):
        """10 maszyn z różnymi scenariuszami — sync nie crashuje."""
        machines = [
            Machine(f"M{i:03d}", f"Maszyna {i}", "test",
                    status=s)
            for i, s in enumerate([
                "W magazynie", "Na budowie", "Zarezerwowana",
                "W serwisie", "W magazynie", "W magazynie",
                "Na budowie", "W magazynie", "W magazynie",
                "W serwisie",
            ])
        ]

        reservations = [
            # M000: przyszła rezerwacja
            Reservation(
                "R1", "M000", _date_str(5), _date_str(15),
                "Jan", "B1", status="potwierdzona",
            ),
            # M001: aktywna (już Na budowie)
            Reservation(
                "R2", "M001", _date_str(-3), _date_str(5),
                "Anna", "B2", "Kraków", "potwierdzona",
            ),
            # M004: przeszła zakończona
            Reservation(
                "R3", "M004", _date_str(-20), _date_str(-10),
                "Piotr", "B3", status="zakończona",
            ),
            # M006: przeterminowana (Na budowie, end < dziś)
            Reservation(
                "R4", "M006", _date_str(-15), _date_str(-3),
                "Ewa", "B4", status="potwierdzona",
            ),
        ]

        result = run_daily_sync(machines, reservations)

        # M000 powinna być Zarezerwowana
        assert machines[0].status == "Zarezerwowana"
        # M001 już była Na budowie — bez zmian
        assert machines[1].status == "Na budowie"
        # M003 w serwisie — nietknięta
        assert machines[3].status == "W serwisie"
        # M006 Na budowie + przeterminowana → end_date przedłużony
        assert machines[6].status == "Na budowie"

    def test_sync_no_reservations(self):
        """Sync bez rezerwacji — nic się nie zmienia."""
        machines = [Machine("M001", "Test", "test")]
        result = run_daily_sync(machines, [])
        assert result == {"updated": 0, "extended": 0, "reserved": 0}
        assert machines[0].status == "W magazynie"

    def test_sync_no_machines(self):
        """Sync bez maszyn — nic się nie zmienia."""
        r = Reservation(
            "R1", "M999", _date_str(0), _date_str(5),
            "Jan", "B1", status="potwierdzona",
        )
        result = run_daily_sync([], [r])
        assert result == {"updated": 0, "extended": 0, "reserved": 0}


# =============================================================================
# Import edge cases
# =============================================================================


class TestImportEdgeCases:
    @pytest.fixture
    def store(self, tmp_path):
        return DataStore(data_dir=str(tmp_path))

    def test_import_preserves_existing_on_no_overlap(self, store, tmp_path):
        """Import nowych maszyn nie usuwa istniejących."""
        store.save_machines([
            Machine("OLD-001", "Stara", "stara"),
        ])

        source = [
            {"uid": "NEW-001", "name": "Nowa", "type": "nowa",
             "status": "W magazynie"},
        ]
        path = str(tmp_path / "new.json")
        with open(path, "w") as f:
            json.dump(source, f)

        store.import_machines(path)
        loaded = store.load_machines()
        uids = {m.uid for m in loaded}
        assert "OLD-001" in uids
        assert "NEW-001" in uids
        assert len(loaded) == 2

    def test_import_updates_existing(self, store, tmp_path):
        """Import z tym samym UID nadpisuje dane."""
        store.save_machines([
            Machine("M001", "Stara nazwa", "stara"),
        ])

        source = [
            {"uid": "M001", "name": "Nowa nazwa", "type": "nowa",
             "status": "W magazynie"},
        ]
        path = str(tmp_path / "update.json")
        with open(path, "w") as f:
            json.dump(source, f)

        store.import_machines(path)
        loaded = store.load_machines()
        assert len(loaded) == 1
        assert loaded[0].name == "Nowa nazwa"

    def test_import_empty_list(self, store, tmp_path):
        """Import pustej listy — nic się nie zmienia."""
        store.save_machines([Machine("M001", "Test", "test")])

        path = str(tmp_path / "empty.json")
        with open(path, "w") as f:
            json.dump([], f)

        result = store.import_machines(path)
        assert result["imported"] == 0
        loaded = store.load_machines()
        assert len(loaded) == 1

    def test_import_with_new_fields(self, store, tmp_path):
        """Import z nowymi polami (manufacturer, serialNumber itd.)."""
        source = [{
            "uid": "M001", "name": "Koparka CAT", "type": "koparka",
            "status": "W magazynie", "manufacturer": "Caterpillar",
            "serialNumber": "CAT123", "buildYear": 2020,
            "notes": "Testowa",
        }]
        path = str(tmp_path / "full.json")
        with open(path, "w") as f:
            json.dump(source, f)

        store.import_machines(path)
        loaded = store.load_machines()
        assert loaded[0].manufacturer == "Caterpillar"
        assert loaded[0].serial_number == "CAT123"
        assert loaded[0].build_year == 2020


# =============================================================================
# Testy znalezione przez agentów code review (luki w pokryciu)
# =============================================================================


class TestSyncEmptyDates:
    """Testy guard'ów na puste daty w sync i conflict."""

    def test_conflict_skips_reservation_with_empty_dates(self):
        """Rezerwacja z pustymi datami nie crashuje conflict check."""
        r = Reservation(
            "RES-001", "M001", "", "",
            "Jan", "B1", status="potwierdzona",
        )
        assert not has_conflict([r], "M001", _date_str(0), _date_str(5))

    def test_sync_skips_reservation_with_empty_start(self):
        """Sync pomija rezerwacje z pustą datą startową."""
        m = Machine("M001", "Test", "test")
        r = Reservation(
            "RES-001", "M001", "", _date_str(5),
            "Jan", "B1", status="potwierdzona",
        )
        result = run_daily_sync([m], [r])
        assert m.status == "W magazynie"
        assert result["updated"] == 0

    def test_sync_skips_reservation_with_empty_end(self):
        """Sync pomija rezerwacje z pustą datą końcową."""
        m = Machine("M001", "Test", "test")
        r = Reservation(
            "RES-001", "M001", _date_str(-2), "",
            "Jan", "B1", status="potwierdzona",
        )
        result = run_daily_sync([m], [r])
        assert m.status == "W magazynie"


class TestSyncZarezerwowanaExpired:
    """Testy naprawionego buga: Zarezerwowana → W magazynie po wygaśnięciu."""

    def test_expired_zarezerwowana_returns_to_magazyn(self):
        """Maszyna 'Zarezerwowana' z przeterminowaną rezerwacją wraca do magazynu."""
        m = Machine("M001", "Test", "test", status="Zarezerwowana")
        r = Reservation(
            "RES-001", "M001", _date_str(-10), _date_str(-2),
            "Jan", "B1", status="potwierdzona",
        )
        result = run_daily_sync([m], [r])
        assert m.status == "W magazynie"
        assert result["updated"] == 1

    def test_expired_plus_future_order_independent(self):
        """Maszyna z przeterminowaną i przyszłą rez — wynik niezależny od kolejności."""
        m = Machine("M001", "Test", "test", status="W magazynie")
        # Przeterminowana
        r_exp = Reservation(
            "RES-OLD", "M001", _date_str(-20), _date_str(-5),
            "Jan", "B1", status="potwierdzona",
        )
        # Przyszła
        r_fut = Reservation(
            "RES-NEW", "M001", _date_str(10), _date_str(20),
            "Anna", "B2", status="potwierdzona",
        )
        # Test z kolejnością: przyszła przed przeterminowaną
        run_daily_sync([m], [r_fut, r_exp])
        assert m.status == "Zarezerwowana"

        # Reset i test z odwrotną kolejnością
        m.status = "W magazynie"
        run_daily_sync([m], [r_exp, r_fut])
        assert m.status == "Zarezerwowana"

    def test_active_zarezerwowana_goes_to_na_budowie(self):
        """Maszyna 'Zarezerwowana' z aktywną rezerwacją idzie na budowę."""
        m = Machine("M001", "Test", "test", status="Zarezerwowana")
        r = Reservation(
            "RES-001", "M001", _date_str(-2), _date_str(5),
            "Jan", "B1", "Warszawa", "potwierdzona",
        )
        result = run_daily_sync([m], [r])
        assert m.status == "Na budowie"
        assert m.location == "Warszawa"


class TestSyncLocationUpdate:
    """Test że sync ustawia lokalizację z adresu rezerwacji."""

    def test_sync_sets_location_from_reservation(self):
        m = Machine("M001", "Test", "test", location="Magazyn")
        r = Reservation(
            "RES-001", "M001", _date_str(-1), _date_str(5),
            "Jan", "B1", "Kraków, ul. Budowlana 3", "potwierdzona",
        )
        run_daily_sync([m], [r])
        assert m.location == "Kraków, ul. Budowlana 3"


class TestAtomicSave:
    """Test atomowego zapisu (.tmp → .bak → rename)."""

    @pytest.fixture
    def store(self, tmp_path):
        return DataStore(data_dir=str(tmp_path))

    def test_save_creates_bak_after_second_write(self, store):
        machines = [Machine("M001", "Test", "test")]
        store.save_machines(machines)
        store.save_machines(machines)
        bak = store.paths["machines"] + ".bak"
        assert os.path.exists(bak)

    def test_no_tmp_file_left_after_save(self, store):
        machines = [Machine("M001", "Test", "test")]
        store.save_machines(machines)
        tmp = store.paths["machines"] + ".tmp"
        assert not os.path.exists(tmp)
