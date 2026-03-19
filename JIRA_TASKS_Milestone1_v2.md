# TASKI NA JIRĘ — Milestone 1 (Aplikacja konsolowa)
# Projekt: Planer Maszyn Budowlanych
# Sprint: Milestone 1 — Runda poprawek (v2)

---

## TASKI ZAMKNIĘTE (v1)

### TASK 1 ✅ DONE — Struktura projektu i modele danych (OOP)
### TASK 2 ✅ DONE — Zapis i odczyt danych z plików JSON
### TASK 3 ✅ DONE — Import maszyn z zewnętrznego pliku JSON
### TASK 4 ✅ DONE — Menu konsolowe — nawigacja i interfejs użytkownika
### TASK 5 ✅ DONE — Wyświetlanie listy maszyn ze statusami
### TASK 6 ✅ DONE — Tworzenie rezerwacji z wykrywaniem konfliktów
### TASK 7 ✅ DONE — Przegląd rezerwacji — widok z podziałem na statusy
### TASK 8 ✅ DONE — Zwrot maszyny do magazynu
### TASK 9 ✅ DONE — Hard Return Policy — automatyczne przedłużanie rezerwacji
### TASK 10 ✅ DONE — Moduł serwisowy — przeglądy i naprawy

---

## NOWE TASKI — Runda poprawek

---

### TASK 13 — TODO
**Summary:** Edycja istniejących danych z poziomu konsoli
**Type:** Feature
**Priority:** High
**Description:**
Dodanie możliwości edycji istniejących obiektów:
- Metoda `_edit` w klasie `DataStore` (obok `_load` i `_save`) — wczytanie obiektu po ID, modyfikacja, zapis
- Metoda `edit` w klasie `Machine` — edycja nazwy, modelu, lokalizacji, statusu, pojemności
- Metoda `edit` w klasie `Reservation` — edycja dat, osoby odpowiedzialnej, numeru projektu, adresu, statusu (z ponownym sprawdzeniem konfliktu dat przez `has_conflict` z `exclude_id`)
- Metoda `edit` w klasie `ServiceRecord` — edycja opisu, kosztu, typu
- Nowe ekrany w `App`: `edit_machine()`, `edit_reservation()`, `edit_service_record()`
- Nowe opcje w menu konsolowym
- Przy edycji rezerwacji: wykorzystanie istniejącego parametru `exclude_id` w `has_conflict` żeby rezerwacja nie wykrywała konfliktu sama ze sobą
- Walidacja: edytowane pola przechodzą te same walidacje co przy tworzeniu
**Acceptance Criteria:**
- Użytkownik może edytować każdy typ obiektu z poziomu menu
- Edycja rezerwacji sprawdza konflikty z pominięciem edytowanej rezerwacji
- Zmiany zapisywane do plików JSON po zatwierdzeniu
- Nieprawidłowe dane nie przechodzą walidacji

---

### TASK 14 — TODO
**Summary:** Nowa klasa Budowa (ConstructionSite) z pełną integracją
**Type:** Feature
**Priority:** High
**Description:**
Stworzenie nowej klasy reprezentującej budowę/projekt:
- Klasa `ConstructionSite` z polami:
  - `site_id` (UID budowy, generowany automatycznie)
  - `project_number` (OBOWIĄZKOWE, walidacja: dokładnie 9 cyfr)
  - `site_name` (nazwa budowy)
  - `client_name` (nazwa klienta)
  - `project_manager` (kierownik projektu)
  - `foreman` (brygadzista)
  - `address` (adres budowy)
  - `status` (active / completed / cancelled)
- Walidacja `project_number` — property z setterem, musi być string 9 cyfr (`re.match(r"^\d{9}$", value)`)
- Metody `from_dict()`, `to_dict()`, `__str__()`
- Rozszerzenie `DataStore`:
  - Nowy plik: `data/construction_sites.json`
  - Nowy wpis w `self.paths`
  - Metody `load_sites()`, `save_sites()`
- Rozszerzenie `App`:
  - `create_site()` — tworzenie nowej budowy
  - `edit_site()` — edycja istniejącej budowy
  - `delete_site()` — usuwanie budowy (z walidacją: nie usuwaj jeśli ma aktywne rezerwacje)
  - `show_sites()` — lista budów
