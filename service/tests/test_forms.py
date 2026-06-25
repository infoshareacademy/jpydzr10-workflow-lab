"""Form-level tests for the service app."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time

from service.forms import (
    BulkInspectionForm,
    ReportFilterForm,
    ServiceRecordFilterForm,
    ServiceRecordForm,
)
from service.models import ServiceRecord


@pytest.mark.django_db
def test_service_record_form_valid(machine):
    form = ServiceRecordForm(
        data={
            "machine": machine.pk,
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": "2026-05-16",
            "performed_by": "Jan Kowalski",
            "description": "Test",
            "cost": "750.00",
        }
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_service_record_form_negative_cost_rejected(machine):
    form = ServiceRecordForm(
        data={
            "machine": machine.pk,
            "record_type": ServiceRecord.RecordType.NAPRAWA,
            "performed_date": "2026-05-16",
            "cost": "-1.00",
        }
    )
    assert not form.is_valid()
    assert "cost" in form.errors


@pytest.mark.django_db
def test_service_record_form_cost_initial_shows_amount(machine):
    """Edycja istniejącego wpisu: pole kosztu pokazuje samą kwotę (bez waluty)."""
    from service.factories import ServiceRecordFactory

    record = ServiceRecordFactory(machine=machine, cost=Decimal("321.00"))
    form = ServiceRecordForm(instance=record)
    # MoneyField initial to obiekt Money — kwota (bez waluty) jest w .amount.
    assert form.initial["cost"].amount == Decimal("321.00")


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_bulk_inspection_form_negative_cost_rejected(machine):
    """BulkInspectionForm odrzuca ujemny koszt (``min_value=0``)."""
    form = BulkInspectionForm(
        data={
            "machines": [machine.pk],
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": "2026-05-16",
            "cost": "-1.00",
        }
    )
    assert not form.is_valid()
    assert "cost" in form.errors


@pytest.mark.django_db
def test_bulk_inspection_form_requires_machines(machine):
    form = BulkInspectionForm(
        data={
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": "2026-05-16",
        }
    )
    assert not form.is_valid()
    assert "machines" in form.errors


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_bulk_inspection_form_valid(machine, second_machine):
    form = BulkInspectionForm(
        data={
            "machines": [machine.pk, second_machine.pk],
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": date.today().isoformat(),
            "cost": "100.00",
        }
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_bulk_inspection_future_date_rejected(machine):
    future = (date.today() + timedelta(days=10)).isoformat()
    form = BulkInspectionForm(
        data={
            "machines": [machine.pk],
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": future,
        }
    )
    assert not form.is_valid()
    assert "performed_date" in form.errors


@pytest.mark.django_db
def test_bulk_inspection_only_inspection_types_choices():
    form = BulkInspectionForm()
    # NAPRAWA nie jest dozwolona dla bulk inspection.
    choices = {value for value, _label in form.fields["record_type"].choices}
    assert ServiceRecord.RecordType.NAPRAWA.value not in choices
    assert ServiceRecord.RecordType.PRZEGLAD_KWARTALNY.value in choices


@freeze_time("2026-05-16")
def test_report_filter_form_defaults():
    form = ReportFilterForm()
    today = date.today()
    assert form.fields["year"].initial == today.year
    assert form.fields["quarter"].initial == ((today.month - 1) // 3) + 1


@pytest.mark.django_db
def test_list_filter_form_optional_fields_ok():
    form = ServiceRecordFilterForm(data={})
    assert form.is_valid()


@pytest.mark.django_db
def test_list_filter_form_cost_validation():
    form = ServiceRecordFilterForm(data={"cost_min": "abc"})
    assert not form.is_valid()


@pytest.mark.django_db
def test_list_filter_accepts_partial_filters(machine):
    form = ServiceRecordFilterForm(
        data={"record_type": ServiceRecord.RecordType.NAPRAWA, "cost_min": "100"}
    )
    assert form.is_valid()
    assert form.cleaned_data["cost_min"] == Decimal("100")
