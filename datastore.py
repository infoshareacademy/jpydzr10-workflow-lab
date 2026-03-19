"""
Zapis i odczyt danych z plików JSON.

Obsługa błędów:
- Brak pliku → pusta lista (bez crasha)
- Nieprawidłowy JSON → fallback na kopię .bak
- Oba uszkodzone → DataCorruptionError (dane nie są nadpisywane)
- Przed każdym zapisem tworzona jest kopia zapasowa (.bak)
"""

import json
import os
import shutil
from typing import TypeVar

from exceptions import DataCorruptionError
from models import Machine, Reservation, ServiceRecord

T = TypeVar("T", Machine, Reservation, ServiceRecord)


class DataStore:
    """Zapis i odczyt danych z plików JSON."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.paths: dict[str, str] = {
            "machines": os.path.join(data_dir, "machines.json"),
            "reservations": os.path.join(data_dir, "reservations.json"),
            "service": os.path.join(data_dir, "service_records.json"),
        }

    def _load(self, path: str, cls: type[T]) -> list[T]:
        """Wczytuje listę obiektów z JSON.

        - Plik nie istnieje → pusta lista (normalna sytuacja przy pierwszym uruchomieniu)
        - Plik uszkodzony → automatyczny fallback na kopię .bak
        - Oba uszkodzone → DataCorruptionError (obsługiwany w ui.py przez _safe_load)

        Raises:
            DataCorruptionError: Gdy główny plik i kopia .bak są oba nieczytelne.
                Aplikacja NIE nadpisuje uszkodzonych plików — dane pozostają
                na dysku do ręcznej naprawy.
        """
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [cls.from_dict(item) for item in json.load(f)]
        except (json.JSONDecodeError, KeyError, ValueError):
            bak_path = path + ".bak"
            if os.path.exists(bak_path):
                try:
                    with open(bak_path, "r", encoding="utf-8") as f:
                        return [cls.from_dict(item) for item in json.load(f)]
                except (json.JSONDecodeError, KeyError, ValueError) as bak_err:
                    raise DataCorruptionError(path, bak_err) from bak_err
            raise DataCorruptionError(path, Exception(f"Brak pliku .bak dla {path}"))

    def _save(self, path: str, items: list[T]) -> None:
        """Zapisuje listę obiektów do JSON.

        Tworzy kopię zapasową (.bak) istniejącego pliku przed nadpisaniem,
        żeby chronić dane przed utratą w razie awarii.
        """
        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                [item.to_dict() for item in items], f, indent=2, ensure_ascii=False
            )

    # --- Load ---

    def load_machines(self) -> list[Machine]:
        return self._load(self.paths["machines"], Machine)

    def load_reservations(self) -> list[Reservation]:
        return self._load(self.paths["reservations"], Reservation)

    def load_service_records(self) -> list[ServiceRecord]:
        return self._load(self.paths["service"], ServiceRecord)

    # --- Save (celowany zapis — nie nadpisuje niepowiązanych plików) ---

    def save_machines(self, machines: list[Machine]) -> None:
        self._save(self.paths["machines"], machines)

    def save_reservations(self, reservations: list[Reservation]) -> None:
        self._save(self.paths["reservations"], reservations)

    def save_service_records(self, records: list[ServiceRecord]) -> None:
        self._save(self.paths["service"], records)

    # --- Import ---

    def import_machines(self, filepath: str = "machines_db.json") -> dict[str, int]:
        """Importuje maszyny z zewnętrznego pliku.

        Defensywny import: uszkodzone rekordy są logowane i pomijane,
        zamiast przerywać cały import.

        Returns:
            Słownik z kluczami: imported (udane), skipped (pominięte),
            skipped_details (lista opisów pominiętych rekordów)

        Raises:
            FileNotFoundError: Gdy plik źródłowy nie istnieje
            ValueError: Gdy plik nie zawiera prawidłowego JSON
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Plik nie istnieje: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Plik {filepath} nie zawiera prawidłowego JSON: {e}") from e

        if not isinstance(raw, list):
            raise ValueError(
                f"Plik {filepath} powinien zawierać listę JSON ([...]), "
                f"a zawiera: {type(raw).__name__}"
            )

        existing = {m.uid: m for m in self.load_machines()}
        imported = 0
        skipped = 0
        skipped_details: list[str] = []

        for i, item in enumerate(raw):
            try:
                m = Machine.from_dict(item)
                existing[m.uid] = m
                imported += 1
            except (ValueError, KeyError) as e:
                skipped_details.append(f"Rekord #{i + 1}: {e}")
                skipped += 1

        self.save_machines(list(existing.values()))
        return {"imported": imported, "skipped": skipped, "skipped_details": skipped_details}