- Integracja z rezerwacjami:
  - `Reservation` dostaje nowe pole `site_id` (zamiast lub obok `address`)
  - Przy tworzeniu rezerwacji: wyświetlenie menu z listą aktywnych budów, wybór po UID budowy
  - Wyświetlanie rezerwacji pokazuje nazwę budowy i klienta
- Nowe opcje w menu konsolowym
**Acceptance Criteria:**
- Walidacja 9-cyfrowego numeru projektu działa (odrzuca krótsze, dłuższe, z literami)
- CRUD budów działa bez błędów
- Nie można usunąć budowy z aktywnymi rezerwacjami
- Przy tworzeniu rezerwacji wybiera się budowę z listy
- Dane budów zapisywane w osobnym pliku JSON

---

### TASK 15 — TODO
**Summary:** Poprawka obliczania dat przeglądów (dateutil + 2 typy przeglądów)
**Type:** Bug / Improvement
**Priority:** Medium
**Description:**
Zmiana logiki obliczania następnego przeglądu:
- Instalacja biblioteki `python-dateutil` (via `uv add python-dateutil`)
- Zmiana `calculate_next_inspection` z `timedelta(days=interval_months * 30)` na `relativedelta(months=interval_months)` — prawdziwe miesiące kalendarzowe
- Dwa typy przeglądów:
  - Kwartalny (3-miesięczny): przegląd 16.03 → następny 16.06
  - Roczny (12-miesięczny): przegląd 16.03 → następny 16.03 następnego roku
- Rozszerzenie `input_choice` przy dodawaniu wpisu serwisowego: typ przeglądu "quarterly" / "annual"
- Aktualizacja `add_service_record()` — przekazanie odpowiedniego interwału (3 lub 12)
- Weryfikacja: lista maszyn w `show_machines()` już wyświetla [!] i [PRZETERMINOWANY] — ta logika istnieje (TASK 5), potwierdzono podczas code review
**Acceptance Criteria:**
- 3-miesięczny przegląd z 16.03 daje 16.06 (nie 14.06 jak przy 90 dniach)
- Roczny przegląd z 16.03 daje 16.03 następnego roku (nie 11.03 jak przy 360 dniach)
- Użytkownik wybiera typ przeglądu przy dodawaniu wpisu serwisowego
- Lista maszyn nadal pokazuje ostrzeżenia o przeglądach

---

### TASK 16 — TODO
**Summary:** Guard Clauses — sprawdzenie i poprawka wzorca we wszystkich metodach
**Type:** Refactor
**Priority:** Medium
**Description:**
Audyt i poprawka wzorca "early return" (guard clause) w całym kodzie:
- `show_reservations()` — przenieść `if not self.reservations` z końca na początek metody (przed pętlą `for`), dodać `return` po komunikacie
- Przegląd pozostałych metod pod kątem tego samego wzorca:
  - `show_machines()` — ✅ już poprawnie (guard clause na początku)
  - `show_service_history()` — sprawdzić
  - `create_reservation()` — ✅ sprawdzić serię guard clauses
  - `return_machine()` — ✅ sprawdzić
  - `add_service_record()` — sprawdzić
- Zasada: walidacja i warunki wyjścia na początku metody, logika biznesowa na końcu
**Acceptance Criteria:**
- `show_reservations()` sprawdza pustą listę PRZED wykonaniem pętli
- Wszystkie metody z wyświetlaniem danych mają guard clause na początku
- Brak niepotrzebnego wykonywania kodu na pustych danych

---

### TASK 17 — TODO
**Summary:** Gettery zamiast bezpośredniego dostępu do _status
**Type:** Refactor
**Priority:** Medium
**Description:**
Zamiana wszystkich bezpośrednich odwołań do `_status` na użycie property `status` poza klasami, w których `_status` jest zdefiniowany:
- `show_reservations()`: `r._status` → `r.status`
- `create_reservation()`: `m._status` → `m.status`
- `return_machine()`: `m._status` → `m.status`, `res._status` → `res.status`
- `has_conflict()`: `res._status` → `res.status`
- `run_daily_sync()`: `res._status` → `res.status`, `machine._status` → `machine.status`
- `show_machines()` — sprawdzić
- `to_dict()` w Machine: `self._status` → `self.status`
- Metoda: find & replace z weryfikacją — `r._status` → `r.status`, `m._status` → `m.status`, `res._status` → `res.status` — ale TYLKO poza definicją property
**Acceptance Criteria:**
- Żadne odwołanie do `_status` poza klasą, w której jest zdefiniowany
- Property getter używany konsekwentnie w całym kodzie
- Testy manualne: wszystkie funkcje działają bez zmian w zachowaniu

