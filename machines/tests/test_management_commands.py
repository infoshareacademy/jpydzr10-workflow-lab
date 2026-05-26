"""Tests dla machines management commands.

Pokrywa:

* ``seed_machines`` — idempotencja, ``--count``, ``--force``.
* ``import_machines`` — JSON import, error paths (file missing, bad JSON,
  ``--skip-existing``, duplicate UID).
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from machines.models import Machine

# =============================================================================
# seed_machines command
# =============================================================================


@pytest.mark.django_db
class TestSeedMachinesCommand:
    """``seed_machines`` — generuje demo maszyny z factory_boy."""

    def test_creates_default_count_when_empty(self):
        """Pusta baza → tworzy domyślną ilość (20) maszyn."""
        out = StringIO()
        call_command("seed_machines", stdout=out)
        assert Machine.objects.count() == 20
        assert "Utworzono" in out.getvalue()

    def test_skips_when_db_non_empty(self):
        """Niepusta baza → pomija seed (idempotency)."""
        Machine.objects.create(
            uid="EXISTING-001",
            name="Existing",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        out = StringIO()
        call_command("seed_machines", stdout=out)
        # Tylko 1 istniejąca maszyna — seed nie dodał nowych.
        assert Machine.objects.count() == 1
        assert "pomijam" in out.getvalue()

    def test_force_seeds_even_if_non_empty(self):
        """``--force`` dosypuje mimo istniejących maszyn."""
        Machine.objects.create(
            uid="EXISTING-001",
            name="Existing",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        out = StringIO()
        call_command("seed_machines", count=10, force=True, stdout=out)
        # Co najmniej 11 (1 istniejąca + 10 nowych).
        assert Machine.objects.count() >= 11

    def test_custom_count(self):
        """``--count=N`` tworzy N maszyn."""
        out = StringIO()
        call_command("seed_machines", count=15, stdout=out)
        assert Machine.objects.count() == 15


# =============================================================================
# import_machines command
# =============================================================================


@pytest.mark.django_db
class TestImportMachinesCommand:
    """``import_machines`` — JSON bulk import."""

    def test_raises_command_error_when_file_missing(self):
        """Nieistniejąca ścieżka → ``CommandError``."""
        with pytest.raises(CommandError, match="nie istnieje"):
            call_command("import_machines", "/tmp/definitely-no-such-file-3267.json")

    def test_raises_command_error_on_bad_json(self, tmp_path):
        """Niepoprawny JSON → ``CommandError`` z "Niepoprawny JSON"."""
        bad = tmp_path / "bad.json"
        bad.write_text("not a json {")
        with pytest.raises(CommandError, match="Niepoprawny JSON"):
            call_command("import_machines", str(bad))

    def test_raises_command_error_when_payload_not_list(self, tmp_path):
        """JSON dict zamiast list → ``CommandError``."""
        bad = tmp_path / "dict.json"
        bad.write_text(json.dumps({"not": "a list"}))
        with pytest.raises(CommandError, match="listy"):
            call_command("import_machines", str(bad))

    def test_imports_valid_machines(self, tmp_path):
        """Happy path: poprawny JSON tworzy maszyny."""
        payload = [
            {
                "uid": "IMP-001",
                "name": "Importowana koparka",
                "type": "koparka",
                "model": "JCB-XYZ",
                "capacity": 5000,
                "manufacturer": "JCB",
                "serialNumber": "SN-001",
                "buildYear": 2020,
            },
            {
                "uid": "IMP-002",
                "name": "Importowana minikoparka",
                "type": "minikoparka",
                "capacity": 2000,
                "buildYear": 2021,
            },
        ]
        good = tmp_path / "good.json"
        good.write_text(json.dumps(payload))
        out = StringIO()
        call_command("import_machines", str(good), stdout=out, stderr=StringIO())
        assert Machine.objects.filter(uid="IMP-001").exists()
        assert Machine.objects.filter(uid="IMP-002").exists()
        assert "utworzono 2" in out.getvalue()

    def test_skips_records_without_uid(self, tmp_path):
        """Wpis bez UID → pominięty (WARNING)."""
        payload = [
            {"name": "Bez UID"},  # brak uid
            {"uid": "IMP-OK", "name": "Z UID", "type": "koparka", "capacity": 1000},
        ]
        good = tmp_path / "mixed.json"
        good.write_text(json.dumps(payload))
        out = StringIO()
        err = StringIO()
        call_command("import_machines", str(good), stdout=out, stderr=err)
        assert "bez UID" in err.getvalue()
        assert Machine.objects.filter(uid="IMP-OK").exists()

    def test_duplicate_uid_with_skip_existing(self, tmp_path):
        """``--skip-existing`` pomija duplikaty bez błędu."""
        Machine.objects.create(
            uid="DUP-001",
            name="Already",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        payload = [{"uid": "DUP-001", "name": "Próba", "type": "koparka", "capacity": 1000}]
        f = tmp_path / "dup.json"
        f.write_text(json.dumps(payload))
        out = StringIO()
        call_command(
            "import_machines",
            str(f),
            "--skip-existing",
            stdout=out,
            stderr=StringIO(),
        )
        # Tylko jedna maszyna — duplikat pominięty.
        assert Machine.objects.filter(uid="DUP-001").count() == 1
        assert "pominięto 1" in out.getvalue()

    def test_duplicate_uid_without_skip_existing_reports_warning(self, tmp_path):
        """Bez ``--skip-existing`` duplikat raportuje WARNING ale nie crashuje."""
        Machine.objects.create(
            uid="DUP-002",
            name="Already",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        payload = [{"uid": "DUP-002", "name": "Próba", "type": "koparka", "capacity": 1000}]
        f = tmp_path / "dup2.json"
        f.write_text(json.dumps(payload))
        out = StringIO()
        err = StringIO()
        call_command("import_machines", str(f), stdout=out, stderr=err)
        assert "Duplikat" in err.getvalue()

    def test_invalid_data_reports_error_continues(self, tmp_path):
        """Wpis z błędnymi danymi → ERROR, ale import kontynuuje dla pozostałych."""
        payload = [
            # Pierwszy entry z błędnym build_year (nie int).
            {"uid": "BAD-1", "name": "x", "type": "koparka", "capacity": 1000, "buildYear": "abc"},
            # Drugi OK.
            {"uid": "OK-2", "name": "OK", "type": "koparka", "capacity": 1000, "buildYear": 2020},
        ]
        f = tmp_path / "mixed.json"
        f.write_text(json.dumps(payload))
        out = StringIO()
        err = StringIO()
        call_command("import_machines", str(f), stdout=out, stderr=err)
        # Drugi powinien być utworzony.
        assert Machine.objects.filter(uid="OK-2").exists()
        # Pierwszy NIE — błąd parsowania (mapuje na ``int(...)`` rzucający ValueError).
        # Output zawiera "Błąd przy BAD-1" w stderr.
        assert "BAD-1" in err.getvalue()
