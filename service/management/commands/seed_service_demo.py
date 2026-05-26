"""Seed historycznych wpisow serwisowych na prezentacje 14 czerwca 2026.

Sebastian's spec (Wave 14-B, 17 maja 2026):

* historyczne 2-3 lata wstecz (od polowy 2023 do 10.06.2026 - nie pozniej),
* kazda maszyna raz w roku standardowy przeglad (przeglad_roczny),
* niektore maszyny 2x w roku (przeglad_polroczny - bardziej obciazone),
* niektore raz na 3 lata (przeglad_roczny z luka 36 miesiecy),
* plus naprawy (NAPRAWA type) - rozne czestotliwosci per maszyna,
* dodatkowo: 1-2 maszyny W_SERWISIE na 14.06.2026 (otwarty NAPRAWA
  record, status maszyny przerzucony na W_SERWISIE).

Cap na dacie wpisu: ``SERVICE_HISTORY_CUTOFF = 2026-06-10`` - 4 dni przed
prezentacja, zeby nie symulowac "wpisu z przyszlosci". Wyjatek to maszyny
w naprawie 'na zywo' - tam performed_date jest data prezentacji minus 1-3
dni (rzeczywiste rozpoczecie naprawy w tym tygodniu).

Algorytm per maszyna:

1. Wylosuj "profile" maszyny:
   * "lekkie zuzycie" (30%) - 1 przeglad rocznie + 0-2 naprawy/rok
   * "srednie zuzycie" (50%) - 1 przeglad rocznie + 2-4 naprawy/rok
   * "wysokie zuzycie" (20%) - 2 przeglady rocznie + 3-5 napraw/rok
2. Dla kazdego roku w [2023, 2024, 2025, 2026]:
   * przeglady wedlug profilu (data w polowie roku),
   * naprawy losowo rozrzucone po roku,
   * koszty: przeglad 800-2500 PLN, naprawa 300-5000 PLN.
3. Po petli wybierz 1-2 maszyny (W_MAGAZYNIE/W_SERWISIE w aktualnym statusie)
   i dorzuc otwarta naprawe na 11-13 czerwca + zmien status na W_SERWISIE.

Usage::

    DJANGO_SETTINGS_MODULE=planer_config.settings.dev \\
        uv run python manage.py seed_service_demo

    # czysty start:
    uv run python manage.py seed_service_demo --clear
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from machines.models import Machine
from service.models import ServiceRecord

# =============================================================================
# CONFIG - daty kluczowe
# =============================================================================

PRESENTATION_DATE = date(2026, 6, 14)

# Hard cap - zaden wpis serwisowy z performed_date po tej dacie. Sebastian:
# "wszystko <= 10.06.2026 - nie pozniej". Wyjatek dla 1-2 maszyn ktore
# trafia W_SERWISIE na czas prezentacji (open record z performed_date
# z biezacego tygodnia).
SERVICE_HISTORY_CUTOFF = date(2026, 6, 10)

# Start danych historycznych - 3 lata wstecz od kwartalu kalendarzowego
# zaokraglonego. Czerwiec 2023 daje czysty 3-letni horyzont.
HISTORY_START = date(2023, 6, 1)

# =============================================================================
# CONFIG - profile maszyn
# =============================================================================

# Profile zuzycia - tuple (przeglady/rok, naprawy/rok-min, naprawy/rok-max).
# "Lekkie zuzycie" sredsnio 1 naprawa rocznie, "wysokie" - 4. Wagi 30/50/20
# matchuja typowy park budowlany (wieksza polowa maszyn srednio uzywana).
MACHINE_PROFILES = [
    ("lekkie", 1, 0, 2),
    ("srednie", 1, 2, 4),
    ("wysokie", 2, 3, 5),
]
PROFILE_WEIGHTS = [30, 50, 20]

# =============================================================================
# CONFIG - kosztowe (PLN)
# =============================================================================

INSPECTION_COST_MIN = Decimal("800.00")
INSPECTION_COST_MAX = Decimal("2500.00")

REPAIR_COST_MIN = Decimal("300.00")
REPAIR_COST_MAX = Decimal("5000.00")

# Open W_SERWISIE - aktywna naprawa w trakcie. Czesto droga (skomplikowany
# problem, dlatego maszyna jeszcze nie wrocila do pracy).
ACTIVE_REPAIR_COST_MIN = Decimal("1500.00")
ACTIVE_REPAIR_COST_MAX = Decimal("8000.00")

# =============================================================================
# CONFIG - opisy serwisantow + zakres prac
# =============================================================================

SERVICE_TECHNICIANS = [
    "Pawel Mechanik",
    "Wojciech Serwisant",
    "Andrzej Diagnostyk",
    "Tomasz Hydraulik",
    "Krzysztof Elektryk",
    "Marek Spec",
    "Piotr Inspektor",
    "Mariusz Technik",
]

# Opisy przegladow - generyczne ale realistic. Krotkie zeby admin widok
# wygladal czysto.
INSPECTION_DESCRIPTIONS = [
    "Przeglad okresowy - wymiana oleju, filtra powietrza, sprawdzenie hydrauliki.",
    "Przeglad zgodnie z planem - test ukladu hamulcowego, smarowanie podzespolow.",
    "Coroczna inspekcja techniczna - protokol UDT, kalibracja czujnikow.",
    "Przeglad rozszerzony - wymiana plynow eksploatacyjnych, kontrola opon/gasienic.",
    "Inspekcja stanu mechanicznego - test funkcji ramienia, kalibracja zaworow.",
]

REPAIR_DESCRIPTIONS = [
    "Naprawa ukladu hydraulicznego - wymiana waza HP, sprawdzenie szczelnosci.",
    "Wymiana pompy paliwowej + filtra. Test pracy silnika.",
    "Naprawa ukladu elektrycznego - wymiana alternatora, sprawdzenie akumulatora.",
    "Wymiana lozysk osi obrotu, regeneracja ramienia.",
    "Naprawa silnika - wymiana paska rozrzadu, uszczelnienie miski olejowej.",
    "Wymiana ukladu chlodzenia - chlodnica + termostat + plyn.",
    "Naprawa skrzyni biegow - wymiana sprzegla, regeneracja synchronizacji.",
    "Wymiana opon/gasienic + balansowanie. Test jazdy.",
]

ACTIVE_REPAIR_DESCRIPTIONS = [
    "Awaria pompy hydraulicznej - oczekiwanie na czesc zamienna z importu.",
    "Diagnostyka ukladu elektrycznego - lokalizowanie usterki, test podzespolow.",
    "Generalny remont silnika - wymontowanie, rozbiorka, ocena zuzycia.",
    "Wymiana ukladu kierowniczego po awarii - oczekiwanie na zatwierdzenie kosztow.",
]


def _random_cost(low: Decimal, high: Decimal) -> Decimal:
    """Losowy koszt w przedziale [low, high] z dokladnoscia do grosza.

    Uzywamy float intermediate -> Decimal zeby uniknac drogiej operacji
    losowania na Decimal'u (random nie ma native Decimal support).
    """
    range_pln = float(high - low)
    raw = float(low) + random.random() * range_pln
    return Decimal(str(round(raw, 2)))


def _historical_inspection_date(year: int, profile_inspections: int, idx: int) -> date:
    """Wylicza realistyczna date przegladu w danym roku.

    Dla 1 przegladu/rok: koniec maja - poczatek czerwca (typowy budzet
    coroczny dla park budowlanego, before-summer-rush).
    Dla 2 przegladow/rok: koniec maja + koniec listopada (przed sezonem
    zimowym i przed letnim).
    """
    if profile_inspections == 1:
        month = 5
        day = random.randint(15, 30)
    elif idx == 0:
        month = 5
        day = random.randint(10, 25)
    else:
        month = 11
        day = random.randint(5, 25)
    candidate = date(year, month, day)
    # Cap na CUTOFF dla 2026 zeby nie symulowac wpisu po prezentacji.
    if candidate > SERVICE_HISTORY_CUTOFF:
        # Wymuszamy date w maju (przed prezentacja).
        candidate = date(2026, 5, random.randint(1, 15))
    return candidate


def _historical_repair_date(year: int) -> date:
    """Losowa data naprawy w danym roku (cap'owana na CUTOFF dla 2026)."""
    # Dla 2023 - pomijamy pierwsze 5 miesiecy (HISTORY_START = czerwiec 2023).
    if year == 2023:
        start_doy = 152
    else:
        start_doy = 1
    if year == 2026:
        # Cap na CUTOFF - day-of-year 161 (10 czerwca 2026).
        end_doy = SERVICE_HISTORY_CUTOFF.timetuple().tm_yday
    else:
        end_doy = 365 if year % 4 != 0 else 366
    if start_doy >= end_doy:
        return date(year, 1, 1) + timedelta(days=start_doy - 1)
    doy = random.randint(start_doy, end_doy)
    return date(year, 1, 1) + timedelta(days=doy - 1)


def _calculate_next_inspection(performed: date, profile_inspections: int) -> date:
    """Wylicza next_inspection z dateutil.relativedelta (handles leap years).

    Maszyna z 2 przegladami/rok ma next_inspection za 6 miesiecy, z 1 za 12.
    """
    if profile_inspections >= 2:
        return performed + relativedelta(months=6)
    return performed + relativedelta(months=12)


def _record_type_for_inspection(profile_inspections: int) -> str:
    """Wybiera RecordType wedlug profilu przegladow.

    2 przeglady/rok = przeglad_polroczny.
    1 przeglad/rok = przeglad_roczny.
    """
    if profile_inspections >= 2:
        return ServiceRecord.RecordType.PRZEGLAD_POLROCZNY.value
    return ServiceRecord.RecordType.PRZEGLAD_ROCZNY.value


class Command(BaseCommand):
    help = (
        "Seed historycznych wpisow serwisowych (2-3 lata wstecz, <=10.06.2026) "
        "plus 1-2 maszyny W_SERWISIE z aktywna naprawa na prezentacje 14.06."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Usun wszystkie istniejace ServiceRecord przed seedingiem.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=14062026,
            help="Random seed (default 14062026 - prezentacja date).",
        )
        parser.add_argument(
            "--in-service-count",
            type=int,
            default=2,
            help="Ile maszyn ma byc W_SERWISIE na 14.06 (default 2).",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])

        machines = list(Machine.objects.exclude(status=Machine.Status.WYCOFANA))
        if not machines:
            raise CommandError("Brak maszyn (poza Wycofana) - uruchom seed_machines.")

        if options["clear"]:
            deleted = ServiceRecord.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Usunieto: {deleted}"))

        # ------------------------------------------------------------------
        # Rok-po-roku historia per maszyna
        # ------------------------------------------------------------------
        created = 0
        # ``Counter`` na profile dla raportu po seedingu (debug Sebastian'a).
        profile_counts: Counter[str] = Counter()

        for machine in machines:
            profile_name, n_inspections, n_repairs_min, n_repairs_max = random.choices(
                MACHINE_PROFILES, weights=PROFILE_WEIGHTS, k=1
            )[0]
            profile_counts[profile_name] += 1

            # Lata historyczne - 2023-2026 (do CUTOFF).
            for year in (2023, 2024, 2025, 2026):
                # Przeglady - wedlug profilu (1 lub 2 rocznie). Dla 2023
                # ograniczamy do 1 (bo HISTORY_START = czerwiec, brak miejsca
                # na drugi).
                effective_inspections = n_inspections if year != 2023 else min(1, n_inspections)

                for insp_idx in range(effective_inspections):
                    performed = _historical_inspection_date(year, effective_inspections, insp_idx)
                    # Pominij jesli > CUTOFF.
                    if performed > SERVICE_HISTORY_CUTOFF:
                        continue

                    next_insp = _calculate_next_inspection(performed, effective_inspections)
                    ServiceRecord.objects.create(
                        machine=machine,
                        record_type=_record_type_for_inspection(effective_inspections),
                        performed_date=performed,
                        performed_by=random.choice(SERVICE_TECHNICIANS),
                        description=random.choice(INSPECTION_DESCRIPTIONS),
                        cost=_random_cost(INSPECTION_COST_MIN, INSPECTION_COST_MAX),
                        next_inspection=next_insp,
                    )
                    created += 1

                # Naprawy - losowa liczba w przedziale profilu.
                n_repairs = random.randint(n_repairs_min, n_repairs_max)
                for _ in range(n_repairs):
                    performed = _historical_repair_date(year)
                    if performed > SERVICE_HISTORY_CUTOFF:
                        continue
                    ServiceRecord.objects.create(
                        machine=machine,
                        record_type=ServiceRecord.RecordType.NAPRAWA.value,
                        performed_date=performed,
                        performed_by=random.choice(SERVICE_TECHNICIANS),
                        description=random.choice(REPAIR_DESCRIPTIONS),
                        cost=_random_cost(REPAIR_COST_MIN, REPAIR_COST_MAX),
                        next_inspection=None,  # NAPRAWA nie wplywa na cykl
                    )
                    created += 1

            # Update Machine.inspection_date - max(next_inspection) z
            # przegladow tej maszyny. Mirror logic z service.create_record.
            latest = (
                ServiceRecord.objects.filter(machine=machine)
                .exclude(record_type=ServiceRecord.RecordType.NAPRAWA)
                .order_by("-next_inspection")
                .first()
            )
            if latest and latest.next_inspection:
                machine.inspection_date = latest.next_inspection
                machine.save(update_fields=["inspection_date"])

        # ------------------------------------------------------------------
        # 1-2 maszyny W_SERWISIE na 14.06 (otwarta naprawa "live")
        # ------------------------------------------------------------------
        # Sebastian: maszyny bez aktualnego przegladu dostaja status W_SERWISIE.
        # Wybieramy machines ktore juz nie sa NA_BUDOWIE/ZAREZERWOWANA bo
        # tamtych nie chcemy ruszac (seed_reservations_demo je ustawil).
        candidates = [
            m
            for m in machines
            if m.status in (Machine.Status.W_MAGAZYNIE, Machine.Status.W_SERWISIE)
        ]
        if not candidates:
            self.stdout.write(
                self.style.WARNING(
                    "Brak maszyn W_MAGAZYNIE/W_SERWISIE - pomijam aktywne naprawy. "
                    "Wszystkie sa NA_BUDOWIE? Uruchom najpierw seed_reservations_demo."
                )
            )
        else:
            n_in_service = min(options["in_service_count"], len(candidates))
            in_service_machines = random.sample(candidates, n_in_service)

            for machine in in_service_machines:
                # Aktywna naprawa - performed_date 11-13 czerwca 2026 (3-1 dni
                # przed prezentacja). next_inspection = None bo to NAPRAWA.
                performed = PRESENTATION_DATE - timedelta(days=random.randint(1, 3))
                ServiceRecord.objects.create(
                    machine=machine,
                    record_type=ServiceRecord.RecordType.NAPRAWA.value,
                    performed_date=performed,
                    performed_by=random.choice(SERVICE_TECHNICIANS),
                    description=random.choice(ACTIVE_REPAIR_DESCRIPTIONS),
                    cost=_random_cost(ACTIVE_REPAIR_COST_MIN, ACTIVE_REPAIR_COST_MAX),
                    next_inspection=None,
                )
                created += 1

                # Przerzuc Machine.status na W_SERWISIE. Save bez sygnalu zeby
                # nie wywolac signal handlera service.signals.
                machine.status = Machine.Status.W_SERWISIE.value
                machine.save(update_fields=["status"])

            self.stdout.write(
                f"Maszyny W_SERWISIE na 14.06: {', '.join(m.uid for m in in_service_machines)}"
            )

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Utworzono {created} wpisow serwisowych."))
        self.stdout.write(f"Rozklad profili maszyn: {dict(profile_counts)}")

        type_counts = Counter(ServiceRecord.objects.values_list("record_type", flat=True))
        self.stdout.write("Rozklad typow:")
        for type_val, n in sorted(type_counts.items()):
            self.stdout.write(f"  {type_val}: {n}")

        # Status maszyn po seedingu
        machine_status = Counter(Machine.objects.values_list("status", flat=True))
        self.stdout.write("Status maszyn po seedingu:")
        for status_val, n in sorted(machine_status.items()):
            self.stdout.write(f"  {status_val}: {n}")
