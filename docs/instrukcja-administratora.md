# Instrukcja użytkownika — Administrator

Planer Maszyn Budowlanych — system rezerwacji i serwisu maszyn dla firmy budowlanej.

Ta instrukcja jest przeznaczona dla osoby pełniącej rolę **Administratora**. Administrator ma dostęp do wszystkich funkcji systemu: zarządza maszynami, rezerwacjami, budowami, rejestrem serwisowym, kontami pracowników oraz panelem administracyjnym. Instrukcja prowadzi krok po kroku i nie wymaga wiedzy technicznej.

## Czego dowiesz się z tej instrukcji

- Jak zalogować się do systemu i włączyć dwuskładnikowe uwierzytelnianie (2FA).
- Jak czytać pulpit (dashboard) i panel wskaźników.
- Jak zarządzać maszynami, rezerwacjami, budowami i serwisem.
- Jak zakładać konta pracownikom i zarządzać nimi (zwolnienie, anonimizacja RODO).
- Jak korzystać z raportów oraz panelu administracyjnego i dziennika zdarzeń.
- Jak zmienić język, motyw kolorystyczny i dane w profilu.

---

## 1. Logowanie do systemu

1. Otwórz przeglądarkę i wejdź pod adres aplikacji (lokalnie: `http://localhost:8002`).
2. Kliknij **Zaloguj się** w menu po lewej stronie (lub w prawym dolnym rogu menu).
3. Wpisz swoją **nazwę użytkownika** oraz **hasło**.
4. Kliknij przycisk logowania.

Jeśli pięć razy z rzędu wpiszesz błędne hasło, konto zostanie tymczasowo zablokowane na jedną godzinę (ochrona przed włamaniem). Po blokadzie zobaczysz osobną stronę z komunikatem — odczekaj i spróbuj ponownie.

> **Wskazówka:** zaraz po zalogowaniu system może poprosić Cię o drugi składnik uwierzytelniania (kod z aplikacji). Patrz rozdział 2.

---

## 2. Uwierzytelnianie dwuskładnikowe (2FA)

System wymaga drugiego składnika logowania dla kont personelu (w tym administratora). To dodatkowa warstwa bezpieczeństwa: nawet jeśli ktoś pozna Twoje hasło, bez kodu z Twojego telefonu nie zaloguje się na Twoje konto.

### 2.1. Pierwsze uruchomienie 2FA (konfiguracja)

1. Po zalogowaniu system przekieruje Cię na stronę konfiguracji 2FA.
2. Zainstaluj w telefonie aplikację uwierzytelniającą (np. Google Authenticator).
3. Zeskanuj **kod QR** wyświetlony na ekranie. Jeśli nie możesz zeskanować, przepisz ręcznie **klucz tekstowy** podany pod kodem QR.
4. Aplikacja w telefonie zacznie generować sześciocyfrowe kody, które zmieniają się co 30 sekund.
5. Wpisz aktualny kod z aplikacji w pole na stronie i zatwierdź.

### 2.2. Kody zapasowe (recovery codes)

1. Po poprawnej konfiguracji system wygeneruje **10 jednorazowych kodów zapasowych**.
2. Kliknij przycisk pobrania, aby zapisać je jako plik `kody-zapasowe-2fa.txt`.
3. Przechowuj te kody w bezpiecznym miejscu (poza telefonem). Każdy kod działa **tylko raz**.

> **Ważne:** kody zapasowe pobierzesz tylko raz, bezpośrednio po konfiguracji. Jeśli zgubisz telefon i nie masz kodów zapasowych, odzyskanie dostępu będzie wymagało pomocy innego administratora.

### 2.3. Logowanie z 2FA (każde kolejne)

1. Wpisz nazwę użytkownika i hasło jak zwykle.
2. Na stronie weryfikacji wpisz **aktualny sześciocyfrowy kod** z aplikacji uwierzytelniającej.
3. Jeśli nie masz dostępu do telefonu, wpisz jeden ze swoich **kodów zapasowych** w to samo pole.

Po kilku błędnych próbach kod zostanie chwilowo zablokowany (cooldown) — odczekaj chwilę i spróbuj ponownie.

### 2.4. Reset 2FA innego użytkownika

Gdy pracownik utraci telefon i kody zapasowe, **administrator** może zresetować jego 2FA przez panel administracyjny:

1. Wejdź na `/admin/` i zaloguj się jako administrator.
2. Otwórz **TOTP devices** (`/admin/otp_totp/totpdevice/`) — znajdź urządzenie należące do danego użytkownika i **usuń je**.
3. (Opcjonalnie) Otwórz **Static devices** (`/admin/otp_static/staticdevice/`) i usuń stare kody zapasowe użytkownika.
4. Przy następnym logowaniu użytkownik zostanie ponownie poprowadzony przez konfigurację 2FA (nowy kod QR + nowe kody zapasowe).

