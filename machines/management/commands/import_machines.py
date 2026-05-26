"""Management command — import a JSON file of machines into the database.

Used to bootstrap the reference app from the Milestone 1 console fixtures
shipped in ``archive/milestone-1/data/machines.json``. The JSON schema is the
M1 camelCase format (``inspectionDate``, ``serialNumber``, ``buildYear``).

Usage::

    uv run python manage.py import_machines path/to/machines.json
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from machines.models import Machine
from machines.services import create_machine

# Map free-text M1 type strings → Machine.Type enum values.
# Anything not found here falls through to ``Machine.Type.INNE``.
M1_TYPE_MAP: dict[str, str] = {
    "koparka gąsienicowa": Machine.Type.KOPARKA,
    "koparka": Machine.Type.KOPARKA,
    "minikoparka": Machine.Type.MINIKOPARKA,
    "koparko-ładowarka": Machine.Type.KOPARKA,
    "ładowarka kołowa": Machine.Type.KOPARKA,
    "wywrotka": Machine.Type.INNE,
    "ciągnik siodłowy": Machine.Type.INNE,
    "naczepa": Machine.Type.INNE,
    "żuraw samojezdny": Machine.Type.INNE,
    "walec drogowy": Machine.Type.WALEC,
    "walec": Machine.Type.WALEC,
    "podnośnik koszowy": Machine.Type.PODNOSNIK_TELESKOPOWY,
    "podnośnik nożycowy": Machine.Type.PODNOSNIK_NOZYCOWY,
    "podnośnik teleskopowy": Machine.Type.PODNOSNIK_TELESKOPOWY,
    "agregat prądotwórczy": Machine.Type.AGREGAT,
    "wózek widłowy": Machine.Type.WOZEK_WIDLOWY,
    "zagęszczarka": Machine.Type.ZAGESZCZARKA,
    "spawarka": Machine.Type.SPAWARKA,
}


def _map_type(raw: str) -> str:
    """Map an arbitrary M1 type string to one of the :class:`Machine.Type` values."""
    return M1_TYPE_MAP.get(raw.strip().lower(), Machine.Type.INNE)


class Command(BaseCommand):
    """Bulk-import a JSON file of machines into the database."""

    help = "Importuj listę maszyn z pliku JSON (format Milestone 1)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Ścieżka do pliku JSON.")
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Pomijaj maszyny których UID już istnieje (domyślnie: raportuj jako błąd).",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Plik nie istnieje: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Niepoprawny JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError("Oczekiwano listy maszyn w pliku JSON.")

        created = 0
        skipped = 0
        errors = 0
        for entry in payload:
            uid = entry.get("uid")
            if not uid:
                self.stderr.write(self.style.WARNING("Pominięto rekord bez UID."))
                skipped += 1
                continue

            if Machine.objects.filter(uid=uid).exists():
                if options["skip_existing"]:
                    skipped += 1
                    continue
                self.stderr.write(self.style.WARNING(f"Duplikat UID {uid} — pominięto."))
                skipped += 1
                continue

            inspection_iso = entry.get("inspectionDate") or None
            inspection_date = parse_date(inspection_iso) if inspection_iso else None

            try:
                create_machine(
                    uid=uid,
                    name=entry.get("name", ""),
                    machine_type=_map_type(entry.get("type", "")),
                    model=entry.get("model", "") or "",
                    capacity=int(entry.get("capacity") or 0),
                    inspection_date=inspection_date,
                    location=entry.get("location", "Magazyn"),
                    status=entry.get("status", Machine.Status.W_MAGAZYNIE),
                    manufacturer=entry.get("manufacturer", "") or "",
                    serial_number=entry.get("serialNumber", "") or "",
                    build_year=int(entry.get("buildYear") or 0),
                    notes=entry.get("notes", "") or "",
                )
                created += 1
            except (ValidationError, ValueError, TypeError) as exc:
                self.stderr.write(self.style.ERROR(f"Błąd przy {uid}: {exc}"))
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import zakończony: utworzono {created}, pominięto {skipped}, błędów {errors}."
            )
        )
