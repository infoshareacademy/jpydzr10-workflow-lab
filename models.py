"""
Modele danych: Machine, Reservation, ServiceRecord.

Każda klasa:
- Waliduje dane wejściowe (status, UID)
- Serializuje się do/z formatu słownikowego (JSON-ready)
- Używa hermetyzacji dla pól z walidacją (@property + setter)
- Posiada dekoratory @property, @classmethod, @staticmethod

Mapowanie nazw Python → JSON (camelCase w JSON dla kompatybilności z frontendem):
  machine_type  → type
  inspection_date → inspectionDate
  machine_id    → machineId
  start_date    → startDate
  end_date      → endDate
  project_number → projectNumber
  record_date   → date
  record_type   → type
  next_inspection → nextInspection
"""

from datetime import date, timedelta

from utils import parse_date


# =============================================================================
# MACHINE
# =============================================================================


class Machine:
    """Reprezentuje maszynę budowlaną w inwentarzu firmy.

    Statusy:
        In Magazijn   — w magazynie, dostępna do rezerwacji
        Gereserveerd  — zarezerwowana na przyszły termin
        Op de werf    — aktualnie na budowie (rezerwacja w trakcie)
        In Herstelling — w serwisie (wyłączona z rezerwacji)
    """

    VALID_STATUSES = ("In Magazijn", "Op de werf", "Gereserveerd", "In Herstelling")

    def __init__(
        self,
        uid: str,
        name: str,
        machine_type: str,
        model: str = "",
        capacity: int = 0,
        inspection_date: str = "",
        location: str = "Magazyn",
        status: str = "In Magazijn",
    ):
        if not uid or not uid.strip():
            raise ValueError("UID maszyny nie może być pusty")
        self.uid = uid
        self.name = name
        self.machine_type = machine_type
        self.model = model
        self.capacity = capacity
        self.inspection_date = inspection_date
        self.location = location
        self.status = status  # wywołuje setter z walidacją

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        if value not in self.VALID_STATUSES:
            raise ValueError(
                f"Nieprawidłowy status: {value}. Dozwolone: {self.VALID_STATUSES}"
            )
        self._status = value

    @staticmethod
    def check_inspection_status(inspection_date_str: str) -> str:
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

    @classmethod
    def from_dict(cls, data: dict) -> "Machine":
        """Tworzy Machine ze słownika (np. wczytanego z JSON).

        Raises:
            KeyError: Gdy brakuje wymaganego pola 'uid'
            ValueError: Gdy 'uid' jest puste
        """
        return cls(
            uid=data["uid"],
            name=data.get("name", ""),
            machine_type=data.get("type", ""),
            model=data.get("model", ""),
            capacity=data.get("capacity", 0),
            inspection_date=data.get("inspectionDate", ""),
            location=data.get("location", "Magazyn"),
            status=data.get("status", "In Magazijn"),
        )

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "type": self.machine_type,
            "model": self.model,
            "capacity": self.capacity,
            "inspectionDate": self.inspection_date,
            "location": self.location,
            "status": self.status,
        }

    def __str__(self) -> str:
        return f"{self.uid:<14} {self.name:<22} {self.status:<16} {self.location}"

    def __repr__(self) -> str:
        return f"Machine(uid={self.uid!r}, name={self.name!r}, status={self.status!r})"


# =============================================================================
# RESERVATION
# =============================================================================


