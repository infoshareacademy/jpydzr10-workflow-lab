"""View-layer tests for the service app."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from freezegun import freeze_time

from service.factories import InspectionFactory, RepairFactory, ServiceRecordFactory
from service.models import ServiceRecord

# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_requires_login(client):
    resp = client.get(reverse("service:list"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_detail_requires_login(client, machine):
    record = InspectionFactory(machine=machine)
    resp = client.get(reverse("service:detail", kwargs={"pk": record.pk}))
    assert resp.status_code == 302


# ----------------------------------------------------------------------------
# LIST + filtry
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_renders(auth_client, machine):
    InspectionFactory.create_batch(3, machine=machine)
    resp = auth_client.get(reverse("service:list"))
    assert resp.status_code == 200
    assert b"Serwis i przegl" in resp.content


@pytest.mark.django_db
def test_list_filter_by_record_type(auth_client, machine):
    """Filter `record_type=naprawa` returns only repairs (1 row), not inspections."""
    RepairFactory(machine=machine, performed_by="NaprawaPerson")
    InspectionFactory(machine=machine, performed_by="PrzegladPerson")
    resp = auth_client.get(
        reverse("service:list"), {"record_type": ServiceRecord.RecordType.NAPRAWA}
    )
    assert resp.status_code == 200
    assert b"NaprawaPerson" in resp.content
    assert b"PrzegladPerson" not in resp.content


@pytest.mark.django_db
def test_list_filter_by_machine(auth_client, machine, second_machine):
    """Filter `machine=<pk>` returns only that machine's records."""
    InspectionFactory(machine=machine, performed_by="Filter1Person")
    InspectionFactory(machine=second_machine, performed_by="Filter2Person")
    resp = auth_client.get(reverse("service:list"), {"machine": second_machine.pk})
    assert b"Filter2Person" in resp.content
    assert b"Filter1Person" not in resp.content


@pytest.mark.django_db
def test_list_filter_expensive_only(auth_client, machine):
    """F-2: `expensive_only=1` returns only records with cost > 1000 EUR."""
    RepairFactory(machine=machine, performed_by="CheapRepairPerson", cost=Decimal("250.00"))
    RepairFactory(machine=machine, performed_by="ExpensiveRepairPerson", cost=Decimal("2500.00"))
    resp = auth_client.get(reverse("service:list"), {"expensive_only": "on"})
    assert resp.status_code == 200
    assert b"ExpensiveRepairPerson" in resp.content
    assert b"CheapRepairPerson" not in resp.content


@pytest.mark.django_db
def test_list_filter_cost_min(auth_client, machine):
    """`cost_min` ukrywa wpisy tańsze niż próg (EUR)."""
    RepairFactory(machine=machine, performed_by="BelowMinPerson", cost=Decimal("100.00"))
    RepairFactory(machine=machine, performed_by="AboveMinPerson", cost=Decimal("900.00"))
    resp = auth_client.get(reverse("service:list"), {"cost_min": "500"})
    assert resp.status_code == 200
    assert b"AboveMinPerson" in resp.content
    assert b"BelowMinPerson" not in resp.content


@pytest.mark.django_db
def test_list_filter_cost_max(auth_client, machine):
    """`cost_max` ukrywa wpisy droższe niż próg (EUR)."""
    RepairFactory(machine=machine, performed_by="BelowMaxPerson", cost=Decimal("100.00"))
    RepairFactory(machine=machine, performed_by="AboveMaxPerson", cost=Decimal("900.00"))
    resp = auth_client.get(reverse("service:list"), {"cost_max": "500"})
    assert resp.status_code == 200
    assert b"BelowMaxPerson" in resp.content
    assert b"AboveMaxPerson" not in resp.content


@pytest.mark.django_db
def test_list_filter_cost_range(auth_client, machine):
    """`cost_min` + `cost_max` razem = przedział [min, max] (AND)."""
    RepairFactory(machine=machine, performed_by="TooCheapPerson", cost=Decimal("100.00"))
    RepairFactory(machine=machine, performed_by="InRangePerson", cost=Decimal("700.00"))
    RepairFactory(machine=machine, performed_by="TooPriceyPerson", cost=Decimal("5000.00"))
    resp = auth_client.get(reverse("service:list"), {"cost_min": "500", "cost_max": "1000"})
    assert resp.status_code == 200
    assert b"InRangePerson" in resp.content
    assert b"TooCheapPerson" not in resp.content
    assert b"TooPriceyPerson" not in resp.content


@pytest.mark.django_db
def test_list_filter_only_inspections(auth_client, machine):
    """F-3: `only_inspections=on` returns only przegląd_* records (no naprawa)."""
    InspectionFactory(machine=machine, performed_by="InspectionPerson")
    RepairFactory(machine=machine, performed_by="RepairPerson")
    resp = auth_client.get(reverse("service:list"), {"only_inspections": "on"})
    assert resp.status_code == 200
    assert b"InspectionPerson" in resp.content
    assert b"RepairPerson" not in resp.content


# ----------------------------------------------------------------------------
# DETAIL
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_renders(auth_client, machine):
    record = InspectionFactory(machine=machine)
    resp = auth_client.get(reverse("service:detail", kwargs={"pk": record.pk}))
    assert resp.status_code == 200
    assert record.machine.uid.encode() in resp.content


@pytest.mark.django_db
def test_detail_404(auth_client):
    resp = auth_client.get(reverse("service:detail", kwargs={"pk": 99999}))
    assert resp.status_code == 404


