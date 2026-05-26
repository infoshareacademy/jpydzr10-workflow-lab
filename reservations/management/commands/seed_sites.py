"""Seed a handful of demo :class:`ConstructionSite` rows for development.

Usage::

    uv run python manage.py seed_sites
    uv run python manage.py seed_sites --count=10

The default 5 sites use stable, recognisable Polish project numbers
``BUD-2026-001 … BUD-2026-005`` so subsequent runs of seed scripts can
reference them by ID without surprises (idempotent).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from reservations.models import ConstructionSite

# Stable demo sites — kept short so they read cleanly on the list view.
DEMO_SITES: list[dict[str, str]] = [
    {
        "project_number": "BUD-2026-001",
        "name": "Osiedle Słoneczna Polana",
        "client_name": "Polnord S.A.",
        "address": "ul. Słoneczna 12",
        "city": "Warszawa",
    },
    {
        "project_number": "BUD-2026-002",
        "name": "Centrum Logistyczne Wschód",
        "client_name": "Panattoni Europe",
        "address": "ul. Magazynowa 4",
        "city": "Łódź",
    },
    {
        "project_number": "BUD-2026-003",
        "name": "Biurowiec Atlas Tower",
        "client_name": "Skanska SA",
        "address": "Aleja Krakowska 234",
        "city": "Kraków",
    },
    {
        "project_number": "BUD-2026-004",
        "name": "Most na Warcie",
        "client_name": "GDDKiA",
        "address": "Most na rzece Warcie, droga ekspresowa",
        "city": "Poznań",
    },
    {
        "project_number": "BUD-2026-005",
        "name": "Hala produkcyjna XYZ",
        "client_name": "Plastic Solutions Sp. z o.o.",
        "address": "ul. Przemysłowa 89",
        "city": "Wrocław",
    },
]


class Command(BaseCommand):
    help = "Dodaje demo budowy (BUD-2026-001 .. -005) jeśli jeszcze nie istnieją."

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
