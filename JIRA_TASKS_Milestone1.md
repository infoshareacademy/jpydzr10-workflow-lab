# TASKI NA JIRĘ — Milestone 1 (Aplikacja konsolowa)
# Projekt: Planer Maszyn Budowlanych
# Sprint: Milestone 1 (8.02 – 12.04)

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
Implementacja klasy ConsoleUI z interaktywnym menu tekstowym:
- Menu główne z opcjami 0-8
- Pętla programu (while True) z obsługą wyboru
- Walidacja danych wejściowych (daty, wybór z listy)
- Formatowanie wyświetlanych tabel (wyrównanie kolumn)
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
**Acceptance Criteria:**
- Po zwrocie maszyna widoczna jako wolna
- Rezerwacja oznaczona jako zakończona

---

### TASK 9 ✅ DONE
**Summary:** Hard Return Policy — automatyczne przedłużanie rezerwacji
**Type:** Task
**Description:**
Logika automatycznej synchronizacji statusów:
- Część 1: Maszyny z aktywnymi rezerwacjami → status "Op de werf"
- Część 2: Przeterminowane rezerwacje (end_date < dziś, maszyna nie
  w magazynie) → automatyczne przedłużenie end_date do dzisiaj
- Uruchamiane automatycznie przy starcie aplikacji
- Możliwość ręcznego uruchomienia z menu
**Acceptance Criteria:**
- Niezwrócone maszyny mają automatycznie przedłużoną rezerwację
- Synchronizacja nie duplikuje ani nie nadpisuje istniejących danych

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
**Acceptance Criteria:**
- Po dodaniu przeglądu data następnego obliczana automatycznie
- Raport kosztowy wyświetla sumę dla wybranej maszyny
- Koszty w formacie EUR z 2 miejscami po przecinku

---

### TASK 11 — TODO (Milestone 2)
**Summary:** Przygotowanie struktury projektu Django
**Type:** Task
**Status:** To Do
**Description:**
Przeniesienie logiki z aplikacji konsolowej na framework Django:
- Inicjalizacja projektu Django
- Custom User Model
- Konfiguracja bazy PostgreSQL
- Przeniesienie modeli danych

---

### TASK 12 — TODO (Milestone 2)
**Summary:** Interfejs webowy — timeline z rezerwacjami
**Type:** Task
**Status:** To Do
**Description:**
Stworzenie głównego widoku osi czasu w Django templates:
- CSS Grid z maszynami i datami
- Paski rezerwacji z rozróżnieniem statusów
- Nawigacja po tygodniach/miesiącach
- Filtry (typ maszyny, status)
