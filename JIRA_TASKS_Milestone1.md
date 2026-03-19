# TASKI NA JIRĘ — Milestone 1 (Aplikacja konsolowa)
# Projekt: Planer Maszyn Budowlanych
# Sprint: Milestone 1 (8.02 – 12.04)

---

## ARCHITEKTURA PROJEKTU

Aplikacja zbudowana według wzorca **Layered Architecture** (architektura warstwowa)
z wyraźną separacją odpowiedzialności (Separation of Concerns):

| Warstwa | Plik | Odpowiedzialność |
|---------|------|-----------------|
| Prezentacja (UI) | `ui.py` | Menu, formularze, input/print — jedyne miejsce z I/O |
| Logika biznesowa | `logic.py` | Konflikty rezerwacji, synchronizacja — zero I/O |
| Modele dziedzinowe | `models.py` | Klasy danych z walidacją, serializacja do/z JSON |
| Dostęp do danych | `datastore.py` | Zapis/odczyt JSON, backupy — wzorzec Repository |
| Wyjątki | `exceptions.py` | Dedykowane klasy błędów (`DataCorruptionError`) |
| Narzędzia | `utils.py` | Parsowanie dat, generowanie ID — współdzielone |
| Punkt wejścia | `main.py` | Tylko `App().run()` — deleguje do UI |
| Testy | `test_*.py` | Testy jednostkowe pytest, pogrupowane per warstwa |
| Konfiguracja testów | `conftest.py` | PYTHONPATH setup dla pytest |

**Dlaczego taki podział:**
Mapuje się bezpośrednio na architekturę Django w Milestone 2:
- `models.py` → Django Models + ORM (zamiana `DataStore` na bazę danych)
- `logic.py` → serwisy / widoki Django (logika zostaje bez zmian)
- `ui.py` → szablony HTML + widoki Django (zamiana print/input na HTTP)
- `utils.py` → bez zmian
- `exceptions.py` → bez zmian

Dzięki temu migracja do Django polega na wymianie infrastruktury,
nie na przepisywaniu logiki biznesowej.

