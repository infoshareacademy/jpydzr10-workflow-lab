"""Testy walidujące spójność danych demo w data/."""

import os
from collections import Counter
from datetime import date

import pytest

from datastore import DataStore
from models import Machine, Reservation, ServiceRecord
from utils import parse_date


@pytest.fixture(scope="module")
def store():
    return DataStore()


@pytest.fixture(scope="module")
def machines(store):
    return store.load_machines()


@pytest.fixture(scope="module")
def reservations(store):
    return store.load_reservations()


@pytest.fixture(scope="module")
def service_records(store):
    return store.load_service_records()


# =============================================================================
# Testy obecności plików
# =============================================================================


class TestDataFilesExist:
    def test_machines_json_exists(self):
        assert os.path.exists("data/machines.json")

    def test_reservations_json_exists(self):
        assert os.path.exists("data/reservations.json")

    def test_service_records_json_exists(self):
        assert os.path.exists("data/service_records.json")

    def test_machines_db_json_exists(self):
        assert os.path.exists("machines_db.json")


# =============================================================================
# Testy maszyn demo
# =============================================================================


class TestDemoMachines:
    def test_count(self, machines):
        """Powinno być ~20 maszyn."""
        assert 15 <= len(machines) <= 25

    def test_unique_uids(self, machines):
        """Każda maszyna ma unikalny UID."""
        uids = [m.uid for m in machines]
        assert len(uids) == len(set(uids))

    def test_all_have_names(self, machines):
        for m in machines:
            assert m.name, f"Maszyna {m.uid} nie ma nazwy"

    def test_all_have_types(self, machines):
        for m in machines:
            assert m.machine_type, f"Maszyna {m.uid} nie ma typu"

    def test_all_have_valid_status(self, machines):
        for m in machines:
            assert m.status in Machine.VALID_STATUSES, (
                f"Maszyna {m.uid} ma nieprawidłowy status: {m.status}"
            )

    def test_status_distribution(self, machines):
        """Powinna być mieszanka statusów — nie wszystkie w magazynie."""
        statuses = Counter(m.status for m in machines)
        assert statuses["W magazynie"] >= 5, "Za mało maszyn w magazynie"
        assert statuses["Na budowie"] >= 2, "Za mało maszyn na budowie"

    def test_all_have_manufacturers(self, machines):
        for m in machines:
            assert m.manufacturer, (
                f"Maszyna {m.uid} nie ma producenta"
            )

    def test_all_have_build_year(self, machines):
        for m in machines:
            assert 2005 <= m.build_year <= 2026, (
                f"Maszyna {m.uid} ma nierealistyczny rok: {m.build_year}"
            )

    def test_all_have_serial_numbers(self, machines):
        for m in machines:
            assert m.serial_number, (
                f"Maszyna {m.uid} nie ma numeru seryjnego"
            )

    def test_inspection_dates_format(self, machines):
        """Daty przeglądów (jeśli są) muszą mieć poprawny format."""
        for m in machines:
            if m.inspection_date:
                try:
                    parse_date(m.inspection_date)
                except ValueError:
                    pytest.fail(
                        f"Maszyna {m.uid}: zły format daty "
                        f"przeglądu: {m.inspection_date}"
                    )

    def test_variety_of_types(self, machines):
        """Powinno być kilka różnych typów maszyn."""
        types = {m.machine_type for m in machines}
        assert len(types) >= 5, (
            f"Za mało typów maszyn: {types}"
        )

    def test_uid_prefix_convention(self, machines):
        """UID-y powinny mieć 3-literowy prefix + numer."""
        for m in machines:
            parts = m.uid.split("-")
            assert len(parts) == 2, (
                f"UID {m.uid} nie ma formatu XXX-NNN"
            )
            assert parts[0].isalpha(), (
                f"UID {m.uid} prefix nie jest literowy"
            )


# =============================================================================
# Testy rezerwacji demo
# =============================================================================


