"""Testy narzędzi i warstwy persystencji."""

import json
import os
import tempfile

import pytest
from utils import parse_date, generate_id, generate_unique_id
from datastore import DataStore
from exceptions import DataCorruptionError
from models import Machine


# =============================================================================
# utils
# =============================================================================


class TestParseDate:
    def test_valid_date(self):
        d = parse_date("2025-04-01")
        assert d.year == 2025
        assert d.month == 4
        assert d.day == 1

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_date("01-04-2025")

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            parse_date("2025-13-01")


class TestGenerateId:
    def test_has_prefix(self):
        assert generate_id("RES-").startswith("RES-")

    def test_length(self):
        # prefix (4) + 8 hex chars = 12
        assert len(generate_id("RES-")) == 12

    def test_unique(self):
        ids = {generate_id("RES-") for _ in range(100)}
        assert len(ids) == 100  # wszystkie unikalne


class TestGenerateUniqueId:
    def test_avoids_existing(self):
        existing = {"RES-AAAAAAAA", "RES-BBBBBBBB"}
        new_id = generate_unique_id("RES-", existing)
        assert new_id not in existing
        assert new_id.startswith("RES-")

    def test_max_attempts_raises(self):
        """Przy wyczerpaniu prób powinien rzucić RuntimeError."""
        # Sztuczka: podajemy set tak duży, że każdy ID jest "zajęty"
        # (w praktyce niemożliwe, ale testujemy mechanizm limitu)
        class AlwaysContains:
            def __contains__(self, item):
                return True

        with pytest.raises(RuntimeError, match="Nie udało się wygenerować"):
            generate_unique_id("RES-", AlwaysContains(), max_attempts=5)


# =============================================================================
# DataStore
# =============================================================================


