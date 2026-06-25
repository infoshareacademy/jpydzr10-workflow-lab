"""Seed demo service records — N wpisów na każdą maszynę w DB.

Idempotent — jeśli baza już ma wpisy serwisowe, pomijamy (chyba że
``--force``). Wpisy są rozrzucone na ostatnie 3 lata wstecz, z mixem
przeglądów i napraw, żeby raporty wyglądały realistycznie.

Dane są celowo skrojone pod feature raportów (koszt per maszyna za dowolny
okres + wykres top-N + eksport Excel z filtrami):

* przeglądy mają niski/umiarkowany koszt, naprawy bywają drogie (część
  powyżej progu "drogiej naprawy" = ``EXPENSIVE_THRESHOLD_EUR``),
* każda maszyna dostaje losowy "mnożnik zużycia" — kilka maszyn akumuluje
  wyraźnie wyższe koszty, dzięki czemu wykres top-N ma sens (nie jest płaski),
* daty obejmują ostatnie ~3 lata (kwartalne / roczne filtry są demonstrowalne),
* waluta: zawsze EUR (pole ``cost`` ma ``default_currency='EUR'`` — migracja
  0004 znormalizowała całą bazę do EUR; przekazujemy ``Money(..., 'EUR')``
  jawnie, żeby nie polegać wyłącznie na defaultcie pola).

Usage::

    uv run python manage.py seed_service
    uv run python manage.py seed_service --per-machine 5
    uv run python manage.py seed_service --force
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from random import choice, randint, uniform
from random import seed as random_seed

from django.core.management.base import BaseCommand, CommandError
from djmoney.money import Money

from machines.models import Machine
from service.factories import (
    AnnualInspectionFactory,
    HalfYearInspectionFactory,
    InspectionFactory,
    RepairFactory,
)
from service.models import ServiceRecord

# Waluta wszystkich kosztów. Migracja 0004 znormalizowała bazę do EUR — seed
# musi trzymać się tej samej waluty, inaczej raporty (Sum + top-N) miałyby
# mieszankę walut. Nazwana stała zamiast literału rozsianego po pliku (ZASADA #8).
SEED_CURRENCY = "EUR"

# Domyślna liczba wpisów na maszynę (gdy nie podano ``--per-machine``). Przy
# ~40 maszynach daje to ~120 rekordów — zdrowy zbiór dla raportów / wykresu.
DEFAULT_PER_MACHINE = 3

# Domyślny random seed dla powtarzalności pokazu.
DEFAULT_RANDOM_SEED = 42

# Zakresy kosztów (EUR) — rozdzielone na przeglądy i naprawy, żeby rozkład był
# realistyczny: przeglądy tanie/umiarkowane, naprawy szeroko rozrzucone (część
# powyżej progu "drogiej naprawy", co czyni wykres top-N interesującym).
INSPECTION_COST_MIN = 80.0
INSPECTION_COST_MAX = 600.0
REPAIR_COST_MIN = 200.0
REPAIR_COST_MAX = 4500.0

# Mnożnik "zużycia" maszyny. Większość maszyn ma niski mnożnik (~1.0), ale
# kilka — wysoki, dzięki czemu sumaryczny koszt części maszyn wyraźnie odstaje
# i wykres top-N (najdroższe maszyny) jest czytelny zamiast płaski.
WEAR_MULTIPLIER_MIN = 0.6
WEAR_MULTIPLIER_MAX = 1.4
# Co którąś maszynę (statystycznie) oznaczamy jako "kosztochłonną" — wtedy
# mnożnik jest dobierany z górnego, droższego przedziału.
HEAVY_WEAR_PROBABILITY = 0.2
HEAVY_WEAR_MULTIPLIER_MIN = 1.8
HEAVY_WEAR_MULTIPLIER_MAX = 3.2

# Liczba dni wstecz, na którą rozrzucamy daty wpisów (3 lata).
HISTORY_SPAN_DAYS = 3 * 365
# Zakres odstępu (dni) do następnego przeglądu — tylko dla przeglądów.
NEXT_INSPECTION_MIN_DAYS = 60
NEXT_INSPECTION_MAX_DAYS = 360


def _wear_multiplier() -> float:
    """Losowy mnożnik zużycia maszyny.

    Z prawdopodobieństwem :data:`HEAVY_WEAR_PROBABILITY` maszyna jest
    "kosztochłonna" (mnożnik z górnego przedziału) — to one tworzą czoło
    rankingu kosztów na wykresie top-N. Reszta floty ma mnożnik bliski 1.0.
    """
    if uniform(0.0, 1.0) < HEAVY_WEAR_PROBABILITY:
        return uniform(HEAVY_WEAR_MULTIPLIER_MIN, HEAVY_WEAR_MULTIPLIER_MAX)
    return uniform(WEAR_MULTIPLIER_MIN, WEAR_MULTIPLIER_MAX)


def _cost_for(*, is_repair: bool, multiplier: float) -> Money:
    """Wylicz koszt wpisu w EUR z uwzględnieniem mnożnika zużycia maszyny.

    Naprawy mają szerszy, droższy zakres niż przeglądy. Wynik jest zawsze
    dodatni i zaokrąglony do grosza, zwracany jako :class:`~djmoney.money.Money`
    w walucie :data:`SEED_CURRENCY` (EUR).
    """
    low, high = (
        (REPAIR_COST_MIN, REPAIR_COST_MAX)
        if is_repair
        else (INSPECTION_COST_MIN, INSPECTION_COST_MAX)
    )
    raw = uniform(low, high) * multiplier
    return Money(Decimal(str(round(raw, 2))), SEED_CURRENCY)


class Command(BaseCommand):
    """Seed demo service records using factory_boy."""

    help = "Tworzy N wpisów serwisowych na każdą maszynę (domyślnie 3)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--per-machine",
            type=int,
            default=DEFAULT_PER_MACHINE,
            help=f"Ile wpisów na maszynę (domyślnie {DEFAULT_PER_MACHINE}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Twórz nawet jeśli baza już ma wpisy serwisowe.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=DEFAULT_RANDOM_SEED,
            help="Random seed dla powtarzalności.",
        )

    def handle(self, *args, **options) -> None:
        random_seed(options["seed"])

        existing = ServiceRecord.objects.count()
        if existing and not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Baza zawiera już {existing} wpisów serwisowych — pomijam seed. "
                    "Użyj --force żeby dosypać."
                )
            )
            return

        machines = list(Machine.objects.all())
        if not machines:
            raise CommandError("Brak maszyn w bazie — uruchom najpierw seed_machines.")

        per_machine = options["per_machine"]
        today = date.today()
        # Pulling factories instead of writing manual creates keeps the
        # distribution realistic (factory_boy + Faker for performed_by/opis).
        factories = (
            (InspectionFactory, 0.35),
            (HalfYearInspectionFactory, 0.15),
            (AnnualInspectionFactory, 0.20),
            (RepairFactory, 0.30),
        )

        created = 0
        for machine in machines:
            # Stały mnożnik per maszyna — wszystkie jej wpisy są skalowane tym
            # samym współczynnikiem, więc "droga" maszyna jest droga spójnie.
            multiplier = _wear_multiplier()
            for _ in range(per_machine):
                factory = _weighted_pick(factories)
                is_repair = factory is RepairFactory
                # Rozrzuć daty na ostatnie 3 lata.
                performed = today - timedelta(days=randint(1, HISTORY_SPAN_DAYS))
                next_insp = (
                    None
                    if is_repair
                    else performed
                    + timedelta(days=randint(NEXT_INSPECTION_MIN_DAYS, NEXT_INSPECTION_MAX_DAYS))
                )
                factory(
                    machine=machine,
                    performed_date=performed,
                    next_inspection=next_insp,
                    cost=_cost_for(is_repair=is_repair, multiplier=multiplier),
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Utworzono {created} wpisów serwisowych (po ~{per_machine} na maszynę)."
            )
        )


def _weighted_pick(items):
    """Pick a factory class from ``[(factory, weight), ...]`` honouring weights."""
    factories, weights = zip(*items, strict=True)
    cumulative = []
    total = 0.0
    for w in weights:
        total += w
        cumulative.append(total)
    pick = uniform(0, total)
    for factory, threshold in zip(factories, cumulative, strict=True):
        if pick <= threshold:
            return factory
    return choice(factories)  # pragma: no cover — defensive fallback
