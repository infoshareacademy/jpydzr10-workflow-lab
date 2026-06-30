# Instrukcja użytkownika — Magazynier

Planer Maszyn Budowlanych — system rezerwacji i serwisu maszyn dla firmy budowlanej.

Ta instrukcja jest przeznaczona dla osoby pełniącej rolę **Magazyniera**. Magazynier zarządza codziennym obiegiem maszyn: obsługuje rezerwacje, zmienia statusy maszyn, prowadzi rejestr serwisowy, zakłada i edytuje budowy oraz korzysta z raportów. Instrukcja prowadzi krok po kroku i nie wymaga wiedzy technicznej.

## Co magazynier może, a czego nie może

Magazynier ma szerokie uprawnienia operacyjne, ale **węższe niż administrator**. Najważniejsze różnice:

**Magazynier MOŻE:**

- Zatwierdzać, anulować i kończyć rezerwacje.
- Dodawać i edytować wpisy serwisowe.
- Zmieniać statusy maszyn (zwrot, skierowanie do serwisu, zakończenie naprawy).
- Tworzyć i edytować budowy.
- Korzystać z raportów i widzieć koszty (w EUR).

**Magazynier NIE MOŻE:**

- Tworzyć ani usuwać maszyn.
- Edytować formularza rezerwacji (zmiana maszyny/terminu w samym formularzu — to robi administrator).
- Usuwać wpisów serwisowych.
- Usuwać budów.
- Zarządzać kontami pracowników.
- Wchodzić do panelu administracyjnego (`/admin/`).

Jeśli spróbujesz wejść w funkcję, do której nie masz uprawnień, system pokaże stronę z komunikatem o braku dostępu (błąd 403).

---

## 1. Logowanie do systemu

1. Otwórz przeglądarkę i wejdź pod adres aplikacji (lokalnie: `http://localhost:8002`).
2. Kliknij **Zaloguj się** w menu po lewej stronie.
3. Wpisz swoją **nazwę użytkownika** oraz **hasło** i zatwierdź.

Jeśli pięć razy z rzędu wpiszesz błędne hasło, konto zostanie tymczasowo zablokowane na jedną godzinę (ochrona przed włamaniem). Odczekaj i spróbuj ponownie.

---

## 2. Uwierzytelnianie dwuskładnikowe (2FA)

Konto magazyniera wymaga drugiego składnika logowania (kodu z aplikacji w telefonie). To dodatkowe zabezpieczenie: nawet jeśli ktoś pozna Twoje hasło, bez kodu nie zaloguje się na Twoje konto.

### 2.1. Pierwsza konfiguracja 2FA

1. Po zalogowaniu system przekieruje Cię na stronę konfiguracji 2FA.
2. Zainstaluj w telefonie aplikację uwierzytelniającą (np. Google Authenticator).
3. Zeskanuj wyświetlony **kod QR**. Jeśli nie możesz zeskanować, przepisz ręcznie **klucz tekstowy** podany pod kodem.
4. Wpisz w pole na stronie **aktualny sześciocyfrowy kod** wygenerowany przez aplikację i zatwierdź.

### 2.2. Kody zapasowe

1. Po konfiguracji system wygeneruje **10 jednorazowych kodów zapasowych**.
2. Pobierz je jako plik `kody-zapasowe-2fa.txt` i zapisz w bezpiecznym miejscu poza telefonem.
3. Każdy kod zapasowy działa **tylko raz** — używaj ich, gdy nie masz dostępu do telefonu.

> **Ważne:** kody zapasowe pobierzesz tylko raz, zaraz po konfiguracji. Jeśli zgubisz telefon i nie masz kodów, odzyskanie dostępu będzie wymagało pomocy administratora.

### 2.3. Logowanie z 2FA (każde kolejne)

1. Wpisz nazwę użytkownika i hasło.
2. Na stronie weryfikacji wpisz **aktualny kod** z aplikacji uwierzytelniającej (lub jeden z kodów zapasowych).

Po kilku błędnych próbach kod zostanie chwilowo zablokowany — odczekaj moment i spróbuj ponownie.

---

## 3. Pulpit (dashboard) — Twój początek dnia

Po zalogowaniu trafiasz na **Panel główny**. To Twoje centrum operacyjne na początek dnia.

- **Karty wskaźników (KPI)** u góry:
  - **Dostępne maszyny** — ile maszyn jest w magazynie.
  - **Aktualnie na budowie** — ile maszyn jest w terenie.
  - **Aktywne rezerwacje** — ile rezerwacji trwa (i ile czeka na potwierdzenie).
  - **Przeglądy techniczne** — ile maszyn ma przeterminowany lub zbliżający się przegląd (kliknij, aby zobaczyć listę).