Każda taka operacja jest rejestrowana w dzienniku panelu administracyjnego (kto i kiedy usunął urządzenie), więc pozostaje ślad audytowy.

---

## 3. Pulpit (dashboard) i wskaźniki

Po zalogowaniu trafiasz na **Panel główny**. Znajdziesz tam:

- **Cztery karty wskaźników (KPI)** u góry:
  - **Dostępne maszyny** — ile maszyn jest fizycznie w magazynie (wolne + zarezerwowane na przyszłość).
  - **Aktualnie na budowie** — ile maszyn jest obecnie w terenie.
  - **Aktywne rezerwacje** — liczba trwających rezerwacji (z informacją o oczekujących).
  - **Przeglądy techniczne** — ile maszyn ma przeterminowany lub zbliżający się przegląd. Kliknięcie otwiera listę konkretnych maszyn.
- Sekcję **„Dziś w magazynie"** z trzema kolumnami: które maszyny dziś wyjeżdżają, które wracają i które są aktualnie w trasie.
- Alerty o spóźnionych zwrotach i przeterminowanych przeglądach (pojawiają się tylko, gdy są takie sytuacje).
- **Ostatnie rezerwacje** oraz **Szybkie akcje** (nowa rezerwacja, timeline, dodaj maszynę, dodaj budowę).

Każda karta wskaźnika jest klikalna i prowadzi do odpowiedniej listy z gotowym filtrem.

> **Synchronizacja statusów:** w sekcji „Dziś w magazynie" administrator ma przycisk **Synchronizuj statusy**. Wymusza on natychmiastowe dopasowanie statusów maszyn do aktualnych rezerwacji (normalnie robi to automatycznie system raz dziennie rano).

---

## 4. Maszyny

Przejdź do **Maszyny** w menu po lewej stronie.

### 4.1. Przeglądanie i wyszukiwanie

- Lista pokazuje wszystkie maszyny wraz ze statusem: **W magazynie**, **Na budowie**, **Zarezerwowana**, **W serwisie**.
- Użyj filtrów (status, stan przeglądu) oraz pola wyszukiwania, aby zawęzić listę.
- Kliknij maszynę, aby zobaczyć jej kartę szczegółową (dane, historia rezerwacji, historia serwisu, daty przeglądów).

### 4.2. Dodawanie maszyny

1. Na liście maszyn kliknij **Dodaj maszynę**.
2. Wypełnij formularz (m.in. identyfikator UID, nazwa, dane techniczne, data przeglądu).
3. Zapisz. Daty wpisuj w formacie **dd.mm.rrrr** (np. 14.06.2026).

### 4.3. Edycja i usuwanie maszyny

- Na karcie maszyny kliknij **Edytuj**, aby zmienić dane.
- Aby usunąć maszynę, użyj opcji **Usuń** i potwierdź. Usuwanie maszyn jest dostępne **wyłącznie dla administratora**.

### 4.4. Zmiana statusu maszyny

Z poziomu karty maszyny możesz:

