"""Service-layer tests for :func:`service.services.create_service_record`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from service.models import ServiceRecord
from service.services import create_service_record


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_create_inspection_updates_machine_inspection_date(machine):
    # Machine starts with no inspection_date.
    assert machine.inspection_date is None

    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date(2026, 5, 16),
        cost=Decimal("750.00"),
    )

    machine.refresh_from_db()
    # 16.05.2026 + 3 miesiące = 16.08.2026
    assert record.next_inspection == date(2026, 8, 16)
    assert machine.inspection_date == date(2026, 8, 16)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_repair_does_not_update_machine_inspection_date(machine):
    machine.inspection_date = date(2026, 9, 1)
    machine.save(update_fields=["inspection_date"])

    create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date(2026, 5, 16),
        cost=Decimal("1500.00"),
    )

    machine.refresh_from_db()
    # Naprawa nigdy nie aktualizuje daty przeglądu.
    assert machine.inspection_date == date(2026, 9, 1)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_inspection_does_not_overwrite_later_date(machine):
    # Machine already has a future inspection date later than what the new
    # record would compute — we must keep the later date.
    machine.inspection_date = date(2027, 1, 1)
    machine.save(update_fields=["inspection_date"])

    create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date(2026, 5, 16),
    )

    machine.refresh_from_db()
    assert machine.inspection_date == date(2027, 1, 1)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_inspection_does_overwrite_earlier_date(machine):
    machine.inspection_date = date(2026, 6, 1)
    machine.save(update_fields=["inspection_date"])

    create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2026, 5, 16),
    )

    machine.refresh_from_db()
    # 16.05.2026 + 12 miesięcy = 16.05.2027 — nowsza, więc nadpisuje.
    assert machine.inspection_date == date(2027, 5, 16)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_performed_date_in_future_raises(machine):
    with pytest.raises(ValidationError) as exc:
        create_service_record(
            machine=machine,
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            performed_date=date(2026, 5, 17),
        )
    assert "przyszłości" in str(exc.value)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_next_inspection_uses_relativedelta_for_months(machine):
    # 31.01.2026 + 3 miesiące = 30.04.2026 (kwiecień ma 30 dni, nie 31).
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date(2026, 1, 31),
    )
    assert record.next_inspection == date(2026, 4, 30)


@pytest.mark.django_db
@freeze_time("2025-06-15")
def test_create_service_record_persists_all_fields(machine):
    """Wszystkie pola persistowane; ``@freeze_time`` chroni przed flaky kiedy
    przyszły refaktor usunie explicit ``today=...`` w argumentach (defensywnie
    fixuje ``date.today()`` fallback w services.create_service_record)."""
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date(2025, 6, 1),
        performed_by="Jan Kowalski",
        description="Wymiana siłownika hydraulicznego",
        cost=Decimal("4500.50"),
    )
    record.refresh_from_db()
    assert record.performed_by == "Jan Kowalski"
    assert record.description == "Wymiana siłownika hydraulicznego"
    assert record.cost.amount == Decimal("4500.50")
    assert record.next_inspection is None


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_polroczny_interval(machine):
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_POLROCZNY,
        performed_date=date(2026, 5, 16),
    )
    # 16.05.2026 + 6 miesięcy = 16.11.2026
    assert record.next_inspection == date(2026, 11, 16)


@pytest.mark.django_db
@freeze_time("2026-02-15")
def test_quarterly_inspection_at_january_31_uses_relativedelta_safely(machine):
    """31.01 + 3 mc = 30.04 (kwiecień ma 30 dni). ``@freeze_time`` chroni przed
    flaky day-rolling — bez frozen czasu ``performed_date > today`` check
    mógłby się wywrócić przy CI clock drift / month boundary."""
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date(2026, 1, 31),
    )
    assert record.next_inspection == date(2026, 4, 30)


@pytest.mark.django_db
@freeze_time("2024-03-01")
def test_inspection_at_leap_day_boundary(machine):
    """29.02.2024 + 12 mc = 28.02.2025 (rok przestępny → nieprzestępny).
    ``relativedelta`` poprawnie handluje brak 29.02 w 2025 — bez ``@freeze_time``
    test mógłby trafić w ``performed_date > today`` zależnie od dnia CI."""
    record = create_service_record(
        machine=machine,
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2024, 2, 29),
    )
    assert record.next_inspection == date(2025, 2, 28)