class TestDemoReservations:
    def test_count(self, reservations):
        """Powinno być kilkanaście-kilkadziesiąt rezerwacji."""
        assert len(reservations) >= 10

    def test_unique_ids(self, reservations):
        ids = [r.id for r in reservations]
        assert len(ids) == len(set(ids))

    def test_all_have_valid_status(self, reservations):
        for r in reservations:
            assert r.status in Reservation.VALID_STATUSES, (
                f"Rezerwacja {r.id} ma zły status: {r.status}"
            )

    def test_status_variety(self, reservations):
        """Powinny być rezerwacje o różnych statusach."""
        statuses = {r.status for r in reservations}
        assert "potwierdzona" in statuses
        assert "zakończona" in statuses

    def test_date_ranges_valid(self, reservations):
        """Data końca >= data początku."""
        for r in reservations:
            start = parse_date(r.start_date)
            end = parse_date(r.end_date)
            assert end >= start, (
                f"Rezerwacja {r.id}: end < start "
                f"({r.end_date} < {r.start_date})"
            )

    def test_all_have_person(self, reservations):
        for r in reservations:
            assert r.person, f"Rezerwacja {r.id} nie ma osoby"

    def test_all_have_project_number(self, reservations):
        for r in reservations:
            assert r.project_number, (
                f"Rezerwacja {r.id} nie ma numeru projektu"
            )

    def test_machine_ids_reference_existing(self, reservations, machines):
        """Każda rezerwacja odwołuje się do istniejącej maszyny."""
        machine_uids = {m.uid for m in machines}
        for r in reservations:
            assert r.machine_id in machine_uids, (
                f"Rezerwacja {r.id} odwołuje się do "
                f"nieistniejącej maszyny: {r.machine_id}"
            )

    def test_active_reservations_match_na_budowie(
        self, reservations, machines
    ):
        """Maszyny 'Na budowie' mają aktywną rezerwację."""
        today = date.today()
        na_budowie = {m.uid for m in machines if m.status == "Na budowie"}

        active_machines = set()
        for r in reservations:
            if r.status != "potwierdzona":
                continue
            start = parse_date(r.start_date)
            end = parse_date(r.end_date)
            if start <= today <= end:
                active_machines.add(r.machine_id)

        for uid in na_budowie:
            assert uid in active_machines, (
                f"Maszyna {uid} jest 'Na budowie' ale nie ma "
                f"aktywnej rezerwacji"
            )


# =============================================================================
# Testy serwisów demo
# =============================================================================


class TestDemoServiceRecords:
    def test_count(self, service_records):
        """Powinno być dużo wpisów serwisowych."""
        assert len(service_records) >= 100

    def test_unique_ids(self, service_records):
        ids = [s.id for s in service_records]
        assert len(ids) == len(set(ids))

    def test_all_have_valid_type(self, service_records):
        for s in service_records:
            assert s.record_type in ServiceRecord.VALID_TYPES, (
                f"Serwis {s.id} ma zły typ: {s.record_type}"
            )

    def test_both_types_present(self, service_records):
        types = {s.record_type for s in service_records}
        assert "przegląd" in types
        assert "naprawa" in types

    def test_dates_valid_format(self, service_records):
        for s in service_records:
            try:
                parse_date(s.record_date)
            except ValueError:
                pytest.fail(
                    f"Serwis {s.id}: zły format daty: {s.record_date}"
                )

    def test_costs_non_negative(self, service_records):
        for s in service_records:
            assert s.cost >= 0, (
                f"Serwis {s.id} ma ujemny koszt: {s.cost}"
            )

    def test_repairs_have_cost(self, service_records):
        """Większość napraw powinna mieć koszt > 0."""
        repairs = [s for s in service_records if s.record_type == "naprawa"]
        with_cost = [s for s in repairs if s.cost > 0]
        assert len(with_cost) >= len(repairs) * 0.8, (
            "Za mało napraw z kosztem > 0"
        )

    def test_machine_ids_reference_existing(
        self, service_records, machines
    ):
        """Każdy wpis serwisowy odwołuje się do istniejącej maszyny."""
        machine_uids = {m.uid for m in machines}
        for s in service_records:
            assert s.machine_id in machine_uids, (
                f"Serwis {s.id} odwołuje się do nieistniejącej "
                f"maszyny: {s.machine_id}"
            )

    def test_every_machine_has_service(self, service_records, machines):
        """Każda maszyna powinna mieć przynajmniej 1 wpis serwisowy."""
        serviced = {s.machine_id for s in service_records}
        for m in machines:
            assert m.uid in serviced, (
                f"Maszyna {m.uid} nie ma żadnego wpisu serwisowego"
            )

    def test_total_cost_realistic(self, service_records):
        """Łączny koszt powinien być realistyczny."""
        total = sum(s.cost for s in service_records)
        assert total > 10000, "Łączny koszt za niski"
        assert total < 5000000, "Łączny koszt nierealistycznie wysoki"

    def test_dates_span_multiple_years(self, service_records):
        """Wpisy powinny obejmować kilka lat."""
        years = {parse_date(s.record_date).year for s in service_records}
        assert len(years) >= 3, (
            f"Wpisy obejmują za mało lat: {sorted(years)}"
        )

    def test_inspections_have_next_inspection(self, service_records):
        """Przeglądy powinny mieć ustawiony następny przegląd."""
        inspections = [
            s for s in service_records
            if s.record_type == "przegląd"
        ]
        with_next = [s for s in inspections if s.next_inspection]
        ratio = len(with_next) / len(inspections) if inspections else 0
        assert ratio >= 0.8, (
            f"Za mało przeglądów z nextInspection: "
            f"{len(with_next)}/{len(inspections)}"
        )
