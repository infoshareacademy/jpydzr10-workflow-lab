"""Normalizuje walutę WSZYSTKICH wpisów serwisowych do EUR.

Decyzja właściciela: koszty serwisowe prowadzimy wyłącznie w EUR (operacje w
Belgii). Migracja 0003 cofnęła historyczne rekordy (sprzed 2026-06-01) na PLN,
tworząc mieszany zbiór PLN+EUR. Mieszane waluty psuły agregaty (``Sum('cost')``
sumował PLN i EUR jak jedną walutę), filtry progu kosztu (``> 1000``) oraz
nagłówki eksportów.

Ta migracja ustawia ``cost_currency='EUR'`` na każdym rekordzie (bieżącym i
historycznym simple-history), zachowując kwotę bez zmian. To dane demonstracyjne
(syntetyczne) — NIE przeliczamy kursem FX, tylko ujednolicamy etykietę waluty,
żeby cała dalsza arytmetyka kosztów była poprawna i jednowalutowa.

Operacja wyłącznie przez ``bulk update`` — nigdy pętlą ``.save()`` (django-money
#731: per-row save gubi walutę / jest O(N)).

Reverse jest celowo NO-OP: po ujednoliceniu do EUR informacja o tym, które
rekordy były wcześniej PLN, jest bezpowrotnie utracona (nie trzymamy znacznika
„auto-backfilled vs ręcznie wprowadzony"). Bezpieczny no-op chroni przed
„odtwarzaniem" błędnego podziału na podstawie zgadywanej daty granicznej —
cofnięcie 0004 zostawia dane w EUR (stan poprawny), a ewentualny powrót do
PLN wymaga świadomej, ręcznej korekty danych.
"""

from __future__ import annotations

from django.db import migrations

# Docelowa, jedyna waluta kosztów serwisowych.
TARGET_CURRENCY = "EUR"


def normalize_to_eur(apps, schema_editor):
    ServiceRecord = apps.get_model("service", "ServiceRecord")
    HistoricalServiceRecord = apps.get_model("service", "HistoricalServiceRecord")
    # Ujednolicamy wszystkie rekordy nie-EUR (kwoty zostają nietknięte).
    ServiceRecord.objects.exclude(cost_currency=TARGET_CURRENCY).update(
        cost_currency=TARGET_CURRENCY
    )
    HistoricalServiceRecord.objects.exclude(cost_currency=TARGET_CURRENCY).update(
        cost_currency=TARGET_CURRENCY
    )


def reverse_noop(apps, schema_editor):
    """Reverse celowo nic nie robi — patrz docstring modułu.

    Po normalizacji nie znamy już pierwotnej waluty per rekord, więc bezpieczny
    no-op jest jedyną poprawną opcją (alternatywa = zgadywanie po dacie, co
    powtórzyłoby błąd mieszanej waluty z 0003).
    """


class Migration(migrations.Migration):
    dependencies = [
        ("service", "0003_backfill_cost_currency_pln"),
    ]

    operations = [
        migrations.RunPython(normalize_to_eur, reverse_noop),
    ]
