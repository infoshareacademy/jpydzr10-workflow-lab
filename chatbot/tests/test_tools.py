"""Testy READ-ONLY narzędzi chatbota — każde sprawdzane osobno z DB fixtures."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time

from chatbot import tools
from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory
from service.factories import RepairFactory, ServiceRecordFactory
from service.models import ServiceRecord

# =============================================================================
# get_machine_status
# =============================================================================


@pytest.mark.django_db
def test_get_machine_status_found(machine):
    result = tools.get_machine_status("KOP-001")
    assert result.found is True
    assert result.uid == "KOP-001"
    assert result.name == "Koparka chatbot test"
    assert result.status == "W magazynie"
    assert result.machine_type == "Koparka"


@pytest.mark.django_db
def test_get_machine_status_not_found():
    result = tools.get_machine_status("M-NOTEXIST")
    assert result.found is False
    assert result.uid == "M-NOTEXIST"
    assert result.name is None


@pytest.mark.django_db
def test_get_machine_status_inspection_fields():
    m = Machine.objects.create(
        uid="MIN-001",
        name="Minikoparka",
        machine_type=Machine.Type.MINIKOPARKA,
        inspection_date=date(2026, 12, 31),
    )
    with freeze_time("2026-05-16"):
        result = tools.get_machine_status(m.uid)
    assert result.inspection_date == "2026-12-31"
    assert result.inspection_status == "ok"
    assert result.inspection_days_left == (date(2026, 12, 31) - date(2026, 5, 16)).days


# =============================================================================
# check_availability
# =============================================================================


@pytest.mark.django_db
def test_check_availability_machine_not_found():
    result = tools.check_availability("MISSING", "2026-06-01", "2026-06-05")
    assert result.available is False
    assert result.machine_found is False
    assert "MISSING" in result.error


@pytest.mark.django_db
def test_check_availability_invalid_dates_returns_error():
    result = tools.check_availability("KOP-001", "not-a-date", "2026-06-05")
    assert result.available is False
    assert result.error is not None
    assert "format" in result.error.lower()


@pytest.mark.django_db
def test_check_availability_end_before_start_returns_error(machine):
    result = tools.check_availability(machine.uid, "2026-06-10", "2026-06-05")
    assert result.available is False
    assert "Data" in result.error


@pytest.mark.django_db
def test_check_availability_returns_true_when_free(machine):
    result = tools.check_availability(machine.uid, "2026-06-01", "2026-06-05")
    assert result.available is True
    assert result.machine_found is True
    assert result.conflict_count == 0
    assert result.conflicts == []


@pytest.mark.django_db
def test_check_availability_detects_conflict(machine):
    ConfirmedReservationFactory(
        machine=machine,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        person="Jan Kowalski",
    )
    result = tools.check_availability(machine.uid, "2026-06-03", "2026-06-10")
    assert result.available is False
    assert result.conflict_count >= 1
    # Dane osobowe NIE wychodzą z narzędzia — kanał głosowy dostaje sam termin
    # i status, więc nazwisko z cudzej rezerwacji nie może zostać wypowiedziane.
    assert "Jan Kowalski" not in result.model_dump_json()
    assert result.conflicts[0].start == "2026-06-01"


# =============================================================================
# get_inspections_due
# =============================================================================


@pytest.mark.django_db
def test_get_inspections_due_counts_overdue_and_upcoming():
    with freeze_time("2026-05-16"):
        Machine.objects.create(
            uid="OVR-001", name="Przeterminowana", inspection_date=date(2026, 4, 1)
        )
        Machine.objects.create(uid="UPC-001", name="Wkrótce", inspection_date=date(2026, 5, 20))
        Machine.objects.create(uid="FAR-001", name="Daleko", inspection_date=date(2027, 1, 1))
        Machine.objects.create(uid="NUL-001", name="Brak daty", inspection_date=None)

        result = tools.get_inspections_due(days_ahead=14)

    assert result.overdue_count == 1
    assert result.upcoming_count == 1
    uids = [m.uid for m in result.machines]
    assert "OVR-001" in uids
    assert "UPC-001" in uids
    assert "FAR-001" not in uids


@pytest.mark.django_db
def test_get_inspections_due_clamps_days_ahead():
    with freeze_time("2026-05-16"):
        result = tools.get_inspections_due(days_ahead=99999)
    assert result.days_ahead == 365


@pytest.mark.django_db
def test_get_inspections_due_status_field_correct():
    with freeze_time("2026-05-16"):
        Machine.objects.create(uid="A", name="A", inspection_date=date(2026, 5, 1))
        Machine.objects.create(uid="B", name="B", inspection_date=date(2026, 5, 25))
        result = tools.get_inspections_due(days_ahead=14)

    statuses = {m.uid: m.status for m in result.machines}
    assert statuses["A"] == "overdue"
    assert statuses["B"] == "upcoming"


# =============================================================================
# get_service_costs
# =============================================================================


@pytest.mark.django_db
def test_get_service_costs_groups_by_type_display(machine):
    with freeze_time("2026-05-16"):
        ServiceRecordFactory(
            machine=machine,
            performed_date=date(2026, 5, 1),
            cost=Decimal("100.00"),
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        )
        ServiceRecordFactory(
            machine=machine,
            performed_date=date(2026, 5, 10),
            cost=Decimal("250.50"),
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        )
        RepairFactory(
            machine=machine,
            performed_date=date(2026, 5, 12),
            cost=Decimal("500.00"),
        )
        result = tools.get_service_costs(days=90)

    assert result.record_count == 3
    assert result.total_cost == pytest.approx(850.50)
    assert "Przegląd kwartalny (3 mc)" in result.by_type
    assert "Naprawa" in result.by_type
    assert result.by_type["Naprawa"] == pytest.approx(500.00)
    assert result.by_type["Przegląd kwartalny (3 mc)"] == pytest.approx(350.50)


@pytest.mark.django_db
def test_get_service_costs_filters_by_machine_type(machine):
    second = Machine.objects.create(uid="WAL-001", name="Walec", machine_type=Machine.Type.WALEC)
    with freeze_time("2026-05-16"):
        ServiceRecordFactory(
            machine=machine,
            performed_date=date(2026, 5, 1),
            cost=Decimal("100.00"),
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        )
        ServiceRecordFactory(
            machine=second,
            performed_date=date(2026, 5, 2),
            cost=Decimal("999.99"),
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        )
        result = tools.get_service_costs(machine_type=Machine.Type.KOPARKA, days=30)

    assert result.machine_type == Machine.Type.KOPARKA
    assert result.record_count == 1
    assert result.total_cost == pytest.approx(100.0)


@pytest.mark.django_db
def test_get_service_costs_empty_when_no_records():
    result = tools.get_service_costs(days=30)
    assert result.record_count == 0
    assert result.total_cost == 0.0
    assert result.by_type == {}


@pytest.mark.django_db
def test_get_service_costs_excludes_older_records(machine):
    with freeze_time("2026-05-16"):
        ServiceRecordFactory(
            machine=machine,
            performed_date=date(2026, 5, 16) - timedelta(days=200),
            cost=Decimal("100.00"),
        )
        result = tools.get_service_costs(days=30)
    assert result.record_count == 0
