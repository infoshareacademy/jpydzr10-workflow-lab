"""
Planer Maszyn Budowlanych — Aplikacja konsolowa (Milestone 1)
System do zarządzania rezerwacjami maszyn budowlanych w firmie.

Funkcjonalności:
- Przeglądanie listy maszyn z ich statusami
- Tworzenie i zarządzanie rezerwacjami
- Rejestrowanie napraw i przeglądów technicznych
- Automatyczne wykrywanie konfliktów rezerwacji
- Automatyczne przedłużanie rezerwacji dla niezwróconych maszyn
"""

import json
import os
from datetime import datetime, date, timedelta


# =============================================================================
# MODELE DANYCH
# =============================================================================


class Machine:
    """Reprezentuje maszynę budowlaną w inwentarzu firmy."""

    VALID_STATUSES = ("In Magazijn", "Op de werf", "Gereserveerd", "In Herstelling")

    def __init__(
        self,
        uid,
        name,
        machine_type,
        model="",
        capacity=0,
        inspection_date="",
        location="Magazyn",
        status="In Magazijn",
    ):
        self.uid = uid
        self.name = name
        self.machine_type = machine_type
        self.model = model
        self.capacity = capacity
        self.inspection_date = inspection_date
        self.location = location
        self.status = status  # wywołuje setter z walidacją

    # Property TYLKO dla statusu — bo walidujemy dozwolone wartości
    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if value not in self.VALID_STATUSES:
            raise ValueError(
                f"Nieprawidłowy status: {value}. Dozwolone: {self.VALID_STATUSES}"
            )
        self._status = value

    @classmethod
    def from_dict(cls, data):
        """Tworzy Machine ze słownika (np. wczytanego z JSON)."""
        return cls(
            uid=data.get("uid", ""),
            name=data.get("name", ""),
            machine_type=data.get("type", ""),
            model=data.get("model", ""),
            capacity=data.get("capacity", 0),
            inspection_date=data.get("inspectionDate", ""),
            location=data.get("location", "Magazyn"),
            status=data.get("status", "In Magazijn"),
        )

    def to_dict(self):
        return {
            "uid": self.uid,
            "name": self.name,
            "type": self.machine_type,
            "model": self.model,
            "capacity": self.capacity,
            "inspectionDate": self.inspection_date,
            "location": self.location,
            "status": self._status,
        }

    def __str__(self):
        return f"{self.uid:<14} {self.name:<22} {self._status:<16} {self.location}"


class Reservation:
    """Reprezentuje rezerwację maszyny na określony okres."""

    VALID_STATUSES = ("pending", "confirmed", "rejected", "completed")

    def __init__(
        self,
        reservation_id,
        machine_id,
        start_date,
        end_date,
        person,
        project_number,
        address="",
        status="pending",
    ):
        self.id = reservation_id
        self.machine_id = machine_id
        self.start_date = start_date
        self.end_date = end_date
        self.person = person
        self.project_number = project_number
        self.address = address
        self.status = status  # wywołuje setter z walidacją

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if value not in self.VALID_STATUSES:
            raise ValueError(f"Nieprawidłowy status: {value}")
        self._status = value

    @property
    def title(self):
        """Generuje krótki opis — obliczany dynamicznie, nie przechowywany."""
        return f"{self.project_number} / {self.person}"

    @classmethod
    def from_dict(cls, data):
        return cls(
            reservation_id=data.get("id", ""),
            machine_id=data.get("machineId", ""),
            start_date=data.get("startDate", ""),
            end_date=data.get("endDate", ""),
            person=data.get("person", ""),
            project_number=data.get("projectNumber", ""),
            address=data.get("address", ""),
            status=data.get("status", "pending"),
        )

    def to_dict(self):
        return {
            "id": self.id,
            "machineId": self.machine_id,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "person": self.person,
            "projectNumber": self.project_number,
            "address": self.address,
            "status": self._status,
        }

    def __str__(self):
        return (
            f"[{self._status:>10}] {self.machine_id:<14} "
            f"{self.start_date} → {self.end_date}  "
            f"{self.project_number} ({self.person})"
        )


