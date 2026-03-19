# Planer Maszyn Budowlanych

Aplikacja konsolowa do zarządzania rezerwacjami maszyn budowlanych w firmie.
Projekt zaliczeniowy — Milestone 1 (aplikacja konsolowa).

## Uruchomienie

```bash
python3 main.py
```

## Testy

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pytest
python -m pytest test_*.py -v
```

Wynik (65 testów):
```
test_logic.py          — konflikty, synchronizacja statusów (17 testów)
test_models.py         — Machine, Reservation, ServiceRecord (18 testów)
test_utils_and_datastore.py — parse_date, generate_id, DataStore, import (30 testów)
```

## Wymagania

- Python 3.10+
- Brak zewnętrznych bibliotek (tylko standardowa biblioteka)
- pytest (opcjonalnie, do uruchomienia testów)

## Struktura projektu

| Plik                          | Opis                                              |
|-------------------------------|----------------------------------------------------|
| `main.py`                     | Punkt wejścia aplikacji                            |
| `models.py`                   | Modele danych: Machine, Reservation, ServiceRecord |
| `datastore.py`                | Zapis/odczyt JSON + kopie zapasowe (.bak)          |
| `logic.py`                    | Logika biznesowa: konflikty, synchronizacja        |
| `ui.py`                       | Interfejs konsolowy: menu, formularze, input       |
| `utils.py`                    | Wspólne narzędzia: parse_date, generate_id         |
| `exceptions.py`               | Wyjątki specyficzne dla aplikacji                  |
| `conftest.py`                 | Konfiguracja pytest (PYTHONPATH)                   |
| `test_models.py`              | Testy modeli danych                                |
| `test_logic.py`               | Testy logiki biznesowej                            |
| `test_utils_and_datastore.py` | Testy narzędzi i warstwy persystencji              |
| `machines_db.json`            | Dane maszyn do importu (opcja 10 w menu)           |

## Mapowanie nazw Python → JSON

Pola w Pythonie używają `snake_case`, w JSON `camelCase` (dla kompatybilności z frontendem w Milestone 2):

| Python            | JSON              |
|-------------------|-------------------|
| `machine_type`    | `type`            |
| `inspection_date` | `inspectionDate`  |
| `machine_id`      | `machineId`       |
| `start_date`      | `startDate`       |
| `end_date`        | `endDate`         |
| `project_number`  | `projectNumber`   |
| `record_type`     | `type`            |
| `next_inspection` | `nextInspection`  |

## Statusy maszyn

| Status           | Znaczenie                                |
|------------------|------------------------------------------|
| `In Magazijn`    | W magazynie, dostępna do rezerwacji       |
| `Gereserveerd`   | Zarezerwowana na przyszły termin          |
| `Op de werf`     | Na budowie (rezerwacja aktywna)           |
| `In Herstelling` | W serwisie (wyłączona z automatycznej synchronizacji) |

## Obsługa błędów danych

Aplikacja stosuje strategię "bezpieczeństwo danych ponad wygodę":

1. **Brak pliku** → pusta lista (normalne przy pierwszym uruchomieniu)
2. **Uszkodzony JSON** → automatyczny fallback na kopię `.bak`
3. **Oba uszkodzone** → `DataCorruptionError` → czytelny komunikat w konsoli, kontynuacja z pustą listą. Uszkodzone pliki NIE są nadpisywane — pozostają na dysku do ręcznej naprawy.
4. **Import z błędnymi rekordami** → uszkodzone rekordy są logowane i pomijane, poprawne rekordy importowane normalnie.

## Walidacja danych

- UID maszyny nie może być pusty (walidacja w `__init__`)
- ID rezerwacji i wpisu serwisowego nie mogą być puste (walidacja w `__init__`)
- Statusy maszyn i rezerwacji walidowane przez `@property` + setter
- Wymagane pola formularzy (osoba, numer projektu) wymuszane przez `input_required()`
- Koszty serwisowe nie mogą być ujemne (walidacja w `add_service_record`)
- Unikalne ID generowane z limitem prób (`generate_unique_id`)
- Stykające się daty rezerwacji traktowane jako konflikt (maszyna potrzebuje transportu)

## Funkcjonalności

- Przeglądanie listy maszyn z oznaczeniami przeglądów technicznych
- Tworzenie, edycja i anulowanie rezerwacji z wykrywaniem konfliktów
- Walidacja wymaganych pól (osoba, numer projektu)
- Zwrot maszyn do magazynu z automatycznym zamknięciem bieżących rezerwacji
- Rejestrowanie napraw i przeglądów z automatycznym obliczaniem terminów
- Import maszyn z zewnętrznego pliku JSON (z pomijaniem uszkodzonych rekordów)
- Automatyczna synchronizacja statusów (Hard Return Policy)
- Status `Gereserveerd` dla maszyn z rezerwacją w przyszłości
- Kopie zapasowe (.bak) przed każdym zapisem
- Celowane zapisy (tylko zmienione pliki, nie wszystkie) z flagami `_dirty`

## Type Hints

Moduły `logic.py`, `datastore.py`, `utils.py` i `ui.py` posiadają adnotacje typów
(PEP 484), co ułatwia statyczną analizę kodu (mypy) i wsparcie edytora.
Przygotowanie pod migrację do Django + Pydantic w Milestone 2.

## Dane

Katalog `data/` tworzony automatycznie przy pierwszym zapisie.
Pliki: `machines.json`, `reservations.json`, `service_records.json`.

Aby zaimportować maszyny, umieść plik `machines_db.json` w katalogu projektu
i użyj opcji 10 z menu.

## Tech Debt (do rozwiązania w Milestone 2)

- `float` → `DecimalField` dla kosztów serwisowych
- `calculate_next_inspection`: 30 dni/miesiąc → `dateutil.relativedelta`
- `conftest.py`: `sys.path` hack → `pyproject.toml` z `[tool.pytest.ini_options]`
- Daty przechowywane jako stringi → obiekt `date` w atrybutach klas
- `VALID_STATUSES` krotki → Django `TextChoices` / enum
- Walidacja `end_date >= start_date` w konstruktorze `Reservation` (teraz chroni tylko UI)
