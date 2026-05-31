"""Seed a handful of demo :class:`ConstructionSite` rows for development.

Usage::

    uv run python manage.py seed_sites
    uv run python manage.py seed_sites --count=10

The default 6 sites use stable Polish project numbers w nowym formacie
``10260000001 … 10260000006`` (10 = staly prefix, 26 = rok 2026, 5-cyfrowy
sekwencyjny numer). Adresy + nazwy firm to realne lokalizacje w PL
(geocodable na Google Maps).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from reservations.models import ConstructionSite

# Stable demo sites — kept short so they read cleanly on the list view.
# Wszystkie adresy to realne lokalizacje w PL (siedziby firm budowlanych,
# centra logistyczne, biurowce) — sprawdzalne na Google Maps.
DEMO_SITES: list[dict[str, str]] = [
    {
        "project_number": "10260000001",
        "name": "Osiedle Marina Mokotow — etap III",
        "client_name": "Polnord S.A.",
        "address": "ul. Stefana Batorego 18, 02-591 Warszawa",
        "city": "Warszawa",
    },
    {
        "project_number": "10260000002",
        "name": "Centrum Logistyczne Panattoni Park Lodz East",
        "client_name": "Panattoni Europe Sp. z o.o.",
        "address": "ul. Pomorska 555, 92-735 Lodz",
        "city": "Lodz",
    },
    {
        "project_number": "10260000003",
        "name": "Biurowiec Skanska Cedet — modernizacja",
        "client_name": "Skanska S.A.",
        "address": "ul. Marynarska 11, 02-674 Warszawa",
        "city": "Warszawa",
    },
    {
        "project_number": "10260000004",
        "name": "Most na rzece Warcie — droga ekspresowa S11",
        "client_name": "Mota-Engil Central Europe S.A.",
        "address": "ul. Wybickiego 24, 60-105 Poznan",
        "city": "Poznan",
    },
    {
        "project_number": "10260000005",
        "name": "Hala produkcyjna Erbud Industrial Park",
        "client_name": "Erbud S.A.",
        "address": "ul. Klimczaka 1, 02-797 Warszawa",
        "city": "Warszawa",
    },
    {
        "project_number": "10260000006",
        "name": "Centrum biurowe Strabag Office Park",
        "client_name": "Strabag Sp. z o.o.",
        "address": "ul. Parzniewska 10, 05-800 Pruszkow",
        "city": "Pruszkow",
    },
]


class Command(BaseCommand):
    help = "Dodaje demo budowy (10260000001 .. 10260000006) z realnymi adresami PL jesli jeszcze nie istnieja."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=len(DEMO_SITES),
            help=f"Ile budów dodać (max {len(DEMO_SITES)}, domyślnie wszystkie demo).",
        )

    def handle(self, *args, **options) -> None:
        count = min(options["count"], len(DEMO_SITES))
        created = 0
        for spec in DEMO_SITES[:count]:
            _, was_created = ConstructionSite.objects.get_or_create(
                project_number=spec["project_number"],
                defaults={
                    "name": spec["name"],
                    "client_name": spec["client_name"],
                    "address": spec["address"],
                    "city": spec["city"],
                    "status": ConstructionSite.Status.AKTYWNA,
                },
            )
            if was_created:
                created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Demo budowy: {created} utworzone, {count - created} już istniały.")
        )