class ServiceRecord:
    """Rejestruje przegląd techniczny lub naprawę maszyny."""

    def __init__(
        self,
        record_id,
        machine_id,
        record_date,
        record_type,
        description="",
        cost=0.0,
        next_inspection="",
    ):
        self.id = record_id
        self.machine_id = machine_id
        self.record_date = record_date
        self.record_type = record_type
        self.description = description
        self.cost = cost
        self.next_inspection = next_inspection

    @classmethod
    def from_dict(cls, data):
        return cls(
            record_id=data.get("id", ""),
            machine_id=data.get("machineId", ""),
            record_date=data.get("date", ""),
            record_type=data.get("type", "inspection"),
            description=data.get("description", ""),
            cost=data.get("cost", 0.0),
            next_inspection=data.get("nextInspection", ""),
        )

    def to_dict(self):
        return {
            "id": self.id,
            "machineId": self.machine_id,
            "date": self.record_date,
            "type": self.record_type,
            "description": self.description,
            "cost": self.cost,
            "nextInspection": self.next_inspection,
        }

    def __str__(self):
        cost_str = f"{self.cost:.2f} EUR" if self.cost else "---"
        return f"{self.record_date}  {self.record_type:<12}  {cost_str:<14}  {self.description}"


# =============================================================================
# ZAPIS I ODCZYT DANYCH
# =============================================================================


class DataStore:
    """Zapis i odczyt danych z plików JSON."""

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.paths = {
            "machines": os.path.join(data_dir, "machines.json"),
            "reservations": os.path.join(data_dir, "reservations.json"),
            "service": os.path.join(data_dir, "service_records.json"),
        }

    def _load(self, path, cls):
        """Wczytuje listę obiektów z JSON. Pusta lista jeśli plik nie istnieje."""
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return [cls.from_dict(item) for item in json.load(f)]

    def _save(self, path, items):
        """Zapisuje listę obiektów do JSON."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                [item.to_dict() for item in items], f, indent=2, ensure_ascii=False
            )

    def load_machines(self):
        return self._load(self.paths["machines"], Machine)

    def save_machines(self, machines):
        self._save(self.paths["machines"], machines)

    def load_reservations(self):
        return self._load(self.paths["reservations"], Reservation)

    def save_reservations(self, reservations):
        self._save(self.paths["reservations"], reservations)

    def load_service_records(self):
        return self._load(self.paths["service"], ServiceRecord)

    def save_service_records(self, records):
        self._save(self.paths["service"], records)

    def import_machines(self, filepath="machines_db.json"):
        """Importuje maszyny z zewnętrznego pliku. Zwraca liczbę zaimportowanych."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Plik nie istnieje: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)

        existing = {m.uid: m for m in self.load_machines()}
        for item in raw:
            m = Machine.from_dict(item)
            existing[m.uid] = m

        self.save_machines(list(existing.values()))
        return len(raw)


# =============================================================================
# LOGIKA BIZNESOWA
# =============================================================================


