"""Import reservations from the Milestone 1 ``reservations.json`` fixture.

The legacy JSON uses camelCase keys (``machineId``, ``startDate``,
``endDate``, ``projectNumber``) and string statuses that match
``Reservation.Status.value`` 1:1 — so the import is a straight field-by-field
copy with no data migration.

Behaviour:

* Skips rows whose ``machineId`` does not match an existing
  :class:`machines.Machine` (logged as warning).
* Auto-creates a :class:`ConstructionSite` for every unique
  ``projectNumber`` (status defaults to ``aktywna``) — keeps the imported
  reservations linked to a site instead of dropping the project number.
* Idempotent on a per-row basis (skips rows whose ``(machine, start_date)``
  pair already exists).

Usage::

    uv run python manage.py import_reservations \\
        --file=archive/milestone-1/data/reservations.json
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from machines.models import Machine
from reservations.models import ConstructionSite, Reservation


class Command(BaseCommand):
    help = "Importuje rezerwacje z M1 JSON-a (camelCase) do bazy."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--file",
            required=True,
            help="Ścieżka do reservations.json (np. archive/milestone-1/data/reservations.json).",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Plik nie istnieje: {path}")

        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Plik nie jest poprawnym JSON-em: {exc}") from exc

        created = skipped_missing_machine = skipped_existing = sites_created = 0

        with transaction.atomic():
            for row in rows:
                machine_uid = row.get("machineId", "").strip()
                try:
                    machine = Machine.objects.get(uid=machine_uid)
                except Machine.DoesNotExist:
                    skipped_missing_machine += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  pomijam {row.get('id')}: brak maszyny {machine_uid!r}"
                        )
                    )
                    continue

                try:
                    start = date.fromisoformat(row.get("startDate", ""))
                    end = date.fromisoformat(row.get("endDate", ""))
                except ValueError:
                    skipped_missing_machine += 1
                    continue

                # Avoid duplicates on re-runs — match (machine, start_date).
                if Reservation.objects.filter(machine=machine, start_date=start).exists():
                    skipped_existing += 1
                    continue

                project_number = row.get("projectNumber", "").strip()
                site = None
                if project_number:
                    site, was_created = ConstructionSite.objects.get_or_create(
                        project_number=project_number,
                        defaults={
                            "name": f"Budowa {project_number}",
                            "address": row.get("address", "") or "Adres do uzupełnienia",
                            "status": ConstructionSite.Status.AKTYWNA,
                        },
                    )
                    if was_created:
                        sites_created += 1

                status = row.get("status", "oczekująca")
                Reservation.objects.create(
                    machine=machine,
                    site=site,
                    start_date=start,
                    end_date=end,
                    person=row.get("person", "—"),
                    address=row.get("address", ""),
                    status=status,
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import: {created} utworzonych, {skipped_existing} duplikatów, "
                f"{skipped_missing_machine} pominiętych (brak maszyny), "
                f"{sites_created} nowych budów."
            )
        )