**Statystyki kodu:**
- 1836 linii kodu łącznie (11 plików .py)
- 617 linii UI, 309 linii modeli, 142 linie persystencji, 127 linii logiki
- 556 linii testów (3 pliki, 40+ test case'ów)

---

## FAZA 1 — FUNDAMENT (Taski 1–10)

---

### TASK 1 ✅ DONE
**Summary:** Struktura projektu i modele danych (OOP)
**Type:** Task
**Description:**
Utworzenie struktury projektu i klas obiektowych:
- Klasa Machine (maszyna budowlana) z właściwościami i walidacją statusów
- Klasa Reservation (rezerwacja) z właściwościami i generowaniem tytułu
- Klasa ServiceRecord (przegląd/naprawa) z obsługą kosztów
- Dekoratory @property, @classmethod, @staticmethod
- Metody serializacji to_dict() i deserializacji from_dict()
**Acceptance Criteria:**
- Każda klasa ma walidację danych wejściowych
- Obiekty można konwertować do/z formatu słownikowego (JSON-ready)
- Klasy używają hermetyzacji (prywatne atrybuty + gettery/settery)

---

### TASK 2 ✅ DONE
**Summary:** Zapis i odczyt danych z plików JSON
**Type:** Task
**Description:**
Implementacja klasy DataStore odpowiedzialnej za persystencję danych:
- Zapis/odczyt maszyn z pliku machines.json
- Zapis/odczyt rezerwacji z pliku reservations.json
- Zapis/odczyt wpisów serwisowych z pliku service_records.json
- Automatyczne tworzenie katalogu data/ jeśli nie istnieje
- Obsługa błędów (brak pliku, nieprawidłowy JSON)
**Acceptance Criteria:**
- Dane zapisywane w czytelnym formacie JSON z wcięciami
- Aplikacja nie crashuje gdy pliki nie istnieją (pusta lista)
- Kodowanie UTF-8 (polskie znaki w opisach)

---

### TASK 3 ✅ DONE
**Summary:** Import maszyn z zewnętrznego pliku JSON
**Type:** Task
**Description:**
Funkcja importu danych maszyn z pliku machines_db.json:
- Wczytanie pliku z danymi źródłowymi (55 maszyn)
- Mapowanie pól z formatu źródłowego na model Machine
- Mechanizm update-or-create (istniejące maszyny nadpisywane po UID)
- Obsługa błędów: brak pliku, nieprawidłowy format
**Acceptance Criteria:**
- Po imporcie w systemie jest 55 maszyn z poprawnymi danymi
- Ponowny import nie tworzy duplikatów

---

### TASK 4 ✅ DONE
**Summary:** Menu konsolowe — nawigacja i interfejs użytkownika
**Type:** Task
**Description:**
Implementacja klasy App (ui.py) z interaktywnym menu tekstowym:
- Menu główne z opcjami 0–11
- Pętla programu (while True) z obsługą wyboru
- Walidacja danych wejściowych (daty, wybór z listy)
- Formatowanie wyświetlanych tabel (wyrównanie kolumn)
- Helpery input: input_date, input_choice, input_required
**Acceptance Criteria:**
- Nieprawidłowy wybór nie crashuje programu
- Daty walidowane w formacie RRRR-MM-DD
- Czytelne formatowanie list maszyn i rezerwacji

---

### TASK 5 ✅ DONE
**Summary:** Wyświetlanie listy maszyn ze statusami
**Type:** Task
**Description:**
Widok listy maszyn w konsoli:
- Tabela: UID, Nazwa, Status, Lokalizacja
- Oznaczenie maszyn z przeterminowanym przeglądem [PRZETERMINOWANY]
- Oznaczenie maszyn z przeglądem kończącym się w ciągu 14 dni [!]
**Acceptance Criteria:**
- Wszystkie maszyny wyświetlone w czytelnej tabeli
- Status przeglądu widoczny obok każdej maszyny

---

### TASK 6 ✅ DONE
**Summary:** Tworzenie rezerwacji z wykrywaniem konfliktów
**Type:** Task
**Description:**
Formularz tworzenia nowej rezerwacji:
- Wyświetlenie listy dostępnych maszyn (status: In Magazijn)
- Pola: maszyna, data od/do, osoba, numer projektu, adres budowy
- Algorytm wykrywania nakładających się rezerwacji
- Walidacja: data końca >= data początku
- Generowanie unikalnego ID rezerwacji
- Stykające się daty (end_a == start_b) traktowane jako konflikt
  (maszyna potrzebuje transportu i przygotowania)
**Acceptance Criteria:**
- Nie można zarezerwować maszyny w terminie, w którym jest już zajęta
- Komunikat błędu precyzyjnie informuje o konflikcie
- Rezerwacja zapisywana do pliku JSON po utworzeniu

---

### TASK 7 ✅ DONE
**Summary:** Przegląd rezerwacji — widok z podziałem na statusy
**Type:** Task
**Description:**
Wyświetlanie rezerwacji z podziałem na sekcje:
- Oczekujące na zatwierdzenie (pending)
- Aktywne / Potwierdzone (confirmed)
- Zakończone (completed)
- Anulowane (rejected)
- Liczba rezerwacji w każdej sekcji
**Acceptance Criteria:**
- Rezerwacje pogrupowane i wyświetlone czytelnie
- Widoczne: maszyna, daty, projekt, osoba, status

---

### TASK 8 ✅ DONE
**Summary:** Zwrot maszyny do magazynu
**Type:** Task
**Description:**
Funkcja realizacji zwrotu maszyny:
- Wyświetlenie maszyn aktualnie na budowie (Op de werf)
- Zmiana statusu maszyny na "In Magazijn"
- Zmiana lokalizacji na "Magazyn"
- Zamknięcie aktywnej rezerwacji (status: completed)
- Zamknięcie przeterminowanych rezerwacji (przedłużonych przez sync)
- Sprawdzenie czy maszyna ma rezerwację w przyszłości → status Gereserveerd
**Acceptance Criteria:**
- Po zwrocie maszyna widoczna jako wolna
- Rezerwacja oznaczona jako zakończona
- Zamykane tylko bieżące i przeterminowane rezerwacje, przyszłe nienaruszone

---

### TASK 9 ✅ DONE
**Summary:** Hard Return Policy — automatyczne przedłużanie rezerwacji
**Type:** Task
**Description:**
Logika automatycznej synchronizacji statusów (run_daily_sync):
- Maszyny z aktywnymi rezerwacjami → status "Op de werf"
- Przeterminowane rezerwacje (end_date < dziś, maszyna nie w magazynie)
  → automatyczne przedłużenie end_date do dzisiaj
- Maszyny z rezerwacją w przyszłości → status "Gereserveerd"
- Maszyny "In Herstelling" pomijane (serwis > automatyka)
- Uruchamiane automatycznie przy starcie aplikacji
- Możliwość ręcznego uruchomienia z menu (opcja 11)
**Acceptance Criteria:**
- Niezwrócone maszyny mają automatycznie przedłużoną rezerwację
- Synchronizacja nie duplikuje ani nie nadpisuje istniejących danych
- Maszyna z aktywną + przyszłą rezerwacją → pozostaje "Op de werf" (nie przeskakuje)

---

### TASK 10 ✅ DONE
**Summary:** Moduł serwisowy — przeglądy i naprawy
**Type:** Task
**Description:**
Obsługa przeglądów technicznych i napraw:
- Dodawanie wpisu: typ (przegląd/naprawa), data, opis, koszt
- Automatyczne obliczanie daty następnego przeglądu
- Aktualizacja daty przeglądu na maszynie
- Wyświetlanie historii serwisowej z filtrowaniem po maszynie
- Podsumowanie łącznych kosztów
- Walidacja: koszt nie może być ujemny
**Acceptance Criteria:**
- Po dodaniu przeglądu data następnego obliczana automatycznie
- Raport kosztowy wyświetla sumę dla wybranej maszyny
- Koszty w formacie EUR z 2 miejscami po przecinku

---

## FAZA 2 — ROZSZERZENIA I EDYCJA (Taski 13–16)

---

### TASK 13 ✅ DONE
**Summary:** Edycja maszyny z poziomu konsoli
**Type:** Task
**Description:**
Formularz edycji danych maszyny (edit_machine):
- Wyszukanie maszyny po UID
- Edycja pól: nazwa, model, lokalizacja, status
- Enter = pozostaw obecną wartość (nie wymusza ponownego wpisywania)
- Walidacja statusu przez setter (nieprawidłowy status → komunikat, brak zmiany)
- Natychmiastowy zapis po edycji
**Acceptance Criteria:**
- Zmiana statusu na nieprawidłowy nie crashuje, wyświetla komunikat
- Puste pola nie nadpisują istniejących wartości

---

### TASK 14 ✅ DONE
**Summary:** Edycja rezerwacji z wykrywaniem konfliktów
**Type:** Task
**Description:**
Formularz edycji istniejącej rezerwacji (edit_reservation):
- Lista aktywnych rezerwacji (pending + confirmed) z numeracją
- Edycja pól: osoba, numer projektu, adres, data końca
- Wykrywanie konfliktów przy zmianie daty końca (exclude_id = edytowana)
- Walidacja date range (koniec >= początek)
- Enter = pozostaw obecną wartość
**Acceptance Criteria:**
- Zmiana daty końca sprawdza konflikty z innymi rezerwacjami
- Edytowana rezerwacja nie koliduje sama ze sobą (exclude_id)

---

### TASK 15 ✅ DONE
**Summary:** Anulowanie rezerwacji z obsługą statusów maszyny
**Type:** Task
**Description:**
Funkcja anulowania rezerwacji (cancel_reservation):
- Lista aktywnych rezerwacji z numeracją
- Potwierdzenie anulowania (t/n)
- Zmiana statusu rezerwacji na "rejected"
- Sprawdzenie czy maszyna powinna wrócić do magazynu:
  - Brak innych aktywnych rezerwacji → "In Magazijn"
  - Maszyna była "Gereserveerd" → "In Magazijn"
  - Maszyna była "Op de werf" → ostrzeżenie + "In Magazijn"
**Acceptance Criteria:**
- Anulowanie jedynej rezerwacji zmienia status maszyny na "In Magazijn"
- Anulowanie jednej z wielu rezerwacji nie zmienia statusu maszyny
- Ostrzeżenie gdy maszyna fizycznie na budowie

---

### TASK 16 ✅ DONE
**Summary:** Status "Gereserveerd" przy tworzeniu rezerwacji
**Type:** Task
**Description:**
Ustawienie statusu maszyny po utworzeniu rezerwacji:
- Rezerwacja zaczyna się dziś lub wcześniej → "Op de werf" + lokalizacja
- Rezerwacja w przyszłości → "Gereserveerd"
- Rezerwacja tworzona od razu jako "confirmed" (warehouse manager
  jest jedynym użytkownikiem, nie ma procesu zatwierdzania)
- Status "pending" pozostaje w VALID_STATUSES na przyszłość (Milestone 2: multi-user)
**Acceptance Criteria:**
- Maszyna z rezerwacją w przyszłości ma status "Gereserveerd"
- Maszyna z rezerwacją od dziś ma status "Op de werf"

---

## FAZA 3 — BEZPIECZEŃSTWO DANYCH (Taski 17–20)

---

### TASK 17 ✅ DONE
**Summary:** Kopie zapasowe (.bak) z automatycznym fallbackiem
**Type:** Task
**Description:**
Mechanizm ochrony danych przed utratą (DataStore._save / _load):
- Przed każdym zapisem tworzenie kopii zapasowej (.bak) istniejącego pliku
- Przy odczycie: plik uszkodzony → automatyczny fallback na .bak
- Oba uszkodzone → DataCorruptionError (dedykowany wyjątek)
- Uszkodzone pliki NIE są nadpisywane — pozostają na dysku do ręcznej naprawy
**Acceptance Criteria:**
- Po dwukrotnym zapisie istnieje plik .bak z poprzednią wersją
- Uszkodzony plik główny → dane wczytane z .bak bez ingerencji usera
- Oba uszkodzone → czytelny komunikat, pusta lista, brak nadpisania

---

### TASK 18 ✅ DONE
**Summary:** Blokada zapisu uszkodzonych kolekcji (_corrupted)
**Type:** Task
**Description:**
Zabezpieczenie przed nadpisaniem uszkodzonych plików (App._safe_load):
- Set _corrupted śledzi kolekcje z DataCorruptionError przy starcie
- _save_machines(), _save_reservations(), _save_service_records()
  sprawdzają _corrupted i pomijają zapis z komunikatem
- save_all() przy wyjściu respektuje _corrupted
**Acceptance Criteria:**
- Uszkodzony plik maszyn → user może przeglądać rezerwacje, ale zapis
  maszyn jest zablokowany do ręcznej naprawy pliku
- Komunikat "Zapis pominięty — plik był uszkodzony przy starcie"

---

### TASK 19 ✅ DONE
**Summary:** Celowane zapisy z flagami _dirty
**Type:** Task
**Description:**
Optymalizacja zapisu — tylko zmodyfikowane kolekcje:
- Set _dirty śledzi które kolekcje się zmieniły od ostatniego zapisu
- Każda operacja dodaje odpowiedni klucz do _dirty
- save_all() przy wyjściu zapisuje tylko zmienione kolekcje
- Celowane zapisy (_save_machines itp.) natychmiast po operacji
**Acceptance Criteria:**
- Edycja maszyny nie nadpisuje pliku rezerwacji
- save_all() nie zapisuje niezmienionych plików

---

### TASK 20 ✅ DONE
**Summary:** Defensywny import z pomijaniem uszkodzonych rekordów
**Type:** Task
**Description:**
Uodpornienie importu maszyn (import_machines):
- Guard clause: sprawdzenie czy JSON to lista (nie słownik)
- Uszkodzone rekordy logowane i pomijane, poprawne importowane
- Lista pominiętych rekordów (skipped_details) zwracana w return value
- Szczegóły pominiętych rekordów wyświetlane w ui.py (nie w datastore)
**Acceptance Criteria:**
- Plik z {} zamiast [] → czytelny ValueError
- 2 z 4 rekordów uszkodzone → 2 zaimportowane, 2 pominięte z opisem
- Zero printów w warstwie danych (datastore.py)

---

## FAZA 4 — TESTY I JAKOŚĆ KODU (Taski 21–22)

---

### TASK 21 ✅ DONE
**Summary:** Testy jednostkowe — modele, logika, persystencja
**Type:** Task
**Description:**
Suite testów pytest z podziałem na warstwy:
- test_models.py: walidacja statusów, serializacja to_dict/from_dict,
  walidacja pustych ID, check_inspection_status, date range
- test_logic.py: has_conflict (overlap, adjacent, touching, exclude_id,
  rejected/completed), run_daily_sync (aktywna, przeterminowana,
  przyszła, In Herstelling, brak maszyny, aktywna+przyszła)
- test_utils_and_datastore.py: parse_date, generate_id, generate_unique_id,
  save/load, backup, corruption, defensywny import, guard clause
- conftest.py: PYTHONPATH setup (TODO → pyproject.toml w M2)
**Acceptance Criteria:**
- 40+ test case'ów pokrywających happy path i edge case'y
- Testy persystencji używają tmp_path (bez efektów ubocznych)
- `python -m pytest tests/ -v` → all green

---

### TASK 22 ✅ DONE
**Summary:** Type hints i adnotacje typów (PEP 484)
**Type:** Task
**Description:**
Konsekwentne typowanie we wszystkich modułach:
- Składnia Python 3.10+ (list[Machine], dict[str, int], str | None)
- TypeVar z ograniczeniami w DataStore (T = Machine | Reservation | ServiceRecord)
- Adnotacje parametrów i zwracanych wartości w publicznych metodach
- Przygotowanie pod mypy i migrację do Django + Pydantic
**Acceptance Criteria:**
- Wszystkie publiczne metody mają adnotacje typów
- Edytor (PyCharm/VSCode) poprawnie podpowiada typy

---

## FAZA 5 — CODE REVIEW I HARDENING (Taski 25–28)

---

### TASK 25 ✅ DONE
**Summary:** Walidacja pustych ID w konstruktorach modeli
**Type:** Bug fix
**Description:**
Zabezpieczenie przed tworzeniem obiektów z pustym identyfikatorem:
- Machine.__init__: `if not uid or not uid.strip(): raise ValueError`
- Reservation.__init__: `if not reservation_id or not reservation_id.strip(): raise ValueError`
- ServiceRecord.__init__: `if not record_id or not record_id.strip(): raise ValueError`
- Testy: test_empty_id_raises, test_whitespace_id_raises dla każdej klasy
- TypeVar w DataStore ściślej ograniczony do trzech klas modeli
**Acceptance Criteria:**
- Machine("", ...) → ValueError
- Machine("   ", ...) → ValueError
- from_dict z brakującym UID → walidacja w konstruktorze

---

### TASK 26 ✅ DONE
**Summary:** Code review #1 — bug fixy (3× AI review: Claude + Gemini Pro + Gemini Thinking)
**Type:** Bug fix
**Description:**
Trzy niezależne przeglądy kodu skonsolidowane w listę poprawek:

**BUG 1 — _safe_load nie blokuje zapisu do uszkodzonych plików:**
Po DataCorruptionError apka kontynuowała z pustą listą. Przy wyjściu
save_all() nadpisywał uszkodzony plik pustą listą.
Fix: _corrupted set + sprawdzenie w _save_*() (→ TASK 18)

**BUG 2 — import_machines nie sprawdza czy JSON to lista:**
Po json.load(f) iteracja po raw zakładała listę. Słownik {} → iteracja
po kluczach-stringach → niezrozumiały błąd.
Fix: guard clause `if not isinstance(raw, list): raise ValueError`

**BUG 3 — cancel_reservation resetuje maszynę Op de werf do In Magazijn:**
Maszyna fizycznie na budowie, anulowana rezerwacja → system mówi "In Magazijn".
Fix: ostrzeżenie "upewnij się, że fizycznie wróciła" przed zmianą statusu

**Acceptance Criteria:**
- Uszkodzone pliki nigdy nie są nadpisywane pustą listą
- Import {} → czytelny ValueError, nie cryptic error
- Anulowanie → ostrzeżenie o fizycznej lokalizacji maszyny

---

### TASK 27 ✅ DONE
**Summary:** Code review #1 — refaktoryzacje
**Type:** Improvement
**Description:**
Poprawki czytelności i spójności warstw z trzech przeglądów:

**REFACTOR 1 — print() w DataStore._load():**
Warstwa danych printowała komunikat o fallbacku na .bak.
Fix: usunięty print z _load() — informacja zwracana przez wyjątki/return value.

**REFACTOR 2 — nested ternary w show_machines():**
Zagnieżdżony ternary operator trudny do czytania.
Fix: dict lookup `markers = {"warning": " [!]", "overdue": " [PRZETERMINOWANY]"}`

**REFACTOR 3 — brak komentarza o pominięciu statusu pending:**
create_reservation tworzył rezerwację od razu jako "confirmed" bez wyjaśnienia.
Fix: komentarz biznesowy — warehouse manager sam tworzy, pending na M2.

**REFACTOR 4 — import_machines nie ustawia _dirty:**
Po imporcie brak _dirty.add("machines"), łamie konwencję.
Fix: komentarz wyjaśniający — store.import_machines() zapisuje bezpośrednio,
_dirty nie jest potrzebne (dane zsynchronizowane z dyskiem).

**Acceptance Criteria:**
- Zero printów w datastore.py
- Czytelny dict lookup zamiast nested ternary
- Decyzje biznesowe udokumentowane w komentarzach

---

### TASK 28 ✅ DONE
**Summary:** Code review #2 — finalne poprawki spójności warstw
**Type:** Bug fix / Improvement
**Description:**
Druga runda przeglądu po wdrożeniu Tasków 26–27:

**FIX 1 — print w import_machines (datastore.py):**
REFACTOR 1 usunął print z _load(), ale import_machines nadal printował
"Pominięto rekord #X". Niespójne z zasadą "zero I/O w warstwie danych".
Fix: import_machines zwraca skipped_details: list[str] w return value,
ui.py iteruje i printuje szczegóły.

**FIX 2 — from_dict maskuje brakujące klucze:**
Machine.from_dict robiło data.get("uid", ""). Brakujący klucz "uid" w JSON
powodował ValueError("UID pusty") zamiast KeyError("uid") — mylący komunikat.
Fix: wymagane pola (uid, id) używają data["uid"] zamiast data.get("uid", "").
Brakujący klucz → KeyError, pusta wartość → ValueError. Dwa różne błędy,
dwa różne komunikaty.

**Test update:**
test_from_dict_empty_uid_raises → test_from_dict_missing_uid_raises (expects KeyError)

**Acceptance Criteria:**
- Zero printów w datastore.py (pełna spójność warstw)
- Brakujący klucz w JSON → KeyError("uid"), nie ValueError("UID pusty")
- Testy zaktualizowane pod nowe zachowanie

---

## MILESTONE 2 — TODO

---

### TASK 29 — TODO (Milestone 2)
**Summary:** Przygotowanie struktury projektu Django
**Type:** Task
**Status:** To Do
**Description:**
Przeniesienie logiki z aplikacji konsolowej na framework Django:
- Inicjalizacja projektu Django 5.x
- Custom User Model
- Konfiguracja bazy PostgreSQL
- Przeniesienie modeli danych (models.py → Django Models)
- pyproject.toml z konfiguracją pytest (zamiana conftest.py hack)
- VALID_STATUSES krotki → Django TextChoices / enum
- float → DecimalField dla kosztów serwisowych
- Daty jako stringi → DateField (obiekty date natywnie)
- Walidacja end_date >= start_date w modelu (nie tylko w UI)
- Stack: Django 5.x + Django Ninja + PostgreSQL + HTMX/Tailwind + Celery/Redis

---

### TASK 30 — TODO (Milestone 2)
**Summary:** Interfejs webowy — timeline z rezerwacjami
**Type:** Task
**Status:** To Do
**Description:**
Stworzenie głównego widoku osi czasu w Django:
- Istniejący React timeline component zachowany jako standalone Vite bundle
  osadzony w Django templates
- CSS Grid z maszynami i datami
- Paski rezerwacji z rozróżnieniem statusów
- Nawigacja po tygodniach/miesiącach
- Filtry (typ maszyny, status)

---

## TECH DEBT (udokumentowany, do spłaty w Milestone 2)

| Dług | Obecny stan | Docelowy (M2) |
|------|-------------|---------------|
| Koszty serwisowe | `float` | `DecimalField` |
| Daty w modelach | stringi + parse_date() | `DateField` (natywny `date`) |
| Obliczanie interwałów | 30 dni/miesiąc | `dateutil.relativedelta` |
| Konfiguracja testów | conftest.py sys.path hack | pyproject.toml pythonpath |
| Statusy | krotki stringów | Django TextChoices / enum |
| Walidacja dat | tylko w UI | w konstruktorze modelu |
| run_daily_sync | date.today() hardcoded | parametr `today` (testowalność) |
| Fallback na .bak | cichy (brak info dla usera) | logging.warning |