- **Sekcja „Dziś w magazynie"** — trzy kolumny, które pokazują plan dnia:
  - **Wyjeżdżają dziś** — maszyny, które dziś mają wyjechać na budowę.
  - **Wracają dziś** — maszyny, które dziś powinny wrócić (sprawdź ich stan przy zwrocie).
  - **Dziś w trasie** — maszyny aktualnie pracujące w terenie.
- **Alerty** o spóźnionych zwrotach i przeterminowanych przeglądach (gdy występują).

> **Synchronizacja statusów:** w sekcji „Dziś w magazynie" masz przycisk **Synchronizuj statusy**. Wymusza on natychmiastowe dopasowanie statusów maszyn do aktualnych rezerwacji (zwykle system robi to automatycznie raz dziennie rano). Użyj go, gdy chcesz mieć pewność, że dane są aktualne.

---

## 4. Rezerwacje — Twoja główna praca

Przejdź do **Rezerwacje** lub do **Oś czasu** (timeline) w menu po lewej.

### 4.1. Oś czasu (timeline)

Oś czasu to wizualny harmonogram — wiersze to maszyny, kolumny to dni, a kolorowe belki pokazują rezerwacje. Kliknięcie belki otwiera szczegóły rezerwacji. To wygodny sposób, by jednym rzutem oka zobaczyć obłożenie całej floty.

### 4.2. Tworzenie rezerwacji

1. Kliknij **Nowa rezerwacja** (na pulpicie, liście rezerwacji lub osi czasu).
2. Wybierz **maszynę**, **termin** (data początku i końca w formacie **dd.mm.rrrr**), **budowę** lub adres oraz osobę odpowiedzialną.
3. System automatycznie sprawdza **konflikty terminów**. Pamiętaj: stykające się daty są traktowane jako konflikt — maszyna potrzebuje jednego dnia na transport między budowami.
4. Zapisz. Rezerwacja otrzyma status **Oczekująca**.

### 4.3. Zatwierdzanie, kończenie i anulowanie rezerwacji

Rezerwacja przechodzi przez statusy: **Oczekująca → Potwierdzona → Zakończona** (lub **Anulowana**).

Otwórz szczegóły rezerwacji (klik na liście lub osi czasu). W zależności od statusu zobaczysz przyciski:

- **Potwierdź rezerwację** — dla rezerwacji oczekującej. Po potwierdzeniu osoba wynajmująca otrzyma e-mail z potwierdzeniem.
- **Zakończ (zwrot maszyny)** — dla rezerwacji potwierdzonej, gdy maszyna wraca. Status zmieni się na „Zakończona", a maszyna wróci do magazynu.
- **Anuluj** — gdy rezerwacja nie dojdzie do skutku.
- **Zgłoś awarię** — gdy maszyna uległa awarii w trakcie rezerwacji.
- **Zmień osobę** — zmiana operatora przypisanego do rezerwacji.

> **Uwaga:** edycja samego **formularza** rezerwacji (zmiana maszyny lub terminu w formularzu) jest zarezerwowana dla administratora. Jako magazynier sterujesz rezerwacją poprzez powyższe akcje (potwierdź / zakończ / anuluj / zmień osobę), a nie przez ponowne otwarcie formularza edycji.

### 4.4. Spóźnione zwroty

Jeśli planowy koniec potwierdzonej rezerwacji minął, a maszyna nie wróciła, na pulpicie pojawi się alert **„Maszyny do zwrotu"**. Kliknij go, aby zobaczyć listę i skontaktować się z osobą wynajmującą. System nie zamyka takiej rezerwacji sam — przedłuża ją do dnia faktycznego zwrotu, żeby maszyna nie zniknęła z ewidencji.

### 4.5. Rezerwacje grupowe

Możesz obsłużyć rezerwację grupową (kilka maszyn naraz) i zbiorczo **potwierdzić wszystkie**, **anulować wszystkie** lub **zmienić operatora wszystkim**.

---

## 5. Maszyny — zmiana statusów

Przejdź do **Maszyny** w menu. Jako magazynier **przeglądasz** maszyny i **zmieniasz ich statusy**, ale nie tworzysz ani nie usuwasz maszyn (to robi administrator).

### 5.1. Przeglądanie

- Lista pokazuje maszyny ze statusem: **W magazynie**, **Na budowie**, **Zarezerwowana**, **W serwisie**.
- Użyj filtrów i wyszukiwarki, aby szybko znaleźć maszynę.
- Kliknij maszynę, aby zobaczyć jej kartę (dane, historia rezerwacji i serwisu, daty przeglądów).

### 5.2. Zmiana statusu maszyny

Z poziomu karty maszyny możesz:

- **Zarejestrować zwrot** — maszyna wraca z budowy do magazynu.
- **Skierować do serwisu** — oznaczyć maszynę jako „W serwisie".
- **Zakończyć naprawę** — maszyna wraca z serwisu do magazynu.

> Przyciski **dodania nowej maszyny** oraz **usunięcia maszyny** nie są dla Ciebie dostępne. Jeśli potrzebujesz dodać lub usunąć maszynę, poproś administratora.

