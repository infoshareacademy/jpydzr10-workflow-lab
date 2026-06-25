"""Testy współdzielonego selektora filtrów + endpointu danych wykresu.

Kluczowy wymóg (zadanie nauczyciela): wykres, tabela i eksport Excel pokazują
DOKŁADNIE ten sam zbiór wpisów dla danego querystringa — bo wszystkie idą przez
``filter_service_records``.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from machines.models import Machine
from service.factories import ServiceRecordFactory
from service.models import ServiceRecord
from service.selectors import filter_service_records

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def machines(db):
    return [
        Machine.objects.create(
            uid=f"KOP-{i:03d}",
            name=f"Koparka {i}",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        for i in range(1, 4)
    ]


@pytest.fixture
def records(machines):
    # Koszty: 100, 500, 2000, 3000 — różne maszyny i typy.
    ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("100.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date(2026, 2, 10),
    )
    ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("500.00"),
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date(2026, 3, 15),
    )
    ServiceRecordFactory(
        machine=machines[1],
        cost=Decimal("2000.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date(2026, 4, 1),
    )
    ServiceRecordFactory(
        machine=machines[2],
        cost=Decimal("3000.00"),
        record_type=ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
        performed_date=date(2026, 5, 20),
    )


def test_no_filter_returns_all(records):
    assert filter_service_records({}).count() == 4


def test_cost_min_filter(records):
    qs = filter_service_records({"cost_min": "1000"})
    assert qs.count() == 2  # 2000 + 3000
    assert all(r.cost.amount >= Decimal("1000") for r in qs)


def test_expensive_only_filter(records):
    # expensive() = cost > 1000 → 2000 i 3000.
    qs = filter_service_records({"expensive_only": "on"})
    assert qs.count() == 2


def test_only_inspections_excludes_naprawa(records):
    qs = filter_service_records({"only_inspections": "on"})
    assert qs.count() == 2  # kwartalny + roczny (bez 2 napraw)
    assert all(r.record_type != ServiceRecord.RecordType.NAPRAWA for r in qs)


def test_combined_cost_min_and_expensive(records):
    """Regresja: cost_min ORAZ expensive_only razem zawężają poprawnie."""
    qs = filter_service_records({"cost_min": "2500", "expensive_only": "on"})
    assert qs.count() == 1  # tylko 3000
    assert qs.first().cost.amount == Decimal("3000.00")


def test_date_range_filter(records):
    qs = filter_service_records({"performed_after": "2026-03-01", "performed_before": "2026-04-30"})
    assert qs.count() == 2  # 15.03 + 01.04


def test_report_data_matches_selector(client, records):
    """Suma słupków wykresu == suma kosztów przefiltrowanych wpisów (spójność)."""
    user = User.objects.create_user("raporter", password="x")
    client.force_login(user)
    params = {"cost_min": "1000"}
    response = client.get(reverse("service:report_data"), params)
    assert response.status_code == 200
    payload = json.loads(response.content)
    # Filtr cost_min=1000 → maszyny KOP-002 (2000) i KOP-003 (3000).
    assert set(payload["labels"]) == {"KOP-002", "KOP-003"}
    assert sum(payload["data"]) == pytest.approx(5000.0)
    selector_total = sum(float(r.cost.amount) for r in filter_service_records(params))
    assert sum(payload["data"]) == pytest.approx(selector_total)


def test_export_respects_filters(client, records):
    """Eksport z filtrem zwraca XLSX (200) i przechodzi przez ten sam selektor."""
    user = User.objects.create_user("eksporter", password="x")
    client.force_login(user)
    response = client.get(reverse("service:export_all_xlsx"), {"cost_min": "1000"})
    assert response.status_code == 200
    assert "spreadsheet" in response["Content-Type"]
