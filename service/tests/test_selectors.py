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
    # expensive() = cost > 1000 EUR → 2000 i 3000 (100 i 500 odpadają).
    qs = filter_service_records({"expensive_only": "on"})
    assert {r.cost.amount for r in qs} == {Decimal("2000.00"), Decimal("3000.00")}


def test_expensive_only_boundary_strictly_greater(machines):
    """Granica: koszt == 1000 NIE jest drogi (próg to ``> 1000``, nie ``>=``)."""
    ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("1000.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("1000.01"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    qs = filter_service_records({"expensive_only": "on"})
    amounts = {r.cost.amount for r in qs}
    assert Decimal("1000.01") in amounts
    assert Decimal("1000.00") not in amounts


def test_only_inspections_excludes_naprawa(records):
    qs = filter_service_records({"only_inspections": "on"})
    # Asymetria danych: 2 naprawy + 2 przeglądy — sprawdzamy ZARÓWNO że napraw
    # nie ma, JAK I że zwrócone są faktyczne przeglądy (nie pusty zbiór ani
    # przypadkowo napraw o tej samej liczności).
    assert qs.count() == 2
    assert all(r.is_inspection for r in qs)
    assert {r.record_type for r in qs} == {
        ServiceRecord.RecordType.PRZEGLAD_KWARTALNY.value,
        ServiceRecord.RecordType.PRZEGLAD_ROCZNY.value,
    }


def test_record_type_filter(records):
    """Filtr ``record_type`` zwraca tylko wpisy danego typu (bezpośrednio)."""
    naprawy = filter_service_records({"record_type": ServiceRecord.RecordType.NAPRAWA})
    assert naprawy.count() == 2
    assert all(r.record_type == ServiceRecord.RecordType.NAPRAWA.value for r in naprawy)

    kwartalne = filter_service_records({"record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY})
    assert kwartalne.count() == 1
    assert kwartalne.first().cost.amount == Decimal("500.00")


def test_machine_filter(machines, records):
    """Filtr ``machine`` zwraca tylko wpisy wskazanej maszyny."""
    qs = filter_service_records({"machine": machines[0].pk})
    assert qs.count() == 2  # 100 + 500 (obie na machines[0])
    assert {r.machine_id for r in qs} == {machines[0].pk}


def test_machine_combined_with_cost_min(machines, records):
    """machine + cost_min razem = logiczne AND (oba warunki muszą zachodzić)."""
    # machines[0] ma 100 i 500 — cost_min=1000 wyklucza oba → pusto.
    qs = filter_service_records({"machine": machines[0].pk, "cost_min": "1000"})
    assert qs.count() == 0


def test_cost_max_filter(records):
    """Filtr ``cost_max`` zwraca wpisy z kosztem <= progu (EUR)."""
    qs = filter_service_records({"cost_max": "500"})
    assert {r.cost.amount for r in qs} == {Decimal("100.00"), Decimal("500.00")}


def test_cost_range_min_and_max(records):
    """cost_min + cost_max razem zawężają do przedziału [min, max]."""
    qs = filter_service_records({"cost_min": "500", "cost_max": "2000"})
    assert {r.cost.amount for r in qs} == {Decimal("500.00"), Decimal("2000.00")}


def test_cost_min_zero_includes_all(records):
    """cost_min=0 to filtr (>=0), który włącza WSZYSTKIE wpisy — nie 'brak filtra'."""
    qs = filter_service_records({"cost_min": "0"})
    assert qs.count() == 4


def test_invalid_cost_min_returns_all_records(records):
    """Niepoprawny parametr → form.is_valid() False → niezfiltrowany base_qs."""
    qs = filter_service_records({"cost_min": "nie-liczba"})
    assert qs.count() == 4


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


def test_report_data_requires_login(client, records):
    """Endpoint danych wykresu jest chroniony — anonim dostaje redirect do logowania."""
    response = client.get(reverse("service:report_data"), {"cost_min": "1000"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_export_all_xlsx_requires_login(client, records):
    """Eksport wszystkich wpisów jest chroniony — anonim dostaje redirect."""
    response = client.get(reverse("service:export_all_xlsx"), {"cost_min": "1000"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# ----------------------------------------------------------------------------
# Waluta EUR — po normalizacji (migracja 0004) cała agregacja jest jednowalutowa
# ----------------------------------------------------------------------------


def test_all_records_default_to_eur(records):
    """Każdy wpis utworzony fabryką ma walutę EUR (model default_currency)."""
    assert all(str(r.cost.currency) == "EUR" for r in ServiceRecord.objects.all())


def test_report_data_reports_eur_currency(client, records):
    """Endpoint wykresu deklaruje EUR — zgodnie z jedyną walutą danych."""
    user = User.objects.create_user("waluciarz", password="x")
    client.force_login(user)
    response = client.get(reverse("service:report_data"))
    payload = json.loads(response.content)
    assert payload["currency"] == "EUR"


def test_aggregation_correct_after_eur_normalization(client, machines):
    """Po sprowadzeniu wszystkich rekordów do EUR ``Sum('cost')`` sumuje poprawnie.

    Symulujemy stan sprzed normalizacji: część rekordów oznaczona PLN. Po
    ujednoliceniu do EUR (jak robi migracja 0004) suma per maszyna jest
    arytmetycznie poprawna — bez mieszania walut.
    """
    # Dwa wpisy na tej samej maszynie: jeden "legacy" (PLN), jeden EUR.
    legacy = ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("1000.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("250.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    # Wymuszamy mieszankę walut (stan jak po migracji 0003).
    ServiceRecord.objects.filter(pk=legacy.pk).update(cost_currency="PLN")

    # Normalizacja do EUR (odpowiednik migracji 0004) — kwoty bez zmian.
    ServiceRecord.objects.exclude(cost_currency="EUR").update(cost_currency="EUR")

    user = User.objects.create_user("agg", password="x")
    client.force_login(user)
    response = client.get(reverse("service:report_data"), {"machine": machines[0].pk})
    payload = json.loads(response.content)
    # 1000 + 250 = 1250 EUR (poprawne, bo obie kwoty są teraz w tej samej walucie).
    assert payload["data"] == [pytest.approx(1250.0)]
    assert payload["currency"] == "EUR"


@pytest.mark.django_db
def test_normalize_eur_migration_sets_all_records_to_eur(machines):
    """Funkcja normalizująca migracji 0004 sprowadza WSZYSTKIE rekordy do EUR.

    Wołamy ``normalize_to_eur`` bezpośrednio (z ``apps`` z global registry) na
    mieszanym zbiorze PLN+EUR i sprawdzamy, że kwoty zostają nietknięte, a
    waluta wszędzie = EUR.
    """
    import importlib

    from django.apps import apps as global_apps

    migration_0004 = importlib.import_module("service.migrations.0004_normalize_cost_currency_eur")

    pln_rec = ServiceRecordFactory(
        machine=machines[0],
        cost=Decimal("777.00"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    eur_rec = ServiceRecordFactory(
        machine=machines[1],
        cost=Decimal("123.45"),
        record_type=ServiceRecord.RecordType.NAPRAWA,
    )
    ServiceRecord.objects.filter(pk=pln_rec.pk).update(cost_currency="PLN")

    migration_0004.normalize_to_eur(global_apps, None)

    pln_rec.refresh_from_db()
    eur_rec.refresh_from_db()
    assert str(pln_rec.cost.currency) == "EUR"
    assert pln_rec.cost.amount == Decimal("777.00")  # kwota nietknięta
    assert str(eur_rec.cost.currency) == "EUR"
    assert eur_rec.cost.amount == Decimal("123.45")
    assert not ServiceRecord.objects.exclude(cost_currency="EUR").exists()