class Reservation:
    """Reprezentuje rezerwację maszyny na określony okres."""

    VALID_STATUSES = ("pending", "confirmed", "rejected", "completed")

    def __init__(
        self,
        reservation_id: str,
        machine_id: str,
        start_date: str,
        end_date: str,
        person: str,
        project_number: str,
        address: str = "",
        status: str = "pending",
    ):
        if not reservation_id or not reservation_id.strip():
            raise ValueError("ID rezerwacji nie może być puste")
        self.id = reservation_id
        self.machine_id = machine_id
        self.start_date = start_date
        self.end_date = end_date
        self.person = person
        self.project_number = project_number
        self.address = address
        self.status = status  # wywołuje setter z walidacją

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        if value not in self.VALID_STATUSES:
            raise ValueError(f"Nieprawidłowy status: {value}")
        self._status = value

    @property
    def title(self) -> str:
        """Generuje krótki opis — obliczany dynamicznie, nie przechowywany."""
        return f"{self.project_number} / {self.person}"

    @staticmethod
    def validate_date_range(start_str: str, end_str: str) -> bool:
        """Sprawdza czy zakres dat jest prawidłowy (koniec >= początek)."""
        return parse_date(end_str) >= parse_date(start_str)

    @classmethod
    def from_dict(cls, data: dict) -> "Reservation":
        return cls(
            reservation_id=data["id"],
            machine_id=data.get("machineId", ""),
            start_date=data.get("startDate", ""),
            end_date=data.get("endDate", ""),
            person=data.get("person", ""),
            project_number=data.get("projectNumber", ""),
            address=data.get("address", ""),
            status=data.get("status", "pending"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "machineId": self.machine_id,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "person": self.person,
            "projectNumber": self.project_number,
            "address": self.address,
            "status": self.status,
        }

    def __str__(self) -> str:
        return (
            f"[{self.status:>10}] {self.machine_id:<14} "
            f"{self.start_date} → {self.end_date}  "
            f"{self.project_number} ({self.person})"
        )

    def __repr__(self) -> str:
        return (
            f"Reservation(id={self.id!r}, machine_id={self.machine_id!r}, "
            f"status={self.status!r})"
        )


# =============================================================================
# SERVICE RECORD
# =============================================================================


class ServiceRecord:
    """Rejestruje przegląd techniczny lub naprawę maszyny."""

    VALID_TYPES = ("inspection", "repair")

    def __init__(
        self,
        record_id: str,
        machine_id: str,
        record_date: str,
        record_type: str,
        description: str = "",
        cost: float = 0.0,
        next_inspection: str = "",
    ):
        if not record_id or not record_id.strip():
            raise ValueError("ID wpisu serwisowego nie może być puste")
        self.id = record_id
        self.machine_id = machine_id
        self.record_date = record_date
        self.record_type = record_type  # wywołuje setter z walidacją
        self.description = description
        self.cost = cost
        self.next_inspection = next_inspection

    @property
    def record_type(self) -> str:
        return self._record_type

    @record_type.setter
    def record_type(self, value: str) -> None:
        if value not in self.VALID_TYPES:
            raise ValueError(
                f"Nieprawidłowy typ wpisu: {value}. Dozwolone: {self.VALID_TYPES}"
            )
        self._record_type = value

    @staticmethod
    def calculate_next_inspection(
        performed_date: str, interval_months: int = 3
    ) -> str:
        """Oblicza datę następnego przeglądu (uproszczenie: 1 miesiąc = 30 dni).

        TODO (Milestone 2): Zamienić na dateutil.relativedelta dla precyzyjnych
        obliczeń miesięcznych (luty, lata przestępne).
        """
        return (
            parse_date(performed_date) + timedelta(days=interval_months * 30)
        ).strftime("%Y-%m-%d")

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceRecord":
        return cls(
            record_id=data["id"],
            machine_id=data.get("machineId", ""),
            record_date=data.get("date", ""),
            record_type=data.get("type", "inspection"),
            description=data.get("description", ""),
            cost=data.get("cost", 0.0),
            next_inspection=data.get("nextInspection", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "machineId": self.machine_id,
            "date": self.record_date,
            "type": self.record_type,
            "description": self.description,
            "cost": self.cost,
            "nextInspection": self.next_inspection,
        }

    def __str__(self) -> str:
        cost_str = f"{self.cost:.2f} EUR" if self.cost else "---"
        return f"{self.record_date}  {self.record_type:<12}  {cost_str:<14}  {self.description}"

    def __repr__(self) -> str:
        return (
            f"ServiceRecord(id={self.id!r}, machine_id={self.machine_id!r}, "
            f"type={self.record_type!r})"
        )