- **Skierować do serwisu** (oznaczyć jako „W serwisie"),
- **Zarejestrować zwrot** (powrót z budowy do magazynu),
- **Zakończyć naprawę** (powrót z serwisu do magazynu),
- **Wycofać** maszynę z użytku.

### 4.5. Import i eksport maszyn (XLSX)

- **Import:** na liście maszyn kliknij **Import**, wybierz przygotowany plik Excel (XLSX) i prześlij go. System wczyta maszyny zbiorczo.
- **Eksport:** kliknij **Eksport**, aby pobrać wszystkie maszyny do pliku Excel.

---

## 5. Rezerwacje

Przejdź do **Rezerwacje** lub do **Oś czasu** (timeline) w menu.

### 5.1. Oś czasu (timeline)

Oś czasu to wizualny harmonogram w stylu wykresu Gantta — wiersze to maszyny, kolumny to dni. Belki pokazują okresy rezerwacji. Kliknięcie pustego pola pozwala szybko utworzyć rezerwację, a kliknięcie belki otwiera szczegóły rezerwacji.

### 5.2. Tworzenie rezerwacji

1. Kliknij **Nowa rezerwacja** (na pulpicie, liście rezerwacji lub osi czasu).
2. Wybierz **maszynę**, **termin** (data początku i końca w formacie dd.mm.rrrr), **budowę** lub adres oraz osobę odpowiedzialną.
3. System automatycznie sprawdza **konflikty terminów**. Uwaga: stykające się daty są traktowane jako konflikt — maszyna potrzebuje jednego dnia na transport.
4. Zapisz. Nowa rezerwacja otrzyma status **Oczekująca**.

### 5.3. Cykl statusów rezerwacji

Rezerwacja przechodzi liniowo przez statusy: **Oczekująca → Potwierdzona → Zakończona** (z możliwością **Anulowania**).

Z poziomu szczegółów rezerwacji administrator może:

- **Potwierdzić** rezerwację oczekującą (klient otrzyma e-mail potwierdzający).
- **Zakończyć** rezerwację potwierdzoną (rejestracja zwrotu maszyny).
- **Anulować** rezerwację.
- **Zgłosić awarię** maszyny w trakcie rezerwacji.
- **Zmienić osobę** przypisaną do rezerwacji.
- **Wymienić maszynę** w trakcie trwania rezerwacji (kończy starą, tworzy nową).
- **Edytować** formularz rezerwacji (zmiana maszyny, terminu, danych) — ta operacja jest dostępna **wyłącznie dla administratora**.
- **Pobrać PDF** rezerwacji.

> **Spóźnione zwroty:** jeśli planowy koniec potwierdzonej rezerwacji minął, a maszyna nie wróciła, na pulpicie pojawi się alert „Maszyny do zwrotu". System nie zamyka takiej rezerwacji automatycznie — przedłuża ją do dnia faktycznego zwrotu (Hard Return Policy), żeby maszyna nie „zniknęła" z ewidencji.

### 5.4. Rezerwacje grupowe

Możesz utworzyć rezerwację grupową (kilka maszyn naraz) i następnie zbiorczo **potwierdzić wszystkie**, **anulować wszystkie** lub **zmienić operatora wszystkim**.

---

## 6. Budowy

Przejdź do **Budowy** w menu.

1. **Dodawanie:** kliknij **Dodaj budowę**, wprowadź numer projektu, nazwę i adres, a następnie zapisz.
2. **Edycja:** otwórz budowę i kliknij **Edytuj**.
3. **Usuwanie:** budowę można **usunąć** — ta operacja jest dostępna dla administratora.
4. Z karty budowy zobaczysz wszystkie powiązane z nią rezerwacje.

---

## 7. Serwis (rejestr serwisowy)

Przejdź do **Serwis** w menu. Rejestr zawiera przeglądy techniczne i naprawy maszyn. Koszty są prowadzone w walucie **EUR**.

### 7.1. Dodawanie i edycja wpisu serwisowego

1. Kliknij **Dodaj wpis** (na liście serwisu).
2. Wybierz maszynę, rodzaj czynności (przegląd / naprawa), datę (dd.mm.rrrr), koszt w EUR i opis.
3. Zapisz. Po przeglądzie system automatycznie wyliczy termin kolejnego przeglądu.
4. Aby zmienić istniejący wpis, otwórz go i kliknij **Edytuj**.

### 7.2. Usuwanie wpisu serwisowego

Wpisy serwisowe może **usuwać wyłącznie administrator**. Otwórz wpis i wybierz **Usuń**, a następnie potwierdź.

### 7.3. Przeglądy zbiorcze

Opcja **przeglądów zbiorczych** pozwala wprowadzić wykonane przeglądy dla wielu maszyn za jednym razem.

---

## 8. Raporty

Przejdź do **Raporty** w menu (sekcja serwisowa).

System udostępnia kilka rodzajów raportów:

- **Raport kwartalny (XLSX)** — zestawienie kosztów i przeglądów za wybrany kwartał. Wybierz rok i kwartał, następnie pobierz plik Excel.
- **Raport roczny (PDF)** — podsumowanie za cały rok.
- **Karta serwisowa maszyny (PDF)** — pełna historia serwisowa konkretnej maszyny.
- **Wykres kosztów per maszyna** — graficzne porównanie kosztów serwisu poszczególnych maszyn.
- **Eksport do Excela z aktywnymi filtrami** — pobrany plik uwzględnia filtry ustawione na ekranie (np. wybrana maszyna lub okres), dzięki czemu otrzymujesz dokładnie taki zakres danych, jaki widzisz.

Wszystkie kwoty raportowane są w **EUR**, a daty w formacie **dd.mm.rrrr**.

---

## 9. Pracownicy (zarządzanie kontami)

Sekcja **Pracownicy** w menu (część „Administracja") jest dostępna **tylko dla administratora**.

### 9.1. Zakładanie konta pracownika

1. Wejdź w **Pracownicy** i kliknij dodawanie nowego pracownika.
2. Wypełnij **dane logowania** (nazwa użytkownika, e-mail), **dane osobowe** (imię, nazwisko) oraz **funkcję** (rolę) i opcjonalnie telefon.
3. Ustaw **hasło**. Hasło jest sprawdzane w bazie publicznych wycieków **Have I Been Pwned** — jeśli kiedykolwiek pojawiło się w wycieku, system je odrzuci. Minimalna długość to 10 znaków (zalecane 12+).
4. Zapisz. Konto użytkownika i profil pracownika powstają w jednej operacji, a wybrana funkcja od razu nadaje odpowiednie uprawnienia (RBAC).

Dostępne funkcje (role) odpowiadają grupom uprawnień:

- **Administrator** — pełny dostęp do wszystkich funkcji.
- **Magazynier** — obsługa rezerwacji i serwisu (bez usuwania, bez kont pracowników i panelu admina).
- **Kierownik** — składanie wniosków o rezerwacje oraz zarządzanie budowami.
- **Montażysta** — dostęp tylko do odczytu (bez kosztów i bez funkcji administracyjnych).

### 9.2. Lista i filtrowanie pracowników

Na liście pracowników możesz filtrować po statusie (aktywni / zwolnieni / zanonimizowani / wszyscy) oraz funkcji, a także wyszukiwać po nazwisku, nazwie użytkownika, e-mailu lub telefonie.

### 9.3. Zwolnienie pracownika

1. Na liście pracowników wybierz osobę i użyj akcji **Zwolnij** (wymaga potwierdzenia).
2. System zakończy zatrudnienie: usunie aktywne sesje i wyczyści przypisane grupy uprawnień. Pracownik nie będzie mógł się zalogować.

> Nie możesz zwolnić własnego konta.

### 9.4. Anonimizacja danych (RODO / prawo do bycia zapomnianym)

1. Dla zwolnionego pracownika dostępna jest akcja **Anonimizuj** (RODO, Art. 17).
2. Operacja jest **nieodwracalna** — dane osobowe (PII) zostaną trwale zastąpione, a konto zachowane wyłącznie jako anonimowy ślad w ewidencji.
3. Potwierdź operację. Zanonimizowane profile znajdziesz na liście pod filtrem „zanonimizowani".

> Nie możesz zanonimizować własnego profilu.

---

## 10. Panel administracyjny i dziennik zdarzeń

W menu (sekcja „Administracja") znajdziesz **Panel admina** — wbudowany panel Django dla zaawansowanego zarządzania danymi.

### 10.1. Dziennik zdarzeń (audyt)

- W panelu administracyjnym dostępny jest **dziennik zdarzeń (audit log)** — rejestr wszystkich istotnych operacji w systemie (kto, co, kiedy, z jakiego adresu).
- Wpisy są **tylko do odczytu** — nie można ich dodawać, edytować ani usuwać z poziomu panelu, dzięki czemu pozostają wiarygodnym dowodem.
- Dziennik można **filtrować** (po akcji, typie obiektu, dacie, użytkowniku) oraz **eksportować zaznaczone wpisy do pliku CSV**.
- System automatycznie usuwa wpisy starsze niż 90 dni (retencja danych).

---

## 11. Język, motyw i profil

### 11.1. Zmiana języka (PL / EN)

W prawym górnym rogu (pasek u góry) znajduje się **przełącznik języka**. Wybierz **Polski** lub **English** — interfejs przełączy się natychmiast, bez przeładowania strony. Wybór jest zapamiętywany.

### 11.2. Tryb jasny / ciemny

Obok przełącznika języka znajduje się **przycisk motywu** (ikona słońca / księżyca). Kliknij, aby przełączyć między trybem jasnym a ciemnym. Ustawienie jest zapamiętywane między sesjami.

### 11.3. Profil użytkownika

1. Kliknij swoje imię/inicjał w menu po lewej, aby otworzyć **profil**.
2. Możesz tu zaktualizować podstawowe dane oraz preferowany język (który stanie się domyślnym językiem interfejsu po zalogowaniu).
3. W stopce strony dostępna jest opcja **Moje dane (eksport)** — pobranie własnych danych w formacie JSON (RODO, prawo do przenoszalności danych).

---

## 12. Asystent (chatbot)

Dla zalogowanych użytkowników dostępny jest **Asystent** — okno konwersacyjne (przycisk w rogu ekranu). Możesz zadawać pytania o maszyny, rezerwacje i historię serwisową w języku naturalnym. Operacje zapisujące dane wymagają dodatkowego potwierdzenia, zanim asystent je wykona.

---

## 13. Najczęstsze problemy

- **Nie mogę się zalogować po kilku próbach** — konto jest tymczasowo zablokowane (5 błędnych prób = 1 godzina). Odczekaj i spróbuj ponownie.
- **Nie mam kodu 2FA** — użyj jednego z zapisanych **kodów zapasowych** w polu weryfikacji.
- **Nie widzę sekcji „Pracownicy" lub „Panel admina"** — sprawdź, czy jesteś zalogowany na koncie administratora.
- **Daty wyświetlają się inaczej** — w całym systemie obowiązuje europejski format **dd.mm.rrrr**.
- **Kwoty w EUR** — wszystkie koszty serwisowe i raporty prowadzone są w euro.