---

## 6. Budowy

Przejdź do **Budowy** w menu.

1. **Dodawanie:** kliknij **Dodaj budowę**, wpisz numer projektu, nazwę i adres, a następnie zapisz.
2. **Edycja:** otwórz budowę i kliknij **Edytuj**, aby zaktualizować dane.
3. Z karty budowy zobaczysz wszystkie powiązane rezerwacje.

> **Usuwanie budów** nie jest dla Ciebie dostępne — tę operację wykonuje administrator (lub kierownik). Możesz tworzyć i edytować budowy, ale nie kasować.

---

## 7. Serwis (rejestr serwisowy)

Przejdź do **Serwis** w menu. Rejestr zawiera przeglądy techniczne i naprawy maszyn. Koszty są prowadzone w walucie **EUR**.

### 7.1. Dodawanie wpisu serwisowego

1. Kliknij **Dodaj wpis**.
2. Wybierz maszynę, rodzaj czynności (przegląd / naprawa), datę (**dd.mm.rrrr**), koszt w **EUR** i opis.
3. Zapisz. Po wprowadzeniu przeglądu system automatycznie wyliczy termin kolejnego przeglądu.

### 7.2. Edycja wpisu serwisowego

Otwórz istniejący wpis i kliknij **Edytuj**, aby poprawić dane.

> **Usuwanie wpisów serwisowych** nie jest dla Ciebie dostępne — kasowanie wpisów może wykonać wyłącznie administrator. Jeśli wpis trzeba usunąć, zgłoś to administratorowi.

### 7.3. Przeglądy zbiorcze

Opcja **przeglądów zbiorczych** pozwala wprowadzić wykonane przeglądy dla wielu maszyn za jednym razem — wygodne, gdy serwis obsłużył kilka maszyn jednego dnia.

---

## 8. Raporty i koszty

Przejdź do **Raporty** w menu. Jako magazynier masz dostęp do raportów i widzisz koszty serwisowe (w EUR).

Dostępne raporty:

- **Raport kwartalny (XLSX)** — wybierz rok i kwartał, pobierz zestawienie kosztów i przeglądów w Excelu.
- **Raport roczny (PDF)** — podsumowanie za cały rok.
- **Karta serwisowa maszyny (PDF)** — historia serwisowa wybranej maszyny.
- **Wykres kosztów per maszyna** — porównanie kosztów serwisu poszczególnych maszyn.
- **Eksport do Excela z aktywnymi filtrami** — pobrany plik zawiera dokładnie taki zakres danych, jaki ustawiłeś filtrami na ekranie.

Wszystkie kwoty są w **EUR**, a daty w formacie **dd.mm.rrrr**.

---

## 9. Język, motyw i profil

### 9.1. Zmiana języka (PL / EN)

W prawym górnym rogu (pasek u góry) znajduje się **przełącznik języka**. Wybierz **Polski** lub **English** — interfejs przełączy się natychmiast. Wybór jest zapamiętywany.

### 9.2. Tryb jasny / ciemny

Obok przełącznika języka jest **przycisk motywu** (słońce / księżyc). Kliknij, aby przełączyć między trybem jasnym a ciemnym. Ustawienie jest zapamiętywane.

### 9.3. Profil użytkownika

1. Kliknij swoje imię/inicjał w menu po lewej, aby otworzyć **profil**.
2. Możesz tu zaktualizować podstawowe dane oraz preferowany język interfejsu.
3. W stopce strony dostępna jest opcja **Moje dane (eksport)** — pobranie własnych danych w formacie JSON (RODO, prawo do przenoszalności danych).

---

## 10. Asystent (chatbot)

Dla zalogowanych użytkowników dostępny jest **Asystent** — okno konwersacyjne (przycisk w rogu ekranu). Możesz zadawać pytania o maszyny, rezerwacje i historię serwisową zwykłym językiem. Operacje, które zapisują dane, wymagają dodatkowego potwierdzenia, zanim asystent je wykona.

---

## 11. Najczęstsze problemy

- **Widzę stronę „brak dostępu" (403)** — próbujesz wejść w funkcję zarezerwowaną dla administratora (np. usuwanie maszyny, panel admina, zarządzanie pracownikami). To normalne — skontaktuj się z administratorem, jeśli dana operacja jest potrzebna.
- **Nie mogę się zalogować po kilku próbach** — konto jest tymczasowo zablokowane (5 błędnych prób = 1 godzina). Odczekaj i spróbuj ponownie.
- **Nie mam kodu 2FA** — użyj jednego z zapisanych **kodów zapasowych**.
- **Nie widzę przycisku „Dodaj maszynę" lub „Usuń"** — to celowe: magazynier nie tworzy ani nie usuwa maszyn, wpisów serwisowych i budów.
- **Daty i kwoty** — w całym systemie obowiązuje format daty **dd.mm.rrrr**, a koszty prowadzone są w **EUR**.
