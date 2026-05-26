"""Manager / queryset tests for :class:`service.models.ServiceRecord`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from service.factories import InspectionFactory, RepairFactory, ServiceRecordFactory
from service.models import ServiceRecord


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_recent_default_30_days(machine):
    old = ServiceRecordFactory(machine=machine, performed_date=date(2026, 1, 1))
    fresh = ServiceRecordFactory(machine=machine, performed_date=date(2026, 5, 10))
    recent_pks = set(ServiceRecord.objects.recent().values_list("pk", flat=True))
    assert fresh.pk in recent_pks
    assert old.pk not in recent_pks


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_recent_custom_window(machine):
    ServiceRecordFactory(machine=machine, performed_date=date(2025, 1, 1))
    in_window = ServiceRecordFactory(machine=machine, performed_date=date(2025, 6, 1))
    recent_pks = set(ServiceRecord.objects.recent(days=400).values_list("pk", flat=True))
    assert in_window.pk in recent_pks


@pytest.mark.django_db
def test_by_machine(machine, second_machine):
    InspectionFactory(machine=machine)
    InspectionFactory(machine=second_machine)
    assert ServiceRecord.objects.by_machine(machine.pk).count() == 1
    assert ServiceRecord.objects.by_machine(second_machine.pk).count() == 1


@pytest.mark.django_db
def test_by_type_filters_correctly(machine):
    InspectionFactory(machine=machine)
    RepairFactory(machine=machine)
    inspections = ServiceRecord.objects.by_type(ServiceRecord.RecordType.PRZEGLAD_KWARTALNY)
    assert inspections.count() == 1


@pytest.mark.django_db
def test_expensive_threshold(machine):
    cheap = ServiceRecordFactory(machine=machine, cost=Decimal("500.00"))
    pricey = ServiceRecordFactory(machine=machine, cost=Decimal("2500.00"))
    pks = set(ServiceRecord.objects.expensive(Decimal("1000")).values_list("pk", flat=True))
    assert pricey.pk in pks
    assert cheap.pk not in pks


@pytest.mark.django_db
def test_expensive_accepts_float(machine):
    pricey = ServiceRecordFactory(machine=machine, cost=Decimal("100.00"))
    # threshold passed as float — must not blow up.
    pks = set(ServiceRecord.objects.expensive(50.0).values_list("pk", flat=True))
    assert pricey.pk in pks


@pytest.mark.django_db
def test_inspections_excludes_naprawa(machine):
    InspectionFactory(machine=machine)
    RepairFactory(machine=machine)
    inspections = ServiceRecord.objects.inspections()
    assert inspections.count() == 1
    assert all(r.record_type != ServiceRecord.RecordType.NAPRAWA for r in inspections)
