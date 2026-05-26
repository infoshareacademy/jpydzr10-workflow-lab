"""Tests for the custom :class:`machines.managers.MachineManager`."""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from machines.factories import (
    AvailableMachineFactory,
    InServiceMachineFactory,
    MachineFactory,
    OnSiteMachineFactory,
    OverdueInspectionMachineFactory,
)
from machines.models import Machine


@pytest.mark.django_db
def test_available_returns_only_warehouse_status():
    AvailableMachineFactory(uid="A-1")
    AvailableMachineFactory(uid="A-2")
    OnSiteMachineFactory(uid="O-1")
    InServiceMachineFactory(uid="S-1")

    available = Machine.objects.available()
    assert available.count() == 2
    assert all(m.status == Machine.Status.W_MAGAZYNIE for m in available)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_overdue_inspection():
    OverdueInspectionMachineFactory(uid="OVR-1", inspection_date=date(2026, 1, 1))
    OverdueInspectionMachineFactory(uid="OVR-2", inspection_date=date(2026, 5, 15))
    MachineFactory(uid="OK-1", inspection_date=date(2026, 12, 1))

    overdue = Machine.objects.overdue_inspection()
    uids = {m.uid for m in overdue}
    assert uids == {"OVR-1", "OVR-2"}


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_upcoming_inspection_within_14_days_default():
    MachineFactory(uid="U-1", inspection_date=date(2026, 5, 17))
    MachineFactory(uid="U-2", inspection_date=date(2026, 5, 30))  # day 14
    MachineFactory(uid="LATE", inspection_date=date(2026, 6, 30))
    MachineFactory(uid="OVR", inspection_date=date(2026, 5, 1))

    upcoming = Machine.objects.upcoming_inspection()
    uids = {m.uid for m in upcoming}
    assert "U-1" in uids
    assert "U-2" in uids
    assert "LATE" not in uids
    assert "OVR" not in uids


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_upcoming_inspection_custom_window():
    MachineFactory(uid="A", inspection_date=date(2026, 5, 20))
    MachineFactory(uid="B", inspection_date=date(2026, 6, 1))

    in_30 = Machine.objects.upcoming_inspection(days=30)
    assert {m.uid for m in in_30} == {"A", "B"}


@pytest.mark.django_db
def test_by_type_filters_correctly():
    MachineFactory(uid="K-1", machine_type=Machine.Type.KOPARKA)
    MachineFactory(uid="K-2", machine_type=Machine.Type.KOPARKA)
    MachineFactory(uid="W-1", machine_type=Machine.Type.WALEC)

    koparki = Machine.objects.by_type(Machine.Type.KOPARKA)
    assert {m.uid for m in koparki} == {"K-1", "K-2"}
