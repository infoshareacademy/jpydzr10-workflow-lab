"""
Interfejs konsolowy: menu główne, formularze, ekrany.

Zawiera też helpery do pobierania danych od użytkownika
(input_date, input_choice) — bo to warstwa I/O, nie logika biznesowa.
"""

from datetime import date, datetime

from models import Machine, Reservation, ServiceRecord
from datastore import DataStore
from exceptions import DataCorruptionError
from logic import has_conflict, run_daily_sync
from utils import parse_date, generate_unique_id


# =============================================================================
# HELPERY DO INPUTU (przeniesione z logic.py — należą do warstwy UI)
# =============================================================================


def input_date(prompt: str) -> str:
    """Pobiera datę od użytkownika, powtarza aż format będzie prawidłowy."""
    while True:
        value = input(prompt).strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            print("  Zły format. Użyj RRRR-MM-DD.")


def input_choice(prompt: str, valid: tuple[str, ...]) -> str:
    """Pobiera wybór z ograniczonej listy wartości."""
    while True:
        value = input(prompt).strip()
        if value in valid:
            return value
        print(f"  Dozwolone: {', '.join(valid)}")


def input_required(prompt: str) -> str:
    """Pobiera niepusty string od użytkownika."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("  Pole wymagane — nie może być puste.")


# =============================================================================
# APLIKACJA
# =============================================================================


class App:
    """Główna klasa aplikacji — menu i formularze."""

    SEP = "=" * 65
    LINE = "-" * 65

    def __init__(self):
        self.store = DataStore()
        # Kolekcje, których pliki były uszkodzone przy starcie.
        # Zapis do nich jest blokowany, żeby nie nadpisać danych na dysku.
        self._corrupted: set[str] = set()
        self.machines: list[Machine] = self._safe_load(
            "machines", self.store.load_machines
        )
        self.reservations: list[Reservation] = self._safe_load(
            "reservations", self.store.load_reservations
        )
        self.service_records: list[ServiceRecord] = self._safe_load(
            "service", self.store.load_service_records
        )
        # Flagi śledzące które kolekcje zostały zmodyfikowane od ostatniego zapisu.
        # Celowane zapisy (save_machines itp.) ustawiają flagę na False.
        # save_all() przy wyjściu zapisuje tylko zmienione kolekcje.
        self._dirty: set[str] = set()

    def _safe_load(self, name: str, loader) -> list:
        """Wczytuje dane z graceful error handling.

        DataStore automatycznie próbuje wczytać .bak jeśli główny plik
        jest uszkodzony. Jeśli oba pliki są uszkodzone, rzuca
        DataCorruptionError — tutaj łapiemy go i wyświetlamy czytelny
        komunikat zamiast surowego traceback.

        Kolekcja jest dodawana do _corrupted, co blokuje późniejszy
        zapis — uszkodzone pliki NIE są nadpisywane pustą listą.
        """
        try:
            return loader()
        except DataCorruptionError as e:
            print(f"\n  BŁĄD: {e}")
            print(f"  Kontynuuję z pustą listą dla: {name}.")
            print(f"  Uszkodzone pliki NIE zostały nadpisane — sprawdź je ręcznie.\n")
            self._corrupted.add(name)
            return []

    def save_all(self) -> None:
        """Zapisuje tylko zmodyfikowane kolekcje (celowany zapis przy wyjściu).

        Kolekcje z _corrupted są pomijane — nie nadpisujemy uszkodzonych
        plików pustą/częściową listą.
        """
        if "machines" in self._dirty:
            self._save_machines()
        if "reservations" in self._dirty:
            self._save_reservations()
        if "service" in self._dirty:
            self._save_service_records()
        self._dirty.clear()

    def _save_machines(self) -> None:
        """Celowany zapis maszyn z oznaczeniem jako czyste."""
        if "machines" in self._corrupted:
            print("  UWAGA: Zapis maszyn pominięty — plik był uszkodzony przy starcie.")
            return
        self.store.save_machines(self.machines)
        self._dirty.discard("machines")

    def _save_reservations(self) -> None:
        """Celowany zapis rezerwacji z oznaczeniem jako czyste."""
        if "reservations" in self._corrupted:
            print("  UWAGA: Zapis rezerwacji pominięty — plik był uszkodzony przy starcie.")
            return
        self.store.save_reservations(self.reservations)
        self._dirty.discard("reservations")

    def _save_service_records(self) -> None:
        """Celowany zapis wpisów serwisowych z oznaczeniem jako czyste."""
        if "service" in self._corrupted:
            print("  UWAGA: Zapis serwisu pominięty — plik był uszkodzony przy starcie.")
            return
        self.store.save_service_records(self.service_records)
        self._dirty.discard("service")

    def find_machine(self, uid: str) -> Machine | None:
        return next((m for m in self.machines if m.uid == uid), None)

    # -------------------------------------------------------------------------
    # Ekrany — wyświetlanie danych
    # -------------------------------------------------------------------------

    def show_machines(self) -> None:
        print(f"\n{'UID':<14} {'Nazwa':<22} {'Status':<16} Lokalizacja")
        print(self.LINE)
        if not self.machines:
            print("  Brak maszyn. Użyj opcji 10 żeby zaimportować z pliku.")
            return
        for m in self.machines:
            insp = Machine.check_inspection_status(m.inspection_date)
            markers = {"warning": " [!]", "overdue": " [PRZETERMINOWANY]"}
            marker = markers.get(insp, "")
            print(f"{m}{marker}")

    def show_reservations(self) -> None:
        for label, st in [
            ("Oczekujące", "pending"),
            ("Aktywne", "confirmed"),
            ("Zakończone", "completed"),
            ("Anulowane", "rejected"),
        ]:
            group = [r for r in self.reservations if r.status == st]
            if group:
                print(f"\n--- {label} ({len(group)}) ---")
                for r in group:
                    print(f"  {r}")
        if not self.reservations:
            print("\n  Brak rezerwacji w systemie.")

    def show_service_history(self) -> None:
        """Formularz historii serwisowej — pobiera filtr i wyświetla."""
        print("\n--- HISTORIA SERWISOWA ---")
        uid = input("UID maszyny (Enter = wszystkie): ").strip()
        self._display_service_records(uid)

    def _display_service_records(self, uid: str = "") -> None:
        """Wyświetla wpisy serwisowe (opcjonalnie filtrowane po UID).

        Wydzielone z show_service_history, żeby logika wyświetlania
        była testowalna bez input().
        """
        records = [r for r in self.service_records if not uid or r.machine_id == uid]
        if not records:
            print("  Brak wpisów.")
            return

        print(f"\n{'Data':<12} {'Typ':<12} {'Koszt':<14} Opis")
        print(self.LINE)
        total = 0.0
        for r in records:
            print(f"  {r}")
            total += r.cost
        print(self.LINE)
        print(f"  ŁĄCZNY KOSZT: {total:.2f} EUR")

    # -------------------------------------------------------------------------
    # Formularze — tworzenie i edycja
    # -------------------------------------------------------------------------

    def create_reservation(self) -> None:
        """Tworzy nową rezerwację.

        FIX: Po utworzeniu rezerwacji ustawia status maszyny:
        - 'Op de werf' jeśli rezerwacja zaczyna się dziś lub wcześniej
        - 'Gereserveerd' jeśli rezerwacja jest w przyszłości
        FIX: Walidacja wymaganych pól (osoba, numer projektu)
        FIX: generate_unique_id zamiast generate_id (sprawdza kolizje)
        """
        print("\n--- NOWA REZERWACJA ---")
        available = [
            m for m in self.machines
            if m.status in ("In Magazijn", "Gereserveerd")
        ]
        if not available:
            print("  Brak wolnych maszyn!")
            return

        available_uids = {m.uid for m in available}

        print("\nDostępne maszyny:")
        for m in available:
            print(f"  {m.uid:<14} {m.name:<22} {m.status}")

        uid = input("\nUID maszyny: ").strip()
        if uid not in available_uids:
            print("  Maszyna nie jest dostępna (nie ma jej na liście wolnych).")
            return

        start = input_date("Data od (RRRR-MM-DD): ")
        end = input_date("Data do (RRRR-MM-DD): ")

        if not Reservation.validate_date_range(start, end):
            print("  Data końca nie może być wcześniejsza niż początku.")
            return

        if has_conflict(self.reservations, uid, start, end):
            print("  Maszyna jest już zarezerwowana w tym terminie!")
            return

        person = input_required("Osoba odpowiedzialna: ")
        project = input_required("Numer projektu: ")
        address = input("Adres budowy: ").strip()

        existing_ids = {r.id for r in self.reservations}
        res_id = generate_unique_id("RES-", existing_ids)

        # Status "confirmed" od razu — w Isocab rezerwacje tworzy warehouse manager,
        # więc nie ma procesu zatwierdzania. Status "pending" w VALID_STATUSES
        # pozostaje na przyszłość (Milestone 2: multi-user z rolami).
        res = Reservation(
            res_id, uid, start, end, person, project, address, "confirmed"
        )
        self.reservations.append(res)

        # Ustaw status maszyny na podstawie daty rozpoczęcia
        machine = self.find_machine(uid)
        if not machine:
            print("  Błąd wewnętrzny: nie znaleziono maszyny po walidacji.")
            return

        today = date.today()
        start_date = parse_date(start)

        if start_date <= today:
            machine.status = "Op de werf"
            machine.location = address or machine.location
        else:
            machine.status = "Gereserveerd"

        self._dirty.add("reservations")
        self._save_reservations()
        self._dirty.add("machines")
        self._save_machines()
        print(f"\n  Rezerwacja utworzona: {res.title}")

    def return_machine(self) -> None:
        """Realizuje zwrot maszyny do magazynu.

        FIX: Zamyka tylko rezerwacje, które obejmują dzisiejszą datę
        (start <= today <= end), nie wszystkie z start <= today.
        Rezerwacje w przyszłości pozostają nienaruszone.
        """
        print("\n--- ZWROT MASZYNY ---")
        on_site = [m for m in self.machines if m.status == "Op de werf"]
        if not on_site:
            print("  Brak maszyn do zwrotu.")
            return

        print("\nMaszyny na budowie:")
        for m in on_site:
            print(f"  {m.uid:<14} {m.name:<22} {m.location}")

        uid = input("\nUID maszyny: ").strip()
        machine = self.find_machine(uid)
        if not machine or machine.status != "Op de werf":
            print("  Nie znaleziono maszyny na budowie.")
            return

        today = date.today()
        for res in self.reservations:
            if res.machine_id != uid:
                continue
            if res.status != "confirmed":
                continue

            res_start = parse_date(res.start_date)
            res_end = parse_date(res.end_date)

            # Zamknij tylko bieżące rezerwacje (obejmujące dziś)
            if res_start <= today <= res_end:
                res.status = "completed"
            # Przeterminowane (przedłużone przez sync) — też zamknij
            elif res_end < today:
                res.status = "completed"

        machine.status = "In Magazijn"
        machine.location = "Magazyn"

        # Sprawdź czy maszyna ma rezerwację w przyszłości
        has_future = any(
            r for r in self.reservations
            if r.machine_id == uid
            and r.status == "confirmed"
            and parse_date(r.start_date) > today
        )
        if has_future:
            machine.status = "Gereserveerd"

        self._dirty.add("reservations")
        self._save_reservations()
        self._dirty.add("machines")
        self._save_machines()
        print(f"  Maszyna {uid} zwrócona do magazynu.")

    def edit_machine(self) -> None:
        """Edycja danych maszyny z poziomu konsoli."""
        print("\n--- EDYCJA MASZYNY ---")
        uid = input("UID maszyny do edycji: ").strip()
        machine = self.find_machine(uid)
        if not machine:
            print("  Nie znaleziono maszyny.")
            return

        print(f"\n  Edytujesz: {machine.name} ({machine.uid})")
        print("  (Enter = pozostaw obecną wartość)\n")

        new_name = input(f"  Nazwa [{machine.name}]: ").strip()
        if new_name:
            machine.name = new_name

        new_model = input(f"  Model [{machine.model}]: ").strip()
        if new_model:
            machine.model = new_model

        new_location = input(f"  Lokalizacja [{machine.location}]: ").strip()
        if new_location:
            machine.location = new_location

        print(f"\n  Dozwolone statusy: {', '.join(Machine.VALID_STATUSES)}")
        new_status = input(f"  Status [{machine.status}]: ").strip()
        if new_status:
            try:
                machine.status = new_status
            except ValueError as e:
                print(f"  {e} — status pozostaje bez zmian.")

        self._dirty.add("machines")
        self._save_machines()
        print(f"  Maszyna {uid} zaktualizowana.")

    def edit_reservation(self) -> None:
        """Edycja istniejącej rezerwacji z poziomu konsoli."""
        print("\n--- EDYCJA REZERWACJI ---")

        active = [r for r in self.reservations if r.status in ("pending", "confirmed")]
        if not active:
            print("  Brak aktywnych rezerwacji do edycji.")
            return

        print("\nAktywne rezerwacje:")
        for i, r in enumerate(active, 1):
            print(f"  {i}. {r}")

        try:
            choice = int(input("\nNumer rezerwacji z listy powyżej: ").strip())
            if choice < 1:
                raise IndexError
            res = active[choice - 1]
        except (ValueError, IndexError):
            print("  Nieprawidłowy wybór.")
            return

        print(f"\n  Edytujesz: {res.id}")
        print("  (Enter = pozostaw obecną wartość)\n")

        new_person = input(f"  Osoba [{res.person}]: ").strip()
        if new_person:
            res.person = new_person

        new_project = input(f"  Nr projektu [{res.project_number}]: ").strip()
        if new_project:
            res.project_number = new_project

        new_address = input(f"  Adres [{res.address}]: ").strip()
        if new_address:
            res.address = new_address

        new_end = input(f"  Data końca [{res.end_date}] (RRRR-MM-DD): ").strip()
        if new_end:
            try:
                parse_date(new_end)  # walidacja formatu
                if not Reservation.validate_date_range(res.start_date, new_end):
                    print("  Data końca wcześniejsza niż początku — zmiana daty pominięta.")
                elif has_conflict(
                    self.reservations, res.machine_id, res.start_date, new_end,
                    exclude_id=res.id,
                ):
                    print("  Nowy termin koliduje z inną rezerwacją — zmiana daty pominięta.")
                else:
                    res.end_date = new_end
            except ValueError:
                print("  Zły format daty — zmiana pominięta.")

        self._dirty.add("reservations")
        self._save_reservations()
        print(f"  Rezerwacja {res.id} zaktualizowana.")

    def cancel_reservation(self) -> None:
        """Anulowanie (odrzucenie) rezerwacji.

        FIX: Obsługuje status 'Gereserveerd' — jeśli maszyna była
        zarezerwowana na przyszłość i nie ma innych rezerwacji,
        wraca do 'In Magazijn'.
        """
        print("\n--- ANULOWANIE REZERWACJI ---")

        active = [r for r in self.reservations if r.status in ("pending", "confirmed")]
        if not active:
            print("  Brak aktywnych rezerwacji do anulowania.")
            return

        print("\nAktywne rezerwacje:")
        for i, r in enumerate(active, 1):
            print(f"  {i}. {r}")

        try:
            choice = int(input("\nNumer rezerwacji do anulowania: ").strip())
            if choice < 1:
                raise IndexError
            res = active[choice - 1]
        except (ValueError, IndexError):
            print("  Nieprawidłowy wybór.")
            return

        confirm = input(f"  Na pewno anulować {res.id}? (t/n): ").strip().lower()
        if confirm != "t":
            print("  Anulowanie przerwane.")
            return

        res.status = "rejected"

        # Sprawdź czy maszyna powinna wrócić do magazynu
        machine = self.find_machine(res.machine_id)
        if machine and machine.status in ("Op de werf", "Gereserveerd"):
            other_active = [
                r for r in self.reservations
                if r.machine_id == res.machine_id
                and r.status == "confirmed"
                and r.id != res.id
            ]
            if not other_active:
                if machine.status == "Op de werf":
                    print("  UWAGA: Maszyna była 'Op de werf' — upewnij się, że fizycznie wróciła.")
                machine.status = "In Magazijn"
                machine.location = "Magazyn"

        self._dirty.add("reservations")
        self._save_reservations()
        self._dirty.add("machines")
        self._save_machines()
        print(f"  Rezerwacja {res.id} anulowana.")

    def add_service_record(self) -> None:
        print("\n--- NOWY WPIS SERWISOWY ---")
        uid = input("UID maszyny: ").strip()
        machine = self.find_machine(uid)
        if not machine:
            print("  Nie znaleziono maszyny.")
            return

        record_type = input_choice(
            "Typ (inspection / repair): ", ("inspection", "repair")
        )
        record_date = input_date("Data (RRRR-MM-DD): ")
        description = input("Opis: ").strip()

        cost = 0.0
        if record_type == "repair":
            try:
                cost = float(input("Koszt (EUR): ").strip())
                if cost < 0:
                    print("  Koszt nie może być ujemny — ustawiam 0.00 EUR.")
                    cost = 0.0
            except ValueError:
                cost = 0.0

        next_insp = ""
        if record_type == "inspection":
            interval = input("Interwał miesięcy (domyślnie 3): ").strip()
            interval = int(interval) if interval.isdigit() else 3
            next_insp = ServiceRecord.calculate_next_inspection(record_date, interval)
            machine.inspection_date = next_insp
            print(f"  Następny przegląd: {next_insp}")

        existing_ids = {r.id for r in self.service_records}
        record_id = generate_unique_id("SRV-", existing_ids)

        record = ServiceRecord(
            record_id,
            uid,
            record_date,
            record_type,
            description,
            cost,
            next_insp,
        )
        self.service_records.append(record)

        self._dirty.add("service")
        self._save_service_records()
        self._dirty.add("machines")
        self._save_machines()
        print("  Wpis zapisany.")

    # -------------------------------------------------------------------------
    # Import i synchronizacja
    # -------------------------------------------------------------------------

    def import_machines(self) -> None:
        print("\n--- IMPORT MASZYN ---")
        path = (
            input("Ścieżka do pliku (Enter = machines_db.json): ").strip()
            or "machines_db.json"
        )
        try:
            result = self.store.import_machines(path)
            # Odczyt z dysku — store.import_machines() już zapisał plik,
            # więc _dirty nie jest potrzebne (dane zsynchronizowane z dyskiem).
            self.machines = self.store.load_machines()
            for detail in result["skipped_details"]:
                print(f"  Pominięto {detail}")
            print(
                f"  Zaimportowano {result['imported']} maszyn"
                f" (pominięto: {result['skipped']})."
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"  BŁĄD: {e}")

    def sync(self) -> None:
        result = run_daily_sync(self.machines, self.reservations)
        total = result["updated"] + result["extended"] + result["reserved"]
        if total:
            self._dirty.add("machines")
            self._save_machines()
            self._dirty.add("reservations")
            self._save_reservations()
            print(
                f"\n  [SYNC] Na budowie: {result['updated']}, "
                f"przedłużone: {result['extended']}, "
                f"zarezerwowane: {result['reserved']}"
            )
        else:
            print("\n  [SYNC] Wszystko aktualne, brak zmian.")

    # -------------------------------------------------------------------------
    # Menu główne
    # -------------------------------------------------------------------------

    def run(self) -> None:
        self.sync()
        print(f"\n{self.SEP}")
        print("   PLANER MASZYN BUDOWLANYCH")
        print(self.SEP)

        menu = {
            "1": ("Lista maszyn", self.show_machines),
            "2": ("Rezerwacje", self.show_reservations),
            "3": ("Nowa rezerwacja", self.create_reservation),
            "4": ("Zwrot maszyny", self.return_machine),
            "5": ("Edycja maszyny", self.edit_machine),
            "6": ("Edycja rezerwacji", self.edit_reservation),
            "7": ("Anulowanie rezerwacji", self.cancel_reservation),
            "8": ("Serwis — dodaj wpis", self.add_service_record),
            "9": ("Serwis — historia i koszty", self.show_service_history),
            "10": ("Import maszyn z pliku", self.import_machines),
            "11": ("Synchronizacja statusów", self.sync),
        }

        while True:
            print("\n[ MENU GŁÓWNE ]")
            for key, (label, _) in menu.items():
                print(f"  {key:>2}. {label}")
            print("   0. Wyjście")

            choice = input("\nWybierz (0-11): ").strip()

            if choice == "0":
                self.save_all()
                print("\n  Do widzenia!")
                break
            elif choice in menu:
                menu[choice][1]()
            else:
                print("  Nieprawidłowy wybór.")
