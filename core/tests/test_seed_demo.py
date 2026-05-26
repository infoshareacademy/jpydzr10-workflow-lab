"""Testy management command `seed_demo` (Wave 12 coverage).

Pokrywa:
* default flow (call seed_machines/seed_sites/seed_reservations)
* `--reset` flag (delete then seed)
* `_ensure_superuser` — both branches (existing + new)
* `--import-m1` — both branches (file exists + file missing)
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


@pytest.mark.django_db
def test_seed_demo_default_creates_data():
    """Default invocation → 3 sub-commands wywołane (machines/sites/reservations)."""
    out = StringIO()
    call_command(
        "seed_demo",
        "--machines",
        "2",
        "--sites",
        "1",
        "--reservations",
        "1",
        stdout=out,
    )
    assert "Demo data zaseedowane" in out.getvalue()
    user_model = get_user_model()
    # Superuser stworzony
    assert user_model.objects.filter(username="sebastian").exists()


@pytest.mark.django_db
def test_seed_demo_reset_clears_then_seeds(machine_factory):
    """--reset → _reset() przed seedem."""
    # Pre-existing machine
    machine_factory(uid="OLD-1")
    from machines.models import Machine

    assert Machine.objects.filter(uid="OLD-1").exists()
    out = StringIO()
    call_command(
        "seed_demo",
        "--reset",
        "--machines",
        "1",
        "--sites",
        "1",
        "--reservations",
        "1",
        stdout=out,
    )
    # OLD-1 wyczyszczone, ale nowa machine z seed_machines wytworzona
    assert not Machine.objects.filter(uid="OLD-1").exists()
    assert "Resetowanie" in out.getvalue() or "wyczyszczone" in out.getvalue()


@pytest.fixture
def machine_factory(db):
    from machines.factories import MachineFactory

    return MachineFactory


@pytest.mark.django_db
def test_seed_demo_idempotent_when_superuser_exists():
    """Drugi run → superuser już istnieje → "już istnieje" w stdout."""
    out1 = StringIO()
    call_command(
        "seed_demo",
        "--machines",
        "1",
        "--sites",
        "1",
        "--reservations",
        "1",
        stdout=out1,
    )
    out2 = StringIO()
    call_command(
        "seed_demo",
        "--machines",
        "1",
        "--sites",
        "1",
        "--reservations",
        "1",
        stdout=out2,
    )
    assert "już istnieje" in out2.getvalue()


@pytest.mark.django_db
def test_seed_demo_import_m1_missing_file_reports_error(tmp_path, monkeypatch):
    """--import-m1 z brakiem pliku → ERROR w stdout, bez crashu."""
    from core.management.commands import seed_demo as seed_demo_module

    # Wskazujemy nieistniejący katalog
    monkeypatch.setattr(seed_demo_module, "M1_DATA_DIR", tmp_path / "missing")

    out = StringIO()
    call_command("seed_demo", "--import-m1", stdout=out)
    assert "Brak pliku" in out.getvalue()


@pytest.mark.django_db
def test_seed_demo_import_m1_with_machines_only(tmp_path, monkeypatch):
    """--import-m1 z plikiem machines.json (bez reservations.json) → 'pomijam' branch."""
    import json

    from core.management.commands import seed_demo as seed_demo_module

    data_dir = tmp_path / "m1data"
    data_dir.mkdir()
    machines_file = data_dir / "machines.json"
    machines_file.write_text(
        json.dumps(
            [
                {
                    "id": "M1",
                    "uid": "M1-001",
                    "name": "Test",
                    "type": "koparka",
                    "model": "TX",
                    "capacity": 10,
                    "status": "W magazynie",
                    "location": "Magazyn",
                    "inspectionDate": "2026-12-01",
                    "manufacturer": "ACME",
                    "serialNumber": "S1",
                    "buildYear": 2020,
                    "notes": "",
                }
            ]
        )
    )
    # Brak reservations.json
    monkeypatch.setattr(seed_demo_module, "M1_DATA_DIR", data_dir)

    out = StringIO()
    call_command("seed_demo", "--import-m1", stdout=out)
    output = out.getvalue()
    assert "pomijam" in output or "zakończony" in output
