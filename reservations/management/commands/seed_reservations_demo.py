"""Seed realistycznych rezerwacji — dane centrowane na dniu uruchomienia seeda.

Kotwice dat są WZGLĘDEM ``date.today()`` (nie zamrożone), więc seed odpalony przed
demo daje świeży, sensowny obraz „na dziś". Rozkład:

* historyczne (~2,5 mies. wstecz - dziś): wszystkie ``zakończona``,
* dziś - +7 dni (CONFIRM_CUTOFF): wszystkie ``potwierdzona`` (czysta tablica),
* dalej: mix ``potwierdzona`` (~70%) + ``oczekująca`` (~30%),
* gęstość ~0,6 wokół dziś (część maszyn WOLNA — magazyn ma zapas), sparse dalej,
* średnia długość rezerwacji: 15 dni (min 5, max 60), przestoje 1-4 dni
  między rezerwacjami na tę samą maszynę.

Algorytm per maszyna (ekskludujemy ``Wycofana``):

1. Cursor zaczyna 1 marca 2026,
2. Pętla while cursor < koniec horyzontu (30.09.2026):

   a. Wylosuj długość ``length`` w [5, 60] (skewed do 15),
   b. ``end_date = cursor + length``,
   c. Decyzja status na podstawie ``end_date`` vs ``today`` i 15.06,
   d. Density filter: w sierpniu/wrześniu losowo pomijamy slot
      (machine "wolna w tym okresie"),
   e. Utwórz rezerwację jeśli brak konfliktu (rzadkie - cursor zawsze
      idzie do przodu, ale check defensywnie),
   f. ``cursor = end_date + losowy 1-4 dni`` (gap między rezerwacjami).

Usage::

    DJANGO_SETTINGS_MODULE=planer_config.settings.dev \\
        uv run python manage.py seed_reservations_demo

    # czysty start (usuwa wszystko z reservations.Reservation):
    uv run python manage.py seed_reservations_demo --clear

Wymaga: ``ConstructionSite.objects.filter(status='aktywna').exists()`` i
``Machine.objects.exclude(status='Wycofana').exists()``.
Idempotentne z ``--clear`` - bez tego dodaje na top istniejących.
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from machines.models import Machine
from reservations.models import ConstructionSite, Reservation

# =============================================================================
# CONFIG - daty kluczowe
# =============================================================================

# Kotwice dat są WZGLĘDEM dnia uruchomienia seeda (date.today()), NIE zamrożone.
# Zamrożenie na 2026-06-14 sprawiło, że po 3 tygodniach dane „przeterminowały się":
# rezerwacje ciągnęły od marca, prawie każda maszyna wyglądała na wynajętą od
# miesięcy, znikomo mało wolnych. Seed uruchomiony PRZED demo = dane centrowane na
# dniu demo (świeży, sensowny obraz). Dla powtarzalnego układu użyj `--seed N`.
PRESENTATION_DATE = date.today()
TODAY = date.today()

# Rezerwacje kończące się do tej daty są potwierdzone (czysta tablica przed demo).
CONFIRM_CUTOFF = date.today() + timedelta(days=7)

# Start danych historycznych - ~2.5 miesiaca wstecz (dashboard „zakonczone w kwartale").
HISTORY_START = date.today() - timedelta(days=75)

# Koniec horyzontu - ~2.8 miesiaca w przod. Dalej rzadko (sparse).
HORIZON_END = date.today() + timedelta(days=85)

# =============================================================================
# CONFIG - długości i density
# =============================================================================

# Sebastian's spec: srednia 15 dni, min 5, max 60. Uzywamy randint biased ku
# 15 przez triangular distribution (mode=15).
DURATION_MIN = 5
DURATION_MAX = 60
DURATION_MODE = 15

# Gap miedzy rezerwacjami na tej samej maszynie (transport / przygotowanie).
GAP_MIN_DAYS = 1
GAP_MAX_DAYS = 4


# Gęstość rezerwacji zależy od ODLEGŁOŚCI slotu od dnia demo, nie od bezwzględnego
# miesiąca (inaczej po przesunięciu okna względem dziś gęstość by się rozjechała).
# Umiarkowanie gęsto wokół „dziś" (~0.6 → część maszyn WOLNA, realny magazyn ma zapas
# i jest co rezerwować głosem), rzadziej w dalszej przyszłości.
def _density_for(cursor: date, center: date) -> float:
    months = (cursor.year - center.year) * 12 + (cursor.month - center.month)
    if months <= 1:  # przeszłość, bieżący i następny miesiąc — umiarkowanie gęsto
        return 0.6
    if months == 2:
        return 0.45
    return 0.3  # dalej w przyszłość — sparse


# =============================================================================
# CONFIG - dane fixturowe (osoby, adresy)
# =============================================================================

# Osoby rezerwujace w biurze (Marek, Anna, etc. - magazynier ich zna).
PERSONS_OFFICE = [
    "Tomasz Nowak",
    "Anna Kowalska",
    "Marek Wisniewski",
    "Katarzyna Lewandowska",
    "Piotr Dabrowski",
    "Magdalena Zielinska",
    "Krzysztof Szymanski",
    "Joanna Wozniak",
    "Andrzej Kaminski",
    "Barbara Jankowska",
]

# Osoby odpowiedzialne na budowie (kierownicy, brygadziści).
RESPONSIBLE_PERSONS = [
    "Marek Kierownik",
    "Adam Brygadzista",
    "Krzysztof Foreman",
    "Pawel Kierowski",
    "Tadeusz Majster",
    "Jacek Szef Budowy",
    "Wojciech Brygadier",
    "Mariusz Inspektor",
]

# Adresy dostawy - 3 duze miasta + 3 srednie (realistic na PL rynek).
CITIES = [
    "Warszawa",
    "Krakow",
    "Poznan",
    "Wroclaw",
    "Gdansk",
    "Lodz",
    "Bydgoszcz",
    "Lublin",
]

STREETS = [
    "Budowlana",
    "Przemyslowa",
    "Kolejowa",
    "Mostowa",
    "Fabryczna",
    "Magazynowa",
    "Transportowa",
    "Robotnicza",
]


def _random_address() -> str:
    """ul. <Ulica> <nr>, <Miasto> - format zgodny z UI labels."""
    return f"ul. {random.choice(STREETS)} {random.randint(1, 200)}, {random.choice(CITIES)}"


def _decide_status(start_date: date, end_date: date) -> str:
    """Decyzja Reservation.Status na podstawie pozycji w czasie.

    Logika z Sebastian spec:

    * koniec < dzis -> ``zakonczona`` (historyczne, terminal),
    * dzis <= koniec < 15.06 -> ``potwierdzona`` (przed prezentacja - czysto),
    * koniec >= 15.06 -> 70% ``potwierdzona`` / 30% ``oczekujaca`` (post-event,
      typowy backlog magazynu).

    Note: ``start_date`` parameter zachowany na wypadek przyszlych zmian w
    logice (np. "started in past, ends in future" edge case).
    """
    if end_date < TODAY:
        return Reservation.Status.ZAKONCZONA.value
    if end_date < CONFIRM_CUTOFF:
        return Reservation.Status.POTWIERDZONA.value
    # Po 15.06 - mix 70/30 confirmed/pending. Wagi przez ``choices`` bo
    # ``random.choice`` na dwu-elementowej liscie z duplikatami daje
    # zaokraglone 70%.
    return random.choices(
        [
            Reservation.Status.POTWIERDZONA.value,
            Reservation.Status.OCZEKUJACA.value,
        ],
        weights=[70, 30],
        k=1,
    )[0]


def _random_duration() -> int:
    """Randint(5, 60) z trojkatnym rozkladem (mode=15).

    Triangular daje dlugi "ogon" do 60 dni (long-running kontrakty letnie)
    ale wieksza czesc masy w okolicach 15 - co matchuje typowy budowlany
    business cycle (2-tygodniowy najem to standard).
    """
    return int(random.triangular(DURATION_MIN, DURATION_MAX, DURATION_MODE))


def _ensure_sites() -> list[ConstructionSite]:
    """Zwraca listę aktywnych budów - tworzy 3 dodatkowe jeśli mniej niż 5.

    Nazwy są fixture-style (Sebastian katalog), numbers BUD-2026-XXX
    z wolnych slotów.
    """
    extra_sites = [
        {
            "name": "Hala magazynowa Logistic Park",
            "client_name": "Logistic Park Sp. z o.o.",
            "city": "Wroclaw",
            "address": "ul. Magazynowa 100, Wroclaw",
        },
        {
            "name": "Stadion miejski - modernizacja trybun",
            "client_name": "Miasto Stoleczne Warszawa",
            "city": "Warszawa",
            "address": "Al. Sportowa 1, Warszawa",
        },
        {
            "name": "Osiedle Zielone Wzgorza",
            "client_name": "Murapol Developer S.A.",
            "city": "Katowice",
            "address": "ul. Wzgorz Zielonych 50, Katowice",
        },
    ]

    existing = list(ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA))
    if len(existing) >= 5:
        return existing

    # Znajdź najwyzszy istniejacy numer i kontynuuj
    last_num = 0
    for site in ConstructionSite.objects.all():
        try:
            num = int(site.project_number.split("-")[-1])
            last_num = max(last_num, num)
        except (ValueError, IndexError):
            continue

    created_extra = []
    for site_data in extra_sites[: max(0, 5 - len(existing))]:
        last_num += 1
        project_number = f"BUD-2026-{last_num:03d}"
        # ``get_or_create`` chroni przed duplikatami przy ponownym uruchomieniu
        # (np. jesli admin recznie dodal te same nazwy).
        site, _created = ConstructionSite.objects.get_or_create(
            project_number=project_number,
            defaults={
                "name": site_data["name"],
                "client_name": site_data["client_name"],
                "address": site_data["address"],
                "city": site_data["city"],
                "status": ConstructionSite.Status.AKTYWNA,
                "start_date": HISTORY_START,
                "end_date": HORIZON_END,
            },
        )
        created_extra.append(site)

    return existing + created_extra


class Command(BaseCommand):
    help = (
        "Seed realistycznych rezerwacji na prezentacje 14.06.2026 - "
        "historyczne (zakonczone) + biezace (potwierdzone) + przyszle "
        "(mix potwierdzonych i oczekujacych). Dense lipiec, medium sierpien, "
        "sparse wrzesien."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Usun wszystkie istniejace rezerwacje przed seedingiem (idempotent run).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=14062026,  # 14 czerwca 2026 jako reproducible seed
            help="Random seed (default 14062026 - prezentacja date).",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])

        sites = _ensure_sites()
        if not sites:
            raise CommandError("Brak aktywnych budow i nie udalo sie utworzyc - sprawdz fixtures.")

        machines = list(Machine.objects.exclude(status=Machine.Status.WYCOFANA).order_by("uid"))
        if not machines:
            raise CommandError("Brak maszyn (wszystkie Wycofane?) - uruchom seed_machines.")

        if options["clear"]:
            # Usuwamy w 2 krokach - historical_records cascade, potem rezerwacje.
            # ``Reservation.history.all().delete()`` nie jest potrzebne -
            # simple-history ma on_delete=CASCADE z PK rezerwacji.
            deleted = Reservation.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Usunieto: {deleted}"))

        created = 0
        skipped = 0

        for machine in machines:
            cursor = HISTORY_START
            machine_count = 0

            while cursor < HORIZON_END:
                duration = _random_duration()
                end_date = cursor + timedelta(days=duration)
                if end_date > HORIZON_END:
                    break

                # Density check - dla sierpnia/wrzesnia czasem skip slot
                # (cursor przesuwa sie ale nie tworzymy rezerwacji).
                density = _density_for(cursor, PRESENTATION_DATE)
                if random.random() > density:
                    # Skip - przesuwamy cursor do nastepnego potencjalnego okna
                    # bez tworzenia rezerwacji.
                    cursor = end_date + timedelta(days=random.randint(GAP_MIN_DAYS, GAP_MAX_DAYS))
                    skipped += 1
                    continue

                status = _decide_status(cursor, end_date)

                # ``person`` - kto wpisal w biurze, ``responsible_person`` -
                # kierownik/brygadzista na budowie. Rozdzielenie z Wave 14-A B4.
                Reservation.objects.create(
                    machine=machine,
                    site=random.choice(sites),
                    start_date=cursor,
                    end_date=end_date,
                    person=random.choice(PERSONS_OFFICE),
                    responsible_person=random.choice(RESPONSIBLE_PERSONS),
                    address=_random_address(),
                    status=status,
                    notes=f"Rezerwacja demo prezentacja {PRESENTATION_DATE.isoformat()}",
                )
                created += 1
                machine_count += 1

                # Gap do nastepnej rezerwacji
                cursor = end_date + timedelta(days=random.randint(GAP_MIN_DAYS, GAP_MAX_DAYS))

            self.stdout.write(f"  {machine.uid}: {machine_count} rezerwacji")

        # ------------------------------------------------------------------
        # Update Machine.status dla maszyn ktore akurat sa "Na budowie"
        # ------------------------------------------------------------------
        # Dla prezentacji - maszyny ktore maja aktywna (POTWIERDZONA)
        # rezerwacje obejmujaca 14.06 dostaja status NA_BUDOWIE.
        # Reszta dostaje W_MAGAZYNIE (jesli nie sa W_SERWISIE).
        # Note: status W_SERWISIE/WYCOFANA NIE zmieniamy.
        on_site_machines = (
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                start_date__lte=PRESENTATION_DATE,
                end_date__gte=PRESENTATION_DATE,
            )
            .values_list("machine_id", flat=True)
            .distinct()
        )
        on_site_ids = set(on_site_machines)

        for machine in machines:
            if machine.status in (Machine.Status.W_SERWISIE, Machine.Status.WYCOFANA):
                continue
            if machine.pk in on_site_ids:
                new_status = Machine.Status.NA_BUDOWIE.value
            else:
                # Sprawdz czy ma upcoming POTWIERDZONA pomiedzy dzis a 14.06 -
                # taka maszyna jest ``Zarezerwowana`` (bardziej realne).
                has_upcoming = Reservation.objects.filter(
                    machine=machine,
                    status=Reservation.Status.POTWIERDZONA,
                    start_date__gt=PRESENTATION_DATE,
                    start_date__lte=PRESENTATION_DATE + timedelta(days=14),
                ).exists()
                if has_upcoming:
                    new_status = Machine.Status.ZAREZERWOWANA.value
                else:
                    new_status = Machine.Status.W_MAGAZYNIE.value
            if machine.status != new_status:
                machine.status = new_status
                machine.save(update_fields=["status"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Utworzono {created} rezerwacji ({skipped} slotow pominietych "
                f"przez density). Maszyn 'Na budowie' na 14.06: {len(on_site_ids)}."
            )
        )

        # Summary by status
        counts = Counter(Reservation.objects.values_list("status", flat=True))
        self.stdout.write("Rozklad statusow:")
        for status_val, n in sorted(counts.items()):
            self.stdout.write(f"  {status_val}: {n}")