# ----------------------------------------------------------------------------
# CREATE
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_get(auth_client):
    resp = auth_client.get(reverse("service:create"))
    assert resp.status_code == 200


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_create_post_persists(auth_client, machine):
    resp = auth_client.post(
        reverse("service:create"),
        {
            "machine": machine.pk,
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": date.today().isoformat(),
            "performed_by": "Jan Kowalski",
            "description": "Test",
            "cost": "750.00",
        },
    )
    assert resp.status_code == 302, resp.context["form"].errors if resp.context else resp.content
    assert ServiceRecord.objects.filter(machine=machine).count() == 1


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_create_post_validation_error(auth_client, machine):
    # Brak record_type — formularz odrzuci.
    resp = auth_client.post(
        reverse("service:create"),
        {
            "machine": machine.pk,
            "performed_date": date.today().isoformat(),
            "cost": "0",
        },
    )
    assert resp.status_code == 200  # re-render with errors
    assert b"To pole jest wymagane" in resp.content or b"required" in resp.content


# ----------------------------------------------------------------------------
# DELETE
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_post(auth_client, machine):
    record = ServiceRecordFactory(machine=machine)
    resp = auth_client.post(reverse("service:delete", kwargs={"pk": record.pk}))
    assert resp.status_code == 302
    assert not ServiceRecord.objects.filter(pk=record.pk).exists()


# ----------------------------------------------------------------------------
# BULK INSPECTION
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_inspection_get(auth_client):
    resp = auth_client.get(reverse("service:bulk_inspection"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_bulk_inspection_requires_permission(client, regular_user):
    """User bez `service.add_servicerecord` dostaje 403 (Wave 4 E2 P1 #7).

    Wcześniej widok wymagał tylko ``LoginRequiredMixin`` — każdy zalogowany
    mógł bulk-tworzyć przeglądy obchodząc per-machine permission gate.
    """
    client.force_login(regular_user)
    resp = client.get(reverse("service:bulk_inspection"))
    assert resp.status_code == 403


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_bulk_inspection_creates_per_machine(auth_client, machine, second_machine):
    resp = auth_client.post(
        reverse("service:bulk_inspection"),
        {
            "machines": [machine.pk, second_machine.pk],
            "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
            "performed_date": date.today().isoformat(),
            "cost": "100.00",
            "description": "Bulk test",
        },
    )
    assert resp.status_code == 302
    assert ServiceRecord.objects.filter(machine=machine).count() == 1
    assert ServiceRecord.objects.filter(machine=second_machine).count() == 1


# ----------------------------------------------------------------------------
# REPORTS
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_reports_page_renders(auth_client):
    resp = auth_client.get(reverse("service:reports"))
    assert resp.status_code == 200
    assert b"Raport" in resp.content


@pytest.mark.django_db
def test_report_xlsx_download(auth_client, machine):
    InspectionFactory(machine=machine, performed_date=date(2026, 5, 16), cost=Decimal("100.00"))
    resp = auth_client.get(reverse("service:report_xlsx", kwargs={"year": 2026, "quarter": 2}))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in resp["Content-Disposition"]


@pytest.mark.django_db
def test_report_xlsx_invalid_quarter_redirects(auth_client):
    resp = auth_client.get(reverse("service:report_xlsx", kwargs={"year": 2026, "quarter": 7}))
    assert resp.status_code == 302  # back to reports page


@pytest.mark.django_db
def test_inspection_pdf_download(auth_client, machine):
    record = InspectionFactory(machine=machine, performed_date=date(2026, 5, 16))
    resp = auth_client.get(reverse("service:pdf", kwargs={"pk": record.pk}))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert "attachment" in resp["Content-Disposition"]
    assert resp.content.startswith(b"%PDF-")


# ----------------------------------------------------------------------------
# CLOSE SERVICE  (F-1)
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_close_service_flips_machine_to_warehouse(client, machine):
    """F-1: POST /serwis/<pk>/zakoncz-serwis/ → machine status W_SERWISIE → W_MAGAZYNIE."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission

    from machines.models import Machine

    user_model = get_user_model()
    user = user_model.objects.create_user(username="closer", password="secret-pw-123!")
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="machines", codename="change_machine")
    )
    client.force_login(user)

    machine.status = Machine.Status.W_SERWISIE
    machine.save(update_fields=["status", "updated_at"])
    record = RepairFactory(machine=machine)

    resp = client.post(reverse("service:close_service", kwargs={"pk": record.pk}))
    assert resp.status_code == 302
    assert resp.url == reverse("service:detail", kwargs={"pk": record.pk})

    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_MAGAZYNIE


@pytest.mark.django_db
def test_close_service_requires_permission(auth_client, machine):
    """auth_client nie ma `machines.change_machine` → 403."""
    from machines.models import Machine

    machine.status = Machine.Status.W_SERWISIE
    machine.save(update_fields=["status", "updated_at"])
    record = RepairFactory(machine=machine)
    resp = auth_client.post(reverse("service:close_service", kwargs={"pk": record.pk}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_close_service_get_not_allowed(auth_client, machine):
    """GET → 405 (only POST is supported, mutation must be deliberate)."""
    record = RepairFactory(machine=machine)
    resp = auth_client.get(reverse("service:close_service", kwargs={"pk": record.pk}))
    assert resp.status_code == 405
