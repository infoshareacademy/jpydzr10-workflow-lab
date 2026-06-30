"""Testy przeliczania ``Machine.inspection_date`` po usunięciu/edycji przeglądu.

``create_service_record`` bump'uje datę monotonicznie, ale usunięcie wpisu
zostawiało maszynę z datą wskazującą na nieistniejący przegląd (C1-BUG1).
``delete_service_record`` + recompute przywracają prawdę: data = max
``next_inspection`` po pozostałych przeglądach (albo ``None``).
"""

from __future__ import annotations

from datetime import date

import pytest

from machines.factories import MachineFactory
from service.models import ServiceRecord
from service.services import create_service_record, delete_service_record, update_service_record

pytestmark = pytest.mark.django_db


def test_delete_only_inspection_clears_machine_date():
    machine = MachineFactory()
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2026, 1, 10),
    )
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 1, 10)  # +12 mc

    delete_service_record(record)
    machine.refresh_from_db()
    assert machine.inspection_date is None  # brak przeglądów → brak daty


def test_delete_latest_inspection_falls_back_to_previous():
    machine = MachineFactory()
    older = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,  # +3 mc
        performed_date=date(2026, 1, 10),
    )
    newer = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,  # +12 mc → późniejsza data
        performed_date=date(2026, 2, 10),
    )
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 2, 10)  # max = roczny

    delete_service_record(newer)
    machine.refresh_from_db()
    assert machine.inspection_date == date(2026, 4, 10)  # spada do kwartalnego (+3 mc)
    assert ServiceRecord.objects.filter(pk=older.pk).exists()


def test_delete_repair_does_not_touch_inspection_date():
    machine = MachineFactory()
    create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2026, 1, 10),
    )
    repair = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date(2026, 3, 1),
    )
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 1, 10)

    delete_service_record(repair)  # naprawa nie wpływa na datę przeglądu
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 1, 10)


def test_update_inspection_date_recomputes_machine():
    machine = MachineFactory()
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2026, 6, 1),
    )
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 6, 1)

    # Korekta: przegląd był faktycznie wcześniej → data maszyny musi zjechać.
    update_service_record(record, performed_date=date(2026, 1, 1))
    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 1, 1)
