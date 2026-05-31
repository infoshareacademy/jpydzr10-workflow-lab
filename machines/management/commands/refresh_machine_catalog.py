"""Refresh machine catalog — rename existing + top up missing types.

Cel:

* nazwy maszyn w schemacie ``{Typ z dużej} {n}`` (np. ``Koparka 1``, ``Wózek widłowy 3``)
  -- intuicyjne wyszukiwanie "minikoparka 13";
* dla każdego z 10 typów ``Machine.Type`` ma być realna reprezentacja w UI:
  po 5 sztuk dla 4 "głównych" typów, po 3 sztuki dla pozostałych 6;
* typ ``INNE`` dostaje nazwy opisowe (Wyciąg magazynowy / Drabina przejezdna /
  Rusztowanie modułowe) zamiast nudnych "Inne 1, Inne 2".

Idempotentny: drugie uruchomienie nie zmienia nic.
Atomowy: wszystko w jednej transakcji, brak częściowych stanów.

Usage::

    uv run python manage.py refresh_machine_catalog
    uv run python manage.py refresh_machine_catalog --dry-run
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from machines.models import Machine

TARGETS: dict[str, int] = {
    Machine.Type.KOPARKA: 5,
    Machine.Type.MINIKOPARKA: 5,
    Machine.Type.PODNOSNIK_NOZYCOWY: 5,
    Machine.Type.PODNOSNIK_TELESKOPOWY: 3,
    Machine.Type.AGREGAT: 5,
    Machine.Type.WOZEK_WIDLOWY: 3,
    Machine.Type.WALEC: 3,
    Machine.Type.ZAGESZCZARKA: 3,
    Machine.Type.SPAWARKA: 3,
    Machine.Type.INNE: 3,
}

INNE_NAMES: list[str] = [
    "Wyciąg magazynowy",
    "Drabina przejezdna",
    "Rusztowanie modułowe",
]

MANUFACTURERS_PL: list[str] = [
    "Bobcat Polska",
    "Hyundai Heavy Industries",
    "JCB Poland",
    "Kubota Europe",
    "Komatsu Polska",
    "Volvo CE",
    "Caterpillar Polska",
    "Manitou Polska",
    "Genie Lift",
    "Atlas Copco",
    "Honda Power",
    "Wacker Neuson",
    "Bomag Polska",
    "Lincoln Electric",
    "ESAB Polska",
]


def _next_free_uid(taken: set[str]) -> str:
    """Generate next M-XXXX UID not already in ``taken`` set."""
    n = 0
    while True:
        candidate = f"M-{n:04d}"
        if candidate not in taken:
            return candidate
        n += 1


def _pretty_name(mtype: str, idx: int) -> str:
    """Build display name for given type + sequence index (1-based).

    * INNE typ: opisowe nazwy bez liczb (każda unikalna),
    * WALEC typ: "Walec drogowy N" (doprecyzowanie kategorii — w katalogu
      pokazujemy walec drogowy, nie ogrodowy / lekki / wibracyjny),
    * pozostałe: ``{Label z dużej} {n}`` (Koparka 1, Wózek widłowy 3).
    """
    if mtype == Machine.Type.INNE:
        if 1 <= idx <= len(INNE_NAMES):
            return INNE_NAMES[idx - 1]
        return f"Sprzęt pomocniczy {idx}"
    if mtype == Machine.Type.WALEC:
        return f"Walec drogowy {idx}"
    label = Machine.Type(mtype).label
    return f"{label} {idx}"


class Command(BaseCommand):
    help = (
        "Przemianowuje istniejące maszyny na schemat 'Typ N' (Koparka 1, Minikoparka 2) "
        "i dotwarza maszyny dla typów, których brak w katalogu (target: 4 typy po 5 sztuk "
        "+ 6 typów po 3 sztuki = 38 maszyn)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż planowane zmiany bez zapisu.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=14062026,
            help="Random seed dla pól wypełnianych losowo (default 14062026).",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])
        dry_run = options["dry_run"]

        renamed_count = 0
        created_count = 0
        skipped_count = 0

        taken_uids: set[str] = set(Machine.objects.values_list("uid", flat=True))

        for mtype, target in TARGETS.items():
            existing = list(Machine.objects.filter(machine_type=mtype).order_by("uid"))

            for idx, machine in enumerate(existing, start=1):
                new_name = _pretty_name(mtype, idx)
                if machine.name == new_name:
                    skipped_count += 1
                    continue
                self.stdout.write(f"  RENAME {machine.uid}: {machine.name!r} -> {new_name!r}")
                if not dry_run:
                    machine.name = new_name
                    machine.save(update_fields=["name"])
                renamed_count += 1

            missing = target - len(existing)
            if missing <= 0:
                continue

            for offset in range(missing):
                new_idx = len(existing) + offset + 1
                new_name = _pretty_name(mtype, new_idx)
                uid = _next_free_uid(taken_uids)
                taken_uids.add(uid)

                payload = {
                    "uid": uid,
                    "name": new_name,
                    "machine_type": mtype,
                    "model": f"Model {random.randint(100, 999)}",
                    "capacity": random.randint(100, 5000),
                    "inspection_date": date(2026, 5, 27) + timedelta(days=random.randint(45, 270)),
                    "location": "Magazyn",
                    "status": Machine.Status.W_MAGAZYNIE,
                    "manufacturer": random.choice(MANUFACTURERS_PL),
                    "serial_number": f"SN-{random.randint(10_000_000, 99_999_999)}",
                    "build_year": random.randint(2015, 2025),
                    "notes": "",
                }
                self.stdout.write(
                    f"  CREATE {uid}: {new_name!r} (typ={mtype}, insp={payload['inspection_date']})"
                )
                if not dry_run:
                    Machine.objects.create(**payload)
                created_count += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY-RUN: zaplanowano {renamed_count} rename, "
                    f"{created_count} create, {skipped_count} bez zmian."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wykonano: {renamed_count} rename, {created_count} create, "
                    f"{skipped_count} bez zmian. Łącznie maszyn: "
                    f"{Machine.objects.count()}."
                )
            )
