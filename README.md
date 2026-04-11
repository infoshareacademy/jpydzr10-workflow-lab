# Planer Maszyn Budowlanych

Aplikacja konsolowa do zarządzania rezerwacjami maszyn budowlanych w firmie.
Projekt zaliczeniowy — Milestone 1 (aplikacja konsolowa).

## Uruchomienie

```bash
python3 main.py
```

Przy starcie aplikacja uruchamia automatyczną synchronizację statusów,
następnie pokazuje menu główne z 11 opcjami.

## Testy

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pytest
python -m pytest test_*.py -v
```

Wynik (175 testów w ~0.1 s):

| Plik                          | Liczba testów | Zakres                                           |
|-------------------------------|---------------|--------------------------------------------------|
| `test_logic.py`               | 17            | Konflikty rezerwacji, synchronizacja statusów    |
| `test_models.py`              | 32            | Machine, Reservation, ServiceRecord — walidacja  |
| `test_utils_and_datastore.py` | 22            | parse_date, generate_id, DataStore, import       |
| `test_integration.py`         | 67            | Scenariusze end-to-end, edge cases, Hard Return  |
| `test_demo_data.py`           | 37            | Walidacja spójności danych demo w `data/`        |
| **Razem**                     | **175**       |                                                  |

## Wymagania

- Python 3.10+
- Brak zewnętrznych zależności runtime (tylko standardowa biblioteka)
- `pytest>=8.0` (opcjonalnie, do uruchomienia testów)
- `ruff>=0.8` (opcjonalnie, do lintowania)

## Struktura projektu

| Plik                          | Opis                                               |
|-------------------------------|----------------------------------------------------|
| `main.py`                     | Punkt wejścia aplikacji                            |
| `models.py`                   | Modele danych: Machine, Reservation, ServiceRecord |
| `datastore.py`                | Zapis/odczyt JSON, atomowy zapis, kopie `.bak`     |
| `logic.py`                    | Logika biznesowa: konflikty, synchronizacja        |
| `ui.py`                       | Interfejs konsolowy: menu, formularze, input       |
| `utils.py`                    | Wspólne narzędzia: parse_date, generate_id         |
| `exceptions.py`               | Wyjątki specyficzne dla aplikacji                  |
| `conftest.py`                 | Pusty marker pytest (pythonpath w `pyproject.toml`)|
| `pyproject.toml`              | Konfiguracja projektu, pytest, ruff                |
| `test_models.py`              | Testy modeli danych                                |
| `test_logic.py`               | Testy logiki biznesowej                            |
| `test_utils_and_datastore.py` | Testy narzędzi i warstwy persystencji              |
| `test_integration.py`         | Testy integracyjne — scenariusze end-to-end        |
| `test_demo_data.py`           | Testy walidujące spójność danych demo              |
| `machines_db.json`            | Dane maszyn do importu (opcja 10 w menu)           |
| `data/machines.json`          | Maszyny — zapisywane przez aplikację               |
| `data/reservations.json`      | Rezerwacje — zapisywane przez aplikację            |
| `data/service_records.json`   | Wpisy serwisowe — zapisywane przez aplikację       |

## Menu główne

| Opcja | Funkcja                        | Opis                                          |
|:-----:|--------------------------------|-----------------------------------------------|
|   1   | Lista maszyn                   | Wyświetla maszyny z oznaczeniami przeglądów   |
|   2   | Rezerwacje                     | Grupuje rezerwacje po statusie                |
|   3   | Nowa rezerwacja                | Tworzy rezerwację z wykrywaniem konfliktów    |
|   4   | Zwrot maszyny                  | Zwrot do magazynu + zamknięcie rezerwacji     |
|   5   | Edycja maszyny                 | Aktualizacja pól maszyny                      |
|   6   | Edycja rezerwacji              | Zmiana osoby, projektu, adresu, daty końca    |
|   7   | Anulowanie rezerwacji          | Anuluje rezerwację + zwalnia maszynę          |
|   8   | Serwis — dodaj wpis            | Przegląd lub naprawa (z kosztem i terminem)   |
|   9   | Serwis — historia i koszty     | Wpisy + łączny koszt (opcjonalny filtr UID)   |
|  10   | Import maszyn z pliku          | Import z JSON (z pomijaniem uszkodzonych)     |
|  11   | Synchronizacja statusów        | Ręczne uruchomienie daily sync                |
|   0   | Wyjście                        | Zapisuje zmienione kolekcje i kończy pracę    |

## Mapowanie nazw Python → JSON

Pola w Pythonie używają `snake_case`, w JSON `camelCase` (dla kompatybilności
z frontendem w Milestone 2):

| Python            | JSON             |
|-------------------|------------------|
| `machine_type`    | `type`           |
| `inspection_date` | `inspectionDate` |
| `serial_number`   | `serialNumber`   |
| `build_year`      | `buildYear`      |
| `machine_id`      | `machineId`      |
| `start_date`      | `startDate`      |
| `end_date`        | `endDate`        |
| `project_number`  | `projectNumber`  |
| `record_date`     | `date`           |
| `record_type`     | `type`           |
| `next_inspection` | `nextInspection` |

## Statusy maszyn

Zdefiniowane w `Machine.VALID_STATUSES`:

| Status          | Znaczenie                                             |
|-----------------|-------------------------------------------------------|
| `W magazynie`   | Dostępna do rezerwacji                                |
| `Zarezerwowana` | Ma potwierdzoną rezerwację w przyszłości              |
| `Na budowie`    | Rezerwacja aktualnie aktywna (start ≤ dziś ≤ end)     |
| `W serwisie`    | W naprawie/przeglądzie — wyłączona z automatyki syncu |

## Statusy rezerwacji

Zdefiniowane w `Reservation.VALID_STATUSES`:

| Status         | Znaczenie                                     |
|----------------|-----------------------------------------------|
| `oczekująca`   | Utworzona, wymaga potwierdzenia               |
| `potwierdzona` | Aktywna — uczestniczy w konfliktach i syncu   |
| `zakończona`   | Maszyna wróciła do magazynu                   |
| `anulowana`    | Anulowana — nie blokuje terminu ani konflitu  |

## Synchronizacja statusów (Hard Return Policy)

Funkcja `run_daily_sync` (w `logic.py`) uruchamiana automatycznie przy starcie
aplikacji oraz ręcznie przez opcję 11 w menu. Reguły w kolejności priorytetu:

1. **Maszyny `W serwisie`** — pomijane (serwis ma pierwszeństwo nad automatyką).
2. **Rezerwacja aktywna** (`start ≤ dziś ≤ end`) → maszyna `Na budowie`,
   lokalizacja z adresu rezerwacji.
3. **Rezerwacja przeterminowana** (`end < dziś`, maszyna wciąż `Na budowie`) →
   **Hard Return Policy**: `end_date` przedłużana do dziś (maszyna nie wróciła
   do magazynu, rezerwacja zostaje otwarta).
4. **Rezerwacja przeterminowana** (`end < dziś`, maszyna `Zarezerwowana`) →
   zwrot do magazynu (rezerwacja minęła bez aktywacji).
5. **Rezerwacja w przyszłości** (`start > dziś`, maszyna `W magazynie`) →
   status `Zarezerwowana`.

Dwuprzebiegowa pętla zapewnia niezależność wyniku od kolejności rezerwacji.
Zwracany słownik: `{"updated": int, "extended": int, "reserved": int}`.

## Obsługa błędów danych

Strategia "bezpieczeństwo danych ponad wygodę":

1. **Brak pliku** → pusta lista (normalne przy pierwszym uruchomieniu).
2. **Uszkodzony JSON** → automatyczny fallback na kopię `.bak`.
3. **Oba uszkodzone** → `DataCorruptionError` → czytelny komunikat w konsoli,
   kontynuacja z pustą listą. Uszkodzone pliki **NIE są nadpisywane** —
   pozostają na dysku do ręcznej naprawy.
4. **Import z błędnymi rekordami** → uszkodzone rekordy są logowane i pomijane,
   poprawne importowane normalnie.
5. **Atomowy zapis** → zapis do pliku `.tmp`, potem `rename` + backup `.bak`.
   Crash w trakcie zapisu nie uszkodzi ani głównego pliku, ani kopii.
6. **Błąd I/O przy wczytywaniu** (`OSError`) → `App._safe_load` wyświetla
   komunikat i kontynuuje z pustą listą dla tej kolekcji.

## Walidacja danych

- UID maszyny nie może być pusty/whitespace (walidacja w `Machine.__init__`).
- ID rezerwacji i wpisu serwisowego nie mogą być puste.
- Statusy maszyn, rezerwacji i typy wpisów serwisowych walidowane przez
  `@property` + setter.
- Wymagane pola formularzy (osoba, numer projektu) wymuszane przez
  `input_required()` w UI.
- Koszty serwisowe nie mogą być ujemne (walidacja w `add_service_record`);
  kwoty parsowane z polskiej notacji (przecinek jako separator).
- Unikalne ID generowane z limitem prób (`generate_unique_id`, max 1000).
- Stykające się daty rezerwacji traktowane jako konflikt — maszyna potrzebuje
  dnia na transport i przygotowanie.
- Rezerwacje z pustymi datami pomijane przez sync i conflict check (guard).

## Funkcjonalności

- Przeglądanie listy maszyn z oznaczeniami przeglądów technicznych
  (`[!]` ≤ 14 dni, `[PRZEGLĄD!]` przeterminowane).
- Tworzenie, edycja i anulowanie rezerwacji z wykrywaniem konfliktów.
- Walidacja wymaganych pól (osoba, numer projektu).
- Zwrot maszyn do magazynu z automatycznym zamknięciem bieżących rezerwacji
  (maszyna z przyszłą rezerwacją po zwrocie → `Zarezerwowana`).
- Rejestrowanie napraw i przeglądów z automatycznym obliczaniem terminu
  następnego przeglądu.
- Import maszyn z zewnętrznego pliku JSON (defensywny — pomija uszkodzone).
- Automatyczna synchronizacja statusów przy starcie (Hard Return Policy).
- Grupowanie rezerwacji po statusie przy wyświetlaniu.
- Historia serwisowa z łącznym kosztem (opcjonalny filtr po UID maszyny).
- Kopie zapasowe `.bak` przed każdym zapisem.
- Celowane zapisy (tylko zmienione pliki) z flagami `_dirty`.
- Graceful handling `Ctrl+C` i `EOF` — zapis i elegancki exit.

## Type Hints

Moduły `logic.py`, `datastore.py`, `utils.py` i `ui.py` posiadają adnotacje
typów (PEP 484), co ułatwia statyczną analizę kodu (mypy) i wsparcie edytora.
Przygotowanie pod migrację do Django + Pydantic w Milestone 2.

## Dane

Katalog `data/` zawiera dane demo zatwierdzone do repozytorium. Przy pierwszym
uruchomieniu aplikacji w czystym środowisku katalog jest tworzony automatycznie.

Pliki zapisywane przez aplikację:
- `data/machines.json`
- `data/reservations.json`
- `data/service_records.json`

Każdemu z nich towarzyszy kopia `.bak` tworzona przy drugim i kolejnych zapisach.

Aby zaimportować dodatkowe maszyny, umieść plik `machines_db.json` w katalogu
projektu i użyj opcji **10** z menu. Import jest idempotentny (istniejące UID
zostają zaktualizowane, nowe dodane).

## Narzędzia deweloperskie

- **pytest** (konfiguracja w `pyproject.toml` → `[tool.pytest.ini_options]`,
  `pythonpath = ["."]`, `addopts = "-v --tb=short"`).
- **ruff** — linter + formatter (zastępuje flake8, isort, black).
  Konfiguracja w `pyproject.toml` → `[tool.ruff]`, target `py310`, line-length
  100, reguły: pycodestyle, pyflakes, isort, pep8-naming, pyupgrade, bugbear,
  simplify, ruff-specific.

## Tech Debt (do rozwiązania w Milestone 2)

- `float` → `DecimalField` dla kosztów serwisowych.
- `calculate_next_inspection`: 30 dni/miesiąc → `dateutil.relativedelta`.
- Daty przechowywane jako stringi → obiekt `date` w atrybutach klas
  (serializacja do stringa tylko w `to_dict()`).
- `VALID_STATUSES` krotki → Django `TextChoices` / `enum.Enum`.
- Walidacja `end_date >= start_date` w konstruktorze `Reservation`
  (obecnie chroni tylko UI, nie bezpośrednie tworzenie obiektów).
- Migracja persystencji z JSON na ORM (Django models).
- Zastąpienie CLI frontendem webowym (Django views + templates).
