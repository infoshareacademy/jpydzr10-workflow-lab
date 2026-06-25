"""Ustawia walutę PLN na historycznych wpisach serwisowych (sprzed 2026-06-01).

Po migracji MoneyField wszystkie istniejące rekordy dostają domyślną walutę EUR
(z ``default_currency``). Koszty zaimportowane z Milestone 1 były jednak w PLN,
więc starsze rekordy cofamy na PLN. Operacja na obu tabelach (bieżącej i
historycznej simple-history) wyłącznie przez ``bulk update`` — nigdy pętlą
``.save()`` (django-money #731: per-row save gubi walutę / jest O(N)).
"""

from __future__ import annotations

from datetime import datetime

from django.db import migrations
from django.utils.timezone import make_aware

# Granica "danych historycznych" — koszty utworzone wcześniej traktujemy jako PLN.
LEGACY_BEFORE = datetime(2026, 6, 1)


def set_legacy_pln(apps, schema_editor):
    cutoff = make_aware(LEGACY_BEFORE)
    ServiceRecord = apps.get_model("service", "ServiceRecord")
    HistoricalServiceRecord = apps.get_model("service", "HistoricalServiceRecord")
    ServiceRecord.objects.filter(created_at__lt=cutoff).update(cost_currency="PLN")
    HistoricalServiceRecord.objects.filter(created_at__lt=cutoff).update(cost_currency="PLN")


def reverse_to_eur(apps, schema_editor):
    cutoff = make_aware(LEGACY_BEFORE)
    ServiceRecord = apps.get_model("service", "ServiceRecord")
    HistoricalServiceRecord = apps.get_model("service", "HistoricalServiceRecord")
    ServiceRecord.objects.filter(created_at__lt=cutoff).update(cost_currency="EUR")
    HistoricalServiceRecord.objects.filter(created_at__lt=cutoff).update(cost_currency="EUR")


class Migration(migrations.Migration):
    dependencies = [
        ("service", "0002_historicalservicerecord_cost_currency_and_more"),
    ]

    operations = [
        migrations.RunPython(set_legacy_pln, reverse_to_eur),
    ]