class TestDataStore:
    @pytest.fixture
    def tmp_store(self, tmp_path):
        """Tworzy DataStore z tymczasowym katalogiem."""
        return DataStore(data_dir=str(tmp_path))

    def test_load_empty(self, tmp_store):
        machines = tmp_store.load_machines()
        assert machines == []

    def test_save_and_load(self, tmp_store):
        machines = [
            Machine("M001", "Dźwig", "crane"),
            Machine("M002", "Koparka", "excavator"),
        ]
        tmp_store.save_machines(machines)
        loaded = tmp_store.load_machines()
        assert len(loaded) == 2
        assert loaded[0].uid == "M001"
        assert loaded[1].uid == "M002"

    def test_backup_created(self, tmp_store):
        machines = [Machine("M001", "Dźwig", "crane")]
        tmp_store.save_machines(machines)

        # Drugie zapisanie — powinno utworzyć .bak
        machines.append(Machine("M002", "Koparka", "excavator"))
        tmp_store.save_machines(machines)

        bak_path = tmp_store.paths["machines"] + ".bak"
        assert os.path.exists(bak_path)

        # .bak powinien mieć starą wersję (1 maszyna)
        with open(bak_path, "r") as f:
            bak_data = json.load(f)
        assert len(bak_data) == 1

    def test_corrupted_json_falls_back_to_bak(self, tmp_store):
        # Zapisz poprawne dane
        machines = [Machine("M001", "Dźwig", "crane")]
        tmp_store.save_machines(machines)

        # Zapisz ponownie (tworzy .bak)
        tmp_store.save_machines(machines)

        # Uszkodź główny plik
        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN JSON")

        # Powinien wczytać z .bak
        loaded = tmp_store.load_machines()
        assert len(loaded) == 1
        assert loaded[0].uid == "M001"

    # --- Nowy test: podwójna awaria (oba pliki uszkodzone) ---

    def test_both_corrupted_raises_data_corruption_error(self, tmp_store):
        """Gdy główny plik i .bak są oba uszkodzone → DataCorruptionError."""
        machines = [Machine("M001", "Dźwig", "crane")]
        tmp_store.save_machines(machines)
        tmp_store.save_machines(machines)  # tworzy .bak

        # Uszkodź oba pliki
        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN")
        with open(tmp_store.paths["machines"] + ".bak", "w") as f:
            f.write("{{{ALSO BROKEN")

        with pytest.raises(DataCorruptionError):
            tmp_store.load_machines()

    def test_corrupted_no_bak_raises_data_corruption_error(self, tmp_store):
        """Gdy główny plik uszkodzony i brak .bak → DataCorruptionError."""
        # Zapisz raz (bez .bak)
        machines = [Machine("M001", "Dźwig", "crane")]
        tmp_store.save_machines(machines)

        # Uszkodź główny plik
        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN")

        with pytest.raises(DataCorruptionError):
            tmp_store.load_machines()

    # --- Import ---

    def test_import_machines(self, tmp_store, tmp_path):
        # Utwórz plik źródłowy
        source = [
            {"uid": "M001", "name": "Dźwig", "type": "crane", "status": "In Magazijn"},
            {"uid": "M002", "name": "Koparka", "type": "excavator", "status": "In Magazijn"},
        ]
        source_path = str(tmp_path / "import.json")
        with open(source_path, "w") as f:
            json.dump(source, f)

        result = tmp_store.import_machines(source_path)
        assert result["imported"] == 2
        assert result["skipped"] == 0

        loaded = tmp_store.load_machines()
        assert len(loaded) == 2

    def test_import_no_duplicates(self, tmp_store, tmp_path):
        # Zapisz jedną maszynę
        tmp_store.save_machines([Machine("M001", "Dźwig", "crane")])

        # Importuj tę samą maszynę
        source = [{"uid": "M001", "name": "Dźwig Updated", "type": "crane", "status": "In Magazijn"}]
        source_path = str(tmp_path / "import.json")
        with open(source_path, "w") as f:
            json.dump(source, f)

        tmp_store.import_machines(source_path)
        loaded = tmp_store.load_machines()
        assert len(loaded) == 1
        assert loaded[0].name == "Dźwig Updated"

    # --- Nowy test: defensywny import (pominięcie uszkodzonych rekordów) ---

    def test_import_skips_invalid_records(self, tmp_store, tmp_path):
        """Uszkodzone rekordy w pliku importu nie przerywają całego importu."""
        source = [
            {"uid": "M001", "name": "Dźwig", "type": "crane", "status": "In Magazijn"},
            {"uid": "", "name": "Brak UID", "type": "crane", "status": "In Magazijn"},
            {"uid": "M003", "name": "Ładowarka", "type": "loader", "status": "BZDURA"},
            {"uid": "M002", "name": "Koparka", "type": "excavator", "status": "In Magazijn"},
        ]
        source_path = str(tmp_path / "import.json")
        with open(source_path, "w") as f:
            json.dump(source, f)

        result = tmp_store.import_machines(source_path)
        assert result["imported"] == 2  # M001 i M002
        assert result["skipped"] == 2   # pusty UID i zły status

        loaded = tmp_store.load_machines()
        assert len(loaded) == 2
        uids = {m.uid for m in loaded}
        assert "M001" in uids
        assert "M002" in uids

    # --- Import: obsługa błędów ---

    def test_import_file_not_found(self, tmp_store):
        """Import z nieistniejącego pliku → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            tmp_store.import_machines("/nonexistent/path/machines.json")

    def test_import_invalid_json(self, tmp_store, tmp_path):
        """Import z uszkodzonego pliku JSON → ValueError."""
        bad_path = str(tmp_path / "broken.json")
        with open(bad_path, "w") as f:
            f.write("{{{NOT VALID JSON")

        with pytest.raises(ValueError, match="nie zawiera prawidłowego JSON"):
            tmp_store.import_machines(bad_path)

    def test_import_json_dict_instead_of_list(self, tmp_store, tmp_path):
        """Import z JSON-em zawierającym {} zamiast [] → ValueError."""
        dict_path = str(tmp_path / "dict.json")
        with open(dict_path, "w") as f:
            json.dump({"uid": "M001", "name": "Dźwig"}, f)

        with pytest.raises(ValueError, match="powinien zawierać listę"):
            tmp_store.import_machines(dict_path)
