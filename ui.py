"""
Interfejs konsolowy: menu główne, formularze, ekrany.

Zawiera też helpery do pobierania danych od użytkownika
(input_date, input_choice) — bo to warstwa I/O, nie logika biznesowa.
"""

import contextlib
from datetime import date, datetime

from datastore import DataStore
from exceptions import DataCorruptionError
from logic import has_conflict, run_daily_sync
from models import Machine, Reservation, ServiceRecord
from utils import generate_unique_id, parse_date

# =============================================================================
# HELPERY DO INPUTU (warstwa UI)
# =============================================================================


def input_date(prompt: str) -> str:
    """Pobiera datę od użytkownika, powtarza aż format będzie prawidłowy."""
    while True:
        value = input(prompt).strip()
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d")
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
    LINE = "-" * 99

    def __init__(self):
        self.store = DataStore()
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
        self._dirty: set[str] = set()

    def _safe_load(self, name: str, loader) -> list:
        """Wczytuje dane z graceful error handling."""
        try:
            return loader()
        except OSError as e:
            print(f"\n  BŁĄD I/O: {e}")
            print(f"  Kontynuuję z pustą listą dla: {name}.\n")
            self._corrupted.add(name)
            return []
        except DataCorruptionError as e:
            print(f"\n  BŁĄD: {e}")
            print(f"  Kontynuuję z pustą listą dla: {name}.")
            print("  Uszkodzone pliki NIE zostały nadpisane.\n")
            self._corrupted.add(name)
            return []

    def save_all(self) -> None:
        """Zapisuje tylko zmodyfikowane kolekcje przy wyjściu."""
        if "machines" in self._dirty:
            self._save_machines()
        if "reservations" in self._dirty:
            self._save_reservations()
        if "service" in self._dirty:
            self._save_service_records()
        self._dirty.clear()

    def _save_collection(self, name: str, saver, data: list) -> None:
        """Generyczny zapis kolekcji z ochroną uszkodzonych plików."""
        if name in self._corrupted:
            print(f"  UWAGA: Zapis {name} pominięty — plik uszkodzony.")
            return
        saver(data)
        self._dirty.discard(name)

    def _save_machines(self) -> None:
        self._save_collection("machines", self.store.save_machines, self.machines)

    def _save_reservations(self) -> None:
        self._save_collection("reservations", self.store.save_reservations, self.reservations)

    def _save_service_records(self) -> None:
        self._save_collection("service", self.store.save_service_records, self.service_records)

    def find_machine(self, uid: str) -> Machine | None:
        return next((m for m in self.machines if m.uid == uid), None)

    # -------------------------------------------------------------------------
    # Ekrany — wyświetlanie danych
    # -------------------------------------------------------------------------

    def show_machines(self) -> None:
        print(
            f"\n{'UID':<10} {'Nazwa':<40} {'Status':<14} Lokalizacja"
        )
        print(self.LINE)
        if not self.machines:
            print("  Brak maszyn. Użyj opcji 10 żeby zaimportować.")
            return
        for m in self.machines:
            insp = Machine.check_inspection_status(m.inspection_date)
            markers = {
                "warning": " [!]",
                "overdue": " [PRZEGLĄD!]",
            }
            marker = markers.get(insp, "")
            print(f"{m}{marker}")

    def show_reservations(self) -> None:
        for label, st in [
            ("Oczekujące", "oczekująca"),
            ("Aktywne (potwierdzone)", "potwierdzona"),
            ("Zakończone", "zakończona"),
            ("Anulowane", "anulowana"),
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
        """Wyświetla wpisy serwisowe (opcjonalnie filtrowane po UID)."""
        records = [
            r for r in self.service_records
            if not uid or r.machine_id == uid
        ]
        if not records:
            print("  Brak wpisów.")
            return

        print(
            f"\n  {'Data':<12}{'Typ':<12}  {'Koszt':<14}  Opis"
        )
        print(self.LINE)
        total = 0.0
        for r in records:
            print(f"  {r}")
            total += r.cost
        print(self.LINE)
        print(f"  ŁĄCZNY KOSZT: {total:.2f} PLN")

    # -------------------------------------------------------------------------
    # Formularze — tworzenie i edycja
    # -------------------------------------------------------------------------

    def create_reservation(self) -> None:
        """Tworzy nową rezerwację."""
        print("\n--- NOWA REZERWACJA ---")
        available = [
            m for m in self.machines
            if m.status in ("W magazynie", "Zarezerwowana")
        ]
        if not available:
            print("  Brak wolnych maszyn!")
            return

        available_uids = {m.uid for m in available}

        print("\nDostępne maszyny:")
        for m in available:
            print(f"  {m.uid:<10} {m.name:<40} {m.status}")

        uid = input("\nUID maszyny: ").strip()
        if uid not in available_uids:
            print("  Maszyna nie jest dostępna.")
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

        res = Reservation(
            res_id, uid, start, end, person, project,
            address, "potwierdzona",
        )
        self.reservations.append(res)

        machine = self.find_machine(uid)
        if not machine:
            print("  Błąd wewnętrzny: nie znaleziono maszyny.")
            return

        today = date.today()
        start_date = parse_date(start)

        if start_date <= today:
            machine.status = "Na budowie"
            machine.location = address or machine.location
        else:
            machine.status = "Zarezerwowana"

        self._dirty.add("reservations")
        self._save_reservations()
        self._dirty.add("machines")
        self._save_machines()
        print(f"\n  Rezerwacja utworzona: {res.title}")

    def return_machine(self) -> None:
        """Realizuje zwrot maszyny do magazynu."""
        print("\n--- ZWROT MASZYNY ---")
        on_site = [m for m in self.machines if m.status == "Na budowie"]
        if not on_site:
            print("  Brak maszyn do zwrotu.")
            return

        print("\nMaszyny na budowie:")
        for m in on_site:
            print(f"  {m.uid:<10} {m.name:<40} {m.location}")

        uid = input("\nUID maszyny: ").strip()
        machine = self.find_machine(uid)
        if not machine or machine.status != "Na budowie":
            print("  Nie znaleziono maszyny na budowie.")
            return

        today = date.today()
        for res in self.reservations:
            if res.machine_id != uid:
                continue
            if res.status != "potwierdzona":
                continue
            if not res.start_date or not res.end_date:
                continue

            res_start = parse_date(res.start_date)
            res_end = parse_date(res.end_date)

            if res_start <= today <= res_end or res_end < today:
                res.status = "zakończona"

        machine.status = "W magazynie"
        machine.location = "Magazyn"

        has_future = any(
            r for r in self.reservations
            if r.machine_id == uid
            and r.status == "potwierdzona"
            and r.start_date
            and parse_date(r.start_date) > today
        )
        if has_future:
            machine.status = "Zarezerwowana"

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

        new_loc = input(f"  Lokalizacja [{machine.location}]: ").strip()
        if new_loc:
            machine.location = new_loc

        print(
            f"\n  Dozwolone statusy: "
            f"{', '.join(Machine.VALID_STATUSES)}"
        )
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

        active = [
            r for r in self.reservations
            if r.status in ("oczekująca", "potwierdzona")
        ]
        if not active:
            print("  Brak aktywnych rezerwacji do edycji.")
            return

        print("\nAktywne rezerwacje:")
        for i, r in enumerate(active, 1):
            print(f"  {i}. {r}")

        try:
            choice = int(input("\nNumer rezerwacji: ").strip())
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

        new_project = input(
            f"  Nr projektu [{res.project_number}]: "
        ).strip()
        if new_project:
            res.project_number = new_project

        new_address = input(f"  Adres [{res.address}]: ").strip()
        if new_address:
            res.address = new_address

        new_end = input(
            f"  Data końca [{res.end_date}] (RRRR-MM-DD): "
        ).strip()
        if new_end:
            try:
                parse_date(new_end)
                if not Reservation.validate_date_range(
                    res.start_date, new_end
                ):
                    print("  Data końca < początku — pominięto.")
                elif has_conflict(
                    self.reservations,
                    res.machine_id,
                    res.start_date,
                    new_end,
                    exclude_id=res.id,
                ):
                    print("  Nowy termin koliduje — pominięto.")
                else:
                    res.end_date = new_end
            except ValueError:
                print("  Zły format daty — pominięto.")

        self._dirty.add("reservations")
        self._save_reservations()
        print(f"  Rezerwacja {res.id} zaktualizowana.")

    def cancel_reservation(self) -> None:
        """Anulowanie rezerwacji."""
        print("\n--- ANULOWANIE REZERWACJI ---")

        active = [
            r for r in self.reservations
            if r.status in ("oczekująca", "potwierdzona")
        ]
        if not active:
            print("  Brak aktywnych rezerwacji do anulowania.")
            return

        print("\nAktywne rezerwacje:")
        for i, r in enumerate(active, 1):
            print(f"  {i}. {r}")

        try:
            choice = int(
                input("\nNumer rezerwacji do anulowania: ").strip()
            )
            if choice < 1:
                raise IndexError
            res = active[choice - 1]
        except (ValueError, IndexError):
            print("  Nieprawidłowy wybór.")
            return

        confirm = input(
            f"  Na pewno anulować {res.id}? (t/n): "
        ).strip().lower()
        if confirm != "t":
            print("  Anulowanie przerwane.")
            return

        res.status = "anulowana"

        machine = self.find_machine(res.machine_id)
        if machine and machine.status in ("Na budowie", "Zarezerwowana"):
            other_active = [
                r for r in self.reservations
                if r.machine_id == res.machine_id
                and r.status == "potwierdzona"
                and r.id != res.id
            ]
            if not other_active:
                if machine.status == "Na budowie":
                    print(
                        "  UWAGA: Maszyna była 'Na budowie' "
                        "— upewnij się, że fizycznie wróciła."
                    )
                machine.status = "W magazynie"
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
            "Typ (przegląd / naprawa): ", ("przegląd", "naprawa")
        )
        record_date = input_date("Data (RRRR-MM-DD): ")
        description = input("Opis: ").strip()

        cost = 0.0
        if record_type == "naprawa":
            try:
                raw = input("Koszt (PLN): ").strip().replace(",", ".")
                cost = float(raw) if raw else 0.0
                if cost < 0:
                    print("  Koszt nie może być ujemny — 0.00 PLN.")
                    cost = 0.0
            except ValueError:
                print("  Nieprawidłowa kwota — ustawiono 0.00 PLN.")
                cost = 0.0

        next_insp = ""
        if record_type == "przegląd":
            interval = input(
                "Interwał miesięcy (domyślnie 3): "
            ).strip()
            interval = int(interval) if interval.isdigit() else 3
            next_insp = ServiceRecord.calculate_next_inspection(
                record_date, interval
            )
            machine.inspection_date = next_insp
            print(f"  Następny przegląd: {next_insp}")

        existing_ids = {r.id for r in self.service_records}
        record_id = generate_unique_id("SRV-", existing_ids)

        record = ServiceRecord(
            record_id, uid, record_date, record_type,
            description, cost, next_insp,
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
            self.machines = self.store.load_machines()
            self._corrupted.discard("machines")
            for detail in result["skipped_details"]:
                print(f"  Pominięto {detail}")
            print(
                f"  Zaimportowano {result['imported']} maszyn "
                f"(pominięto: {result['skipped']})."
            )
        except (FileNotFoundError, ValueError, DataCorruptionError) as e:
            print(f"  BŁĄD: {e}")

    def sync(self) -> None:
        result = run_daily_sync(self.machines, self.reservations)
        total = sum(result.values())
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

            try:
                choice = input("\nWybierz (0-11): ").strip()
            except EOFError:
                with contextlib.suppress(OSError):
                    self.save_all()
                print("\n  Do widzenia!")
                break

            if choice == "0":
                try:
                    self.save_all()
                except OSError as e:
                    print(f"  Błąd zapisu: {e}")
                print("\n  Do widzenia!")
                break
            elif choice in menu:
                try:
                    menu[choice][1]()
                except (KeyboardInterrupt, EOFError):
                    print("\n  Przerwano — powrót do menu.")
                except OSError as e:
                    print(f"\n  Błąd zapisu/odczytu: {e}")
            else:
                print("  Nieprawidłowy wybór.")
