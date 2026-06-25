"""Model-level tests for :class:`service.models.ServiceRecord`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from service.factories import (
    AnnualInspectionFactory,
    InspectionFactory,
    RepairFactory,
    ServiceRecordFactory,
)
from service.models import INSPECTION_INTERVALS, ServiceRecord


@pytest.mark.django_db
def test_service_record_creation(machine):
    record = ServiceRecordFactory(machine=machine)
    assert record.pk is not None
    assert record.machine_id == machine.pk
    assert record.created_at is not None
    assert record.updated_at is not None


@pytest.mark.django_db
def test_default_ordering_newest_first(machine):
    older = ServiceRecordFactory(machine=machine, performed_date=date(2024, 1, 1))
    newer = ServiceRecordFactory(machine=machine, performed_date=date(2025, 1, 1))
    records = list(ServiceRecord.objects.all())
    assert records[0].pk == newer.pk
    assert records[1].pk == older.pk


@pytest.mark.django_db
def test_str_representation(machine):
    record = ServiceRecordFactory(
        machine=machine,
        performed_date=date(2026, 5, 16),
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
    )
    assert str(record) == "KOP-001 2026-05-16 Przegląd kwartalny (3 mc)"


@pytest.mark.django_db
def test_is_inspection_property(machine):
    inspection = InspectionFactory(machine=machine)
    repair = RepairFactory(machine=machine)
    assert inspection.is_inspection is True
    assert repair.is_inspection is False


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_is_overdue_followup(machine):
    overdue = InspectionFactory(
        machine=machine,
        performed_date=date(2025, 1, 1),
        next_inspection=date(2025, 4, 1),
    )
    current = InspectionFactory(
        machine=machine,
        performed_date=date(2026, 4, 1),
        next_inspection=date(2026, 7, 1),
    )
    no_next = RepairFactory(machine=machine, next_inspection=None)
    assert overdue.is_overdue_followup() is True
    assert current.is_overdue_followup() is False
    assert no_next.is_overdue_followup() is False


@pytest.mark.django_db
def test_inspection_intervals_constants():
    # Sanity — the four record types and the interval dict are kept in sync.
    inspection_types = {value for value in INSPECTION_INTERVALS}
    assert inspection_types == {
        ServiceRecord.RecordType.PRZEGLAD_KWARTALNY.value,
        ServiceRecord.RecordType.PRZEGLAD_POLROCZNY.value,
        ServiceRecord.RecordType.PRZEGLAD_ROCZNY.value,
    }
    # NAPRAWA is intentionally NOT in the interval map.
    assert ServiceRecord.RecordType.NAPRAWA.value not in INSPECTION_INTERVALS


@pytest.mark.django_db
def test_cost_money_field(machine):
    record = ServiceRecordFactory(machine=machine, cost=Decimal("123.45"))
    record.refresh_from_db()
    # Koszt jest MoneyField — kwota + waluta (domyślnie EUR).
    assert record.cost.amount == Decimal("123.45")
    assert str(record.cost.currency) == "EUR"


@pytest.mark.django_db
def test_choices_label_format(machine):
    record = AnnualInspectionFactory(machine=machine)
    assert record.get_record_type_display() == "Przegląd roczny (12 mc)"
