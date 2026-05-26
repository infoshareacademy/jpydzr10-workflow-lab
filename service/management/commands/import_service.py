"""Management command — import a JSON file of service records into the database.

Used to bootstrap from the Milestone 1 console fixtures shipped in
``archive/milestone-1/data/service_records.json``. The JSON schema is the
M1 camelCase format::

    {
      "id": "SRV-0156",
      "machineId": "ZUR-002",
      "date": "2017-04-09",
      "type": "przegląd",
      "description": "...",
      "cost": 350,
      "nextInspection": "2018-04-09"
    }

M1 had only two ``type`` values (``"przegląd"``, ``"naprawa"``). For M2 we
map the unqualified ``"przegląd"`` to :attr:`ServiceRecord.RecordType.PRZEGLAD_ROCZNY`
as the safest default — the operator can re-classify in the admin if needed.

Usage::

    uv run python manage.py import_service path/to/service_records.json
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from machines.models import Machine
from service.models import ServiceRecord
from service.services import create_service_record

# Map M1 free-text ``type`` strings → :class:`ServiceRecord.RecordType` values.
M1_TYPE_MAP: dict[str, str] = {
    "przegląd": ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
    "naprawa": ServiceRecord.RecordType.NAPRAWA,
}


def _safe_decimal(value, default: Decimal = Decimal("0.00")) -> Decimal:
    """Parsuje cokolwiek na :class:`Decimal`, zwracając ``default`` przy błędzie.

    Helper wyodrębniony zamiast ``except (InvalidOperation, ValueError):``
    bo ruff format normalizuje parens-formę do non-standard
    ``except A, B:`` (Py 3.14 tuple shorthand).
    """
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default
    except ValueError:
        return default


class Command(BaseCommand):
    """Bulk-import a JSON file of service records into the database."""

    help = "Importuj listę wpisów serwisowych z pliku JSON (format Milestone 1)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=str, help="Ścieżka do pliku JSON.")
        parser.add_argument(
            "--skip-missing-machine",
            action="store_true",
            help="Pomijaj wpisy odnoszące się do nieistniejącej maszyny "
            "(domyślnie: raportuj jako błąd).",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Plik nie istnieje: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Niepoprawny JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError("Oczekiwano listy wpisów serwisowych w pliku JSON.")

        created = skipped = errors = 0
        for entry in payload:
            machine_uid = (entry.get("machineId") or "").strip()
            if not machine_uid:
                self.stderr.write(self.style.WARNING("Pominięto wpis bez machineId."))
                skipped += 1
                continue

            try:
                machine = Machine.objects.get(uid=machine_uid)
            except Machine.DoesNotExist:
                if options["skip_missing_machine"]:
                    skipped += 1
                    continue
                self.stderr.write(self.style.ERROR(f"Brak maszyny {machine_uid} — pomijam wpis."))
                errors += 1
                continue

            performed_date = parse_date(entry.get("date") or "") or None
            if performed_date is None:
                self.stderr.write(
                    self.style.WARNING(
                        f"Wpis {entry.get('id')}: brak / niepoprawna data — pomijam."
                    )
                )
                skipped += 1
                continue

            record_type = M1_TYPE_MAP.get(
                (entry.get("type") or "").strip().lower(),
                ServiceRecord.RecordType.PRZEGLAD_ROCZNY,
            )

            cost = _safe_decimal(entry.get("cost", 0) or 0)

            try:
                create_service_record(
                    machine=machine,
                    record_type=record_type,
                    performed_date=performed_date,
                    description=entry.get("description", "") or "",
                    cost=cost,
                )
                created += 1
            except (ValidationError, ValueError, TypeError) as exc:
                self.stderr.write(self.style.ERROR(f"Błąd przy wpisie {entry.get('id')}: {exc}"))
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import zakończony: utworzono {created}, pominięto {skipped}, błędów {errors}."
            )
        )