---

### TASK 18 — TODO
**Summary:** return_machine — eliminacja podwójnej iteracji (DRY)
**Type:** Refactor
**Priority:** Low
**Description:**
W `return_machine()` maszyny są filtrowane do listy `on_site`, a następnie `find_machine()` szuka ponownie w pełnej liście `self.machines`. Podwójna iteracja jest niepotrzebna (DRY — Don't Repeat Yourself).
- Zmiana: szukanie maszyny w liście `on_site` zamiast w `self.machines`
- Usunięcie warunku `machine._status != "Op de werf"` (zbędny, bo `on_site` już zawiera tylko takie)
- Przed:
  ```python
  machine = self.find_machine(uid)
  if not machine or machine._status != "Op de werf":
  ```
- Po:
  ```python
  machine = next((m for m in on_site if m.uid == uid), None)
  if not machine:
  ```
**Acceptance Criteria:**
- Maszyna szukana w `on_site`, nie w `self.machines`
- Usunięty zbędny warunek sprawdzania statusu
- Funkcja zwrotu działa identycznie jak przed zmianą

---

### TASK 19 — TODO
**Summary:** Konsekwentne porównywanie dat jako obiektów date, nie stringów
**Type:** Bug / Refactor
**Priority:** Medium
**Description:**
W `return_machine()` daty porównywane są jako stringi:
```python
today_str = date.today().strftime("%Y-%m-%d")
res.start_date <= today_str  # porównanie stringów
```
Mimo że format RRRR-MM-DD sortuje się poprawnie alfabetycznie, jest to niespójne z resztą kodu, który używa `parse_date()` i obiektów `date`.
- Zmiana w `return_machine()`: porównywanie przez `parse_date(res.start_date) <= today`
- Audyt całego kodu pod kątem porównywania dat jako stringów
- Sprawdzić: `run_daily_sync()` — czy `today_str` przy `res.end_date = today_str` jest OK (tak, bo to przypisanie stringa do pola, nie porównanie)
- Zasada: porównania dat ZAWSZE przez obiekty `date`, przypisania do pól JSON mogą pozostać stringami
**Acceptance Criteria:**
- Żadne porównanie dat nie odbywa się na stringach
- Porównania dat używają `parse_date()` lub `date.fromisoformat()`
- Przypisania dat do pól modeli pozostają stringami (bo JSON)

---

### TASK 20 — TODO
**Summary:** Rozbicie monolitu na moduły (architektura plików)
**Type:** Refactor
**Priority:** Low
**Description:**
Aktualnie cały kod (~400 linii, rosnący) jest w jednym pliku `main.py`. Przy dodaniu klasy `ConstructionSite`, edycji i nowych ekranów plik urośnie do ~700+ linii. Rozważyć rozbicie na moduły zgodne z istniejącą architekturą warstwową:

Proponowana struktura:
```
planer_maszyn/
├── main.py                 # tylko: if __name__ == "__main__": App().run()
├── models/
│   ├── __init__.py
│   ├── machine.py          # klasa Machine
│   ├── reservation.py      # klasa Reservation
│   ├── service_record.py   # klasa ServiceRecord
│   └── construction_site.py # klasa ConstructionSite (TASK 14)
├── datastore.py            # klasa DataStore (Repository Pattern)
├── logic.py                # parse_date, has_conflict, run_daily_sync, calculate_next_inspection, check_inspection_status
├── helpers.py              # input_date, input_choice
└── app.py                  # klasa App (UI konsolowe)
```

Wzorzec: **Layered Architecture** (architektura warstwowa) — ten sam podział, który już istnieje w komentarzach kodu (MODELE DANYCH / ZAPIS I ODCZYT / LOGIKA BIZNESOWA / HELPERY / INTERFEJS), przeniesiony na poziom plików.

Korzyści:
- Każdy plik < 150 linii
- Łatwiejsze nawigowanie w IDE
- Przygotowanie do Django: `models/` → `models.py` w Django, `logic.py` → `services.py`, `datastore.py` → zamieniony na ORM
- Import: `from models.machine import Machine` → w Django: `from machines.models import Machine`

Ryzyka:
- Zwiększona złożoność importów
- Potencjalne cykliczne zależności (rozwiązanie: `logic.py` importuje modele, nie odwrotnie)

**DECYZJA DO PODJĘCIA:** Czy rozbijać teraz (przed Milestone 2) czy dopiero przy migracji do Django? Argumenty za "teraz": kod urośnie o ~300 linii (TASK 13 + TASK 14), nawigacja w monolicie będzie uciążliwa. Argumenty za "później": w Django i tak będzie inna struktura plików, więc wysiłek może się nie zwrócić.

**Sugestia:** Rozbić teraz — wysiłek jest mały (przeniesienie kodu + dodanie importów, ~30 minut), a korzyść natychmiastowa. Struktura plików mapuje się 1:1 na architekturę Django, więc migracja będzie prostsza.
**Acceptance Criteria:**
- Każdy moduł w osobnym pliku
- Importy działają poprawnie (brak cyklicznych zależności)
- `main.py` zawiera tylko punkt wejścia
- Wszystkie funkcje działają identycznie jak przed refaktoryzacją
- Testy manualne przechodzą

---

### TASK 21 — TODO
**Summary:** Poprawka create_reservation — walidacja UID z listy dostępnych maszyn
**Type:** Bug
**Priority:** Medium
**Description:**
W `create_reservation()` wyświetlana jest lista maszyn "In Magazijn", ale walidacja UID sprawdza `find_machine(uid)` — czyli szuka w WSZYSTKICH maszynach. Użytkownik może wpisać UID maszyny, która jest "Op de werf" i przejdzie walidację (nie jest `None`), mimo że nie była na liście dostępnych.
- Przed:
  ```python
  available = [m for m in self.machines if m.status == "In Magazijn"]
  # ... wyświetla available ...
  uid = input("UID maszyny: ").strip()
  if not self.find_machine(uid):  # szuka w WSZYSTKICH maszynach
  ```
- Po:
  ```python
  machine = next((m for m in available if m.uid == uid), None)
  if not machine:
  ```
**Acceptance Criteria:**
- Użytkownik może wybrać tylko maszynę z listy dostępnych (status "In Magazijn")
- Wpisanie UID maszyny na budowie daje komunikat "Nie znaleziono maszyny"

---

### TASK 22 — TODO
**Summary:** Bezpieczniejsze generowanie ID rezerwacji i wpisów serwisowych
**Type:** Improvement
**Priority:** Low
**Description:**
Obecne generowanie ID:
- Rezerwacje: `f"RES-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self.reservations) + 1}"` — dwie rezerwacje w tej samej sekundzie = identyczne ID
- Serwis: `f"SRV-{len(self.service_records) + 1}"` — po usunięciu wpisu numeracja się powtórzy

Propozycja: użycie `uuid4()` z biblioteki standardowej:
```python
import uuid
res_id = f"RES-{uuid.uuid4().hex[:12]}"
```
Alternatywnie: zostawić obecne rozwiązanie jako akceptowalne dla aplikacji konsolowej i poprawić dopiero w Django (baza danych generuje ID automatycznie).

**DECYZJA DO PODJĘCIA:** Poprawić teraz czy zostawić na Django?
**Acceptance Criteria:**
- ID rezerwacji i wpisów serwisowych są unikalne niezależnie od czasu utworzenia
- Usunięcie wpisu nie powoduje kolizji numeracji

---

## TASKI MILESTONE 2 (bez zmian)

### TASK 11 — TODO (Milestone 2)
**Summary:** Przygotowanie struktury projektu Django

### TASK 12 — TODO (Milestone 2)
**Summary:** Interfejs webowy — timeline z rezerwacjami
