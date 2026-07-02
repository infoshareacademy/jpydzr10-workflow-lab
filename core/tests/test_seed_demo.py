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
    """Default invocation → 4 sub-commands wywołane (machines/sites/reservations/service)."""
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
def test_seed_demo_creates_service_records_in_eur():
    """Seed tworzy wpisy serwisowe (fundament raportów) — wszystkie w EUR.

    Bez tych danych feature raportów (koszt per maszyna + wykres top-N + Excel)
    nie ma czego pokazać. Sprawdzamy że wpisy powstają i mają walutę EUR
    (migracja 0004 znormalizowała bazę do EUR).
    """
    from service.models import ServiceRecord

    call_command(
        "seed_demo",
        "--machines",
        "3",
        "--sites",
        "1",
        "--reservations",
        "0",
        "--service-per-machine",
        "3",
        stdout=StringIO(),
    )
    records = ServiceRecord.objects.all()
    # 3 maszyny x 3 wpisy = 9 wpisów serwisowych.
    assert records.count() == 9
    # Wszystkie koszty w EUR — żaden inny kod waluty się nie prześlizgnął.
    currencies = {str(r.cost.currency) for r in records}
    assert currencies == {"EUR"}


@pytest.mark.django_db
def test_seed_demo_service_seeding_is_idempotent():
    """Drugi run seed_demo NIE duplikuje wpisów serwisowych (seed_service skip)."""
    from service.models import ServiceRecord

    common = ("--machines", "2", "--sites", "1", "--reservations", "0")
    call_command("seed_demo", *common, stdout=StringIO())
    first_count = ServiceRecord.objects.count()
    assert first_count > 0

    out = StringIO()
    call_command("seed_demo", *common, stdout=out)
    # Brak akumulacji — seed_service pomija gdy wpisy już istnieją.
    assert ServiceRecord.objects.count() == first_count
    assert "pomijam seed" in out.getvalue()


@pytest.mark.django_db
def test_seed_demo_creates_role_accounts():
    """Seed tworzy 3 konta ról (kierownik/magazynier/montażysta) + admina."""
    from accounts.models import EmployeeProfile

    call_command(
        "seed_demo", "--machines", "1", "--sites", "1", "--reservations", "0", stdout=StringIO()
    )
    user_model = get_user_model()

    admin = user_model.objects.get(username="sebastian")
    assert admin.is_superuser
    assert admin.email  # adres skrzynki demo (adresat powiadomień)

    expected = {
        "seba1": EmployeeProfile.Function.KIEROWNIK,
        "seba2": EmployeeProfile.Function.MAGAZYNIER,
        "seba3": EmployeeProfile.Function.MONTAZYSTA,
    }
    for username, function in expected.items():
        user = user_model.objects.get(username=username)
        assert not user.is_superuser
        assert user.profile.function == function
        assert user.profile.phone  # unikalny numer E.164

    # Numery telefonów są unikalne między kontami.
    phones = [user_model.objects.get(username=u).profile.phone for u in expected]
    assert len(set(phones)) == len(phones)

    # RBAC end-to-end: sygnał sync_groups_on_employee_save musi przypisać konta
    # ról do właściwych grup uprawnień (kierownik→Kierownicy, magazynier→
    # Magazynierzy). Montażysta celowo NIE ma grupy (least privilege).
    seba1 = user_model.objects.get(username="seba1")
    seba2 = user_model.objects.get(username="seba2")
    seba3 = user_model.objects.get(username="seba3")
    assert seba1.groups.filter(name="Kierownicy").exists()
    assert seba2.groups.filter(name="Magazynierzy").exists()
    assert not seba3.groups.exists()


@pytest.mark.django_db
def test_seed_demo_preenrolls_voice_pins():
    """Seed ustawia PIN-y głosowe kont demo — bez tego pokaz głosowy pada po
    re-seedzie (dzwoniący nie przejdzie bramy DTMF). Weryfikujemy przez serwis
    (verify_voice_pin), nie po surowym hashu. Używamy ``Command.DEMO_VOICE_PINS``
    (ten sam obiekt, który wczytał seed) → test jest odporny na env vs placeholder."""
    from accounts.services import verify_voice_pin
    from core.management.commands.seed_demo import Command

    call_command(
        "seed_demo", "--machines", "1", "--sites", "1", "--reservations", "0", stdout=StringIO()
    )
    user_model = get_user_model()
    for username, pin in Command.DEMO_VOICE_PINS.items():
        profile = user_model.objects.get(username=username).profile
        assert profile.voice_pin_hash  # PIN ustawiony (hash niepusty, nie plaintext)
        assert verify_voice_pin(profile, pin)  # dokładnie ten PIN przechodzi weryfikację


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
