"""Testy narzędzi i warstwy persystencji."""

import json
import os

import pytest

from datastore import DataStore
from exceptions import DataCorruptionError
from models import Machine
from utils import generate_id, generate_unique_id, parse_date

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
        assert len(generate_id("RES-")) == 12

    def test_unique(self):
        ids = {generate_id("RES-") for _ in range(100)}
        assert len(ids) == 100


class TestGenerateUniqueId:
    def test_avoids_existing(self):
        existing = {"RES-AAAAAAAA", "RES-BBBBBBBB"}
        new_id = generate_unique_id("RES-", existing)
        assert new_id not in existing
        assert new_id.startswith("RES-")

    def test_max_attempts_raises(self):
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
        return DataStore(data_dir=str(tmp_path))

    def test_load_empty(self, tmp_store):
        machines = tmp_store.load_machines()
        assert machines == []

    def test_save_and_load(self, tmp_store):
        machines = [
            Machine("M001", "Koparka", "koparka"),
            Machine("M002", "Ładowarka", "ładowarka"),
        ]
        tmp_store.save_machines(machines)
        loaded = tmp_store.load_machines()
        assert len(loaded) == 2
        assert loaded[0].uid == "M001"
        assert loaded[1].uid == "M002"

    def test_backup_created(self, tmp_store):
        machines = [Machine("M001", "Koparka", "koparka")]
        tmp_store.save_machines(machines)

        machines.append(Machine("M002", "Ładowarka", "ładowarka"))
        tmp_store.save_machines(machines)

        bak_path = tmp_store.paths["machines"] + ".bak"
        assert os.path.exists(bak_path)

        with open(bak_path) as f:
            bak_data = json.load(f)
        assert len(bak_data) == 1

    def test_corrupted_json_falls_back_to_bak(self, tmp_store):
        machines = [Machine("M001", "Koparka", "koparka")]
        tmp_store.save_machines(machines)
        tmp_store.save_machines(machines)

        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN JSON")

        loaded = tmp_store.load_machines()
        assert len(loaded) == 1
        assert loaded[0].uid == "M001"

    def test_both_corrupted_raises(self, tmp_store):
        machines = [Machine("M001", "Koparka", "koparka")]
        tmp_store.save_machines(machines)
        tmp_store.save_machines(machines)

        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN")
        with open(tmp_store.paths["machines"] + ".bak", "w") as f:
            f.write("{{{ALSO BROKEN")

        with pytest.raises(DataCorruptionError):
            tmp_store.load_machines()

    def test_corrupted_no_bak_raises(self, tmp_store):
        machines = [Machine("M001", "Koparka", "koparka")]
        tmp_store.save_machines(machines)

        with open(tmp_store.paths["machines"], "w") as f:
            f.write("{{{BROKEN")

        with pytest.raises(DataCorruptionError):
            tmp_store.load_machines()

    # --- Import ---

    def test_import_machines(self, tmp_store, tmp_path):
        source = [
            {
                "uid": "M001", "name": "Koparka",
                "type": "koparka", "status": "W magazynie",
            },
            {
                "uid": "M002", "name": "Ładowarka",
                "type": "ładowarka", "status": "W magazynie",
            },
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
        tmp_store.save_machines(
            [Machine("M001", "Koparka", "koparka")]
        )

        source = [
            {
                "uid": "M001", "name": "Koparka v2",
                "type": "koparka", "status": "W magazynie",
            },
        ]
        source_path = str(tmp_path / "import.json")
        with open(source_path, "w") as f:
            json.dump(source, f)

        tmp_store.import_machines(source_path)
        loaded = tmp_store.load_machines()
        assert len(loaded) == 1
        assert loaded[0].name == "Koparka v2"

    def test_import_skips_invalid_records(self, tmp_store, tmp_path):
        source = [
            {
                "uid": "M001", "name": "Koparka",
                "type": "koparka", "status": "W magazynie",
            },
            {
                "uid": "", "name": "Brak UID",
                "type": "koparka", "status": "W magazynie",
            },
            {
                "uid": "M003", "name": "Ładowarka",
                "type": "ładowarka", "status": "BZDURA",
            },
            {
                "uid": "M002", "name": "Wywrotka",
                "type": "wywrotka", "status": "W magazynie",
            },
        ]
        source_path = str(tmp_path / "import.json")
        with open(source_path, "w") as f:
            json.dump(source, f)

        result = tmp_store.import_machines(source_path)
        assert result["imported"] == 2
        assert result["skipped"] == 2

        loaded = tmp_store.load_machines()
        assert len(loaded) == 2
        uids = {m.uid for m in loaded}
        assert "M001" in uids
        assert "M002" in uids

    def test_import_file_not_found(self, tmp_store):
        with pytest.raises(FileNotFoundError):
            tmp_store.import_machines("/nonexistent/path/machines.json")

    def test_import_invalid_json(self, tmp_store, tmp_path):
        bad_path = str(tmp_path / "broken.json")
        with open(bad_path, "w") as f:
            f.write("{{{NOT VALID JSON")

        with pytest.raises(ValueError, match="nie zawiera prawidłowego JSON"):
            tmp_store.import_machines(bad_path)

    def test_import_json_dict_instead_of_list(self, tmp_store, tmp_path):
        dict_path = str(tmp_path / "dict.json")
        with open(dict_path, "w") as f:
            json.dump({"uid": "M001", "name": "Koparka"}, f)

        with pytest.raises(ValueError, match="powinien zawierać listę"):
            tmp_store.import_machines(dict_path)