def parse_date(date_str):
    """Konwertuje string RRRR-MM-DD na obiekt date."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def has_conflict(reservations, machine_id, start, end, exclude_id=""):
    """Sprawdza czy maszyna jest zajęta w podanym terminie.

    Dwa zakresy się nakładają gdy: start_a <= end_b ORAZ end_a >= start_b
    """
    new_start, new_end = parse_date(start), parse_date(end)

    for res in reservations:
        if res.machine_id != machine_id:
            continue
        if res._status in ("rejected", "completed"):
            continue
        if res.id == exclude_id:
            continue
        if new_start <= parse_date(res.end_date) and new_end >= parse_date(
            res.start_date
        ):
            return True
    return False


def calculate_next_inspection(performed_date, interval_months=3):
    """Oblicza datę następnego przeglądu (uproszczenie: 1 miesiąc = 30 dni)."""
    return (parse_date(performed_date) + timedelta(days=interval_months * 30)).strftime(
        "%Y-%m-%d"
    )


def check_inspection_status(inspection_date_str):
    """Sprawdza ważność przeglądu: 'ok', 'warning' (≤14 dni), 'overdue'."""
    if not inspection_date_str:
        return "overdue"
    try:
        days_left = (parse_date(inspection_date_str) - date.today()).days
    except ValueError:
        return "overdue"

    if days_left < 0:
        return "overdue"
    if days_left <= 14:
        return "warning"
    return "ok"


def run_daily_sync(machines, reservations):
    """Codzienna synchronizacja statusów.

    1. Aktywne rezerwacje → maszyna 'Op de werf'
    2. Przeterminowane rezerwacje (maszyna nie wróciła) → przedłuż end_date
    """
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    updated = extended = 0

    for res in reservations:
        if res._status != "confirmed":
            continue

        machine = next((m for m in machines if m.uid == res.machine_id), None)
        if not machine:
            continue

        start = parse_date(res.start_date)
        end = parse_date(res.end_date)

        if start <= today <= end and machine._status != "Op de werf":
            machine.status = "Op de werf"
            updated += 1
        elif end < today and machine._status != "In Magazijn":
            res.end_date = today_str
            extended += 1

    return {"updated": updated, "extended": extended}


# =============================================================================
# HELPERY DO INPUTU
# =============================================================================


def input_date(prompt):
    """Pobiera datę od użytkownika, powtarza aż format będzie prawidłowy."""
    while True:
        value = input(prompt).strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            print("  Zły format. Użyj RRRR-MM-DD.")


def input_choice(prompt, valid):
    """Pobiera wybór z ograniczonej listy wartości."""
    while True:
        value = input(prompt).strip()
        if value in valid:
            return value
        print(f"  Dozwolone: {', '.join(valid)}")


# =============================================================================
# INTERFEJS KONSOLOWY
# =============================================================================


class App:
    """Główna klasa aplikacji — menu i formularze."""

    SEP = "=" * 65
    LINE = "-" * 65

    def __init__(self):
        self.store = DataStore()
        self.machines = self.store.load_machines()
        self.reservations = self.store.load_reservations()
        self.service_records = self.store.load_service_records()

    def save_all(self):
        self.store.save_machines(self.machines)
        self.store.save_reservations(self.reservations)
        self.store.save_service_records(self.service_records)

    def find_machine(self, uid):
        return next((m for m in self.machines if m.uid == uid), None)

    # --- Ekrany ---

    def show_machines(self):
        print(f"\n{'UID':<14} {'Nazwa':<22} {'Status':<16} Lokalizacja")
        print(self.LINE)
        if not self.machines:
            print("  Brak maszyn. Użyj opcji 7 żeby zaimportować z pliku.")
            return
        for m in self.machines:
            insp = check_inspection_status(m.inspection_date)
            marker = (
                " [!]"
                if insp == "warning"
                else " [PRZETERMINOWANY]"
                if insp == "overdue"
                else ""
            )
            print(f"{m}{marker}")

    def show_reservations(self):
        for label, st in [
            ("Oczekujące", "pending"),
            ("Aktywne", "confirmed"),
            ("Zakończone", "completed"),
        ]:
            group = [r for r in self.reservations if r._status == st]
            if group:
                print(f"\n--- {label} ({len(group)}) ---")
                for r in group:
                    print(f"  {r}")
        if not self.reservations:
            print("\n  Brak rezerwacji w systemie.")

    def create_reservation(self):
        print("\n--- NOWA REZERWACJA ---")
        available = [m for m in self.machines if m._status == "In Magazijn"]
        if not available:
            print("  Brak wolnych maszyn!")
            return

        print("\nDostępne maszyny:")
        for m in available:
            print(f"  {m.uid:<14} {m.name}")

        uid = input("\nUID maszyny: ").strip()
        if not self.find_machine(uid):
            print("  Nie znaleziono maszyny.")
            return

        start = input_date("Data od (RRRR-MM-DD): ")
        end = input_date("Data do (RRRR-MM-DD): ")

        if parse_date(end) < parse_date(start):
            print("  Data końca nie może być wcześniejsza niż początku.")
            return

        if has_conflict(self.reservations, uid, start, end):
            print("  Maszyna jest już zarezerwowana w tym terminie!")
            return

        person = input("Osoba odpowiedzialna: ").strip()
        project = input("Numer projektu: ").strip()
        address = input("Adres budowy: ").strip()

        res_id = f"RES-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self.reservations) + 1}"
        res = Reservation(
            res_id, uid, start, end, person, project, address, "confirmed"
        )
        self.reservations.append(res)
        self.save_all()
        print(f"\n  Rezerwacja utworzona: {res.title}")

    def return_machine(self):
        print("\n--- ZWROT MASZYNY ---")
        on_site = [m for m in self.machines if m._status == "Op de werf"]
        if not on_site:
            print("  Brak maszyn do zwrotu.")
            return

        print("\nMaszyny na budowie:")
        for m in on_site:
            print(f"  {m.uid:<14} {m.name:<22} {m.location}")

        uid = input("\nUID maszyny: ").strip()
        machine = self.find_machine(uid)
        if not machine or machine._status != "Op de werf":
            print("  Nie znaleziono maszyny na budowie.")
            return

        today_str = date.today().strftime("%Y-%m-%d")
        for res in self.reservations:
            if (
                res.machine_id == uid
                and res._status == "confirmed"
                and res.start_date <= today_str
            ):
                res.status = "completed"

        machine.status = "In Magazijn"
        machine.location = "Magazyn"
        self.save_all()
        print(f"  Maszyna {uid} zwrócona do magazynu.")

    def add_service_record(self):
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
            except ValueError:
                cost = 0.0

        next_insp = ""
        if record_type == "inspection":
            interval = input("Interwał miesięcy (domyślnie 3): ").strip()
            interval = int(interval) if interval.isdigit() else 3
            next_insp = calculate_next_inspection(record_date, interval)
            machine.inspection_date = next_insp
            print(f"  Następny przegląd: {next_insp}")

        record = ServiceRecord(
            f"SRV-{len(self.service_records) + 1}",
            uid,
            record_date,
            record_type,
            description,
            cost,
            next_insp,
        )
        self.service_records.append(record)
        self.save_all()
        print("  Wpis zapisany.")

    def show_service_history(self):
        print("\n--- HISTORIA SERWISOWA ---")
        uid = input("UID maszyny (Enter = wszystkie): ").strip()

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

    def import_machines(self):
        print("\n--- IMPORT MASZYN ---")
        path = (
            input("Ścieżka do pliku (Enter = machines_db.json): ").strip()
            or "machines_db.json"
        )
        try:
            count = self.store.import_machines(path)
            self.machines = self.store.load_machines()
            print(f"  Zaimportowano {count} maszyn.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"  BŁĄD: {e}")

    def sync(self):
        result = run_daily_sync(self.machines, self.reservations)
        self.save_all()
        total = result["updated"] + result["extended"]
        if total:
            print(
                f"\n  [SYNC] Statusy: {result['updated']}, przedłużone: {result['extended']}"
            )
        else:
            print("\n  [SYNC] Wszystko aktualne, brak zmian.")

    # --- Menu ---

    def run(self):
        self.sync()
        print(f"\n{self.SEP}")
        print("   PLANER MASZYN BUDOWLANYCH")
        print(self.SEP)

        menu = {
            "1": ("Lista maszyn", self.show_machines),
            "2": ("Rezerwacje", self.show_reservations),
            "3": ("Nowa rezerwacja", self.create_reservation),
            "4": ("Zwrot maszyny", self.return_machine),
            "5": ("Serwis — dodaj wpis", self.add_service_record),
            "6": ("Serwis — historia i koszty", self.show_service_history),
            "7": ("Import maszyn z pliku", self.import_machines),
            "8": ("Synchronizacja statusów", self.sync),
        }

        while True:
            print("\n[ MENU GŁÓWNE ]")
            for key, (label, _) in menu.items():
                print(f"  {key}. {label}")
            print("  0. Wyjście")

            choice = input("\nWybierz (0-8): ").strip()

            if choice == "0":
                self.save_all()
                print("\n  Do widzenia!")
                break
            elif choice in menu:
                menu[choice][1]()
            else:
                print("  Nieprawidłowy wybór.")


# =============================================================================
# START
# =============================================================================

if __name__ == "__main__":
    App().run()
