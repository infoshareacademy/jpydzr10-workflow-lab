"""Testy modeli danych: Machine, Reservation, ServiceRecord."""

import pytest

from models import Machine, Reservation, ServiceRecord

# =============================================================================
# Machine
# =============================================================================


class TestMachine:
    def test_create_valid_machine(self):
        m = Machine("UID001", "Koparka", "koparka", status="W magazynie")
        assert m.uid == "UID001"
        assert m.name == "Koparka"
        assert m.status == "W magazynie"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Nieprawidłowy status"):
            Machine("UID001", "Koparka", "koparka", status="NIEZNANY")

    def test_status_setter_validates(self):
        m = Machine("UID001", "Koparka", "koparka")
        with pytest.raises(ValueError):
            m.status = "bzdura"

    def test_status_setter_accepts_valid(self):
        m = Machine("UID001", "Koparka", "koparka")
        m.status = "Na budowie"
        assert m.status == "Na budowie"

    def test_all_valid_statuses(self):
        """Wszystkie zdefiniowane statusy powinny być akceptowane."""
        for status in Machine.VALID_STATUSES:
            m = Machine("UID001", "Koparka", "koparka", status=status)
            assert m.status == status

    def test_to_dict_and_back(self):
        m = Machine(
            "UID001", "Koparka", "koparka", model="320 GC",
            capacity=22000, manufacturer="Caterpillar",
            serial_number="CAT0EL12345", build_year=2020,
        )
        d = m.to_dict()
        m2 = Machine.from_dict(d)
        assert m2.uid == m.uid
        assert m2.name == m.name
        assert m2.model == m.model
        assert m2.manufacturer == m.manufacturer
        assert m2.serial_number == m.serial_number
        assert m2.build_year == m.build_year

    def test_to_dict_includes_new_fields(self):
        """to_dict powinien zawierać nowe pola."""
        m = Machine(
            "UID001", "Koparka", "koparka",
            manufacturer="CAT", serial_number="SN123",
            build_year=2019, notes="Uwaga: wymaga kalibracji",
        )
        d = m.to_dict()
        assert d["manufacturer"] == "CAT"
        assert d["serialNumber"] == "SN123"
        assert d["buildYear"] == 2019
        assert d["notes"] == "Uwaga: wymaga kalibracji"

    def test_check_inspection_status_empty(self):
        assert Machine.check_inspection_status("") == "overdue"

    def test_check_inspection_status_overdue(self):
        assert Machine.check_inspection_status("2020-01-01") == "overdue"

    def test_check_inspection_status_warning(self):
        """Przegląd za 7 dni — powinien zwrócić 'warning'."""
        from datetime import date, timedelta

        future_7 = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(future_7) == "warning"

    def test_check_inspection_status_ok(self):
        """Przegląd za 30 dni — powinien zwrócić 'ok'."""
        from datetime import date, timedelta

        future_30 = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
        assert Machine.check_inspection_status(future_30) == "ok"

    def test_repr(self):
        m = Machine("UID001", "Koparka", "koparka")
        assert "UID001" in repr(m)

    def test_empty_uid_raises(self):
        with pytest.raises(ValueError, match="UID maszyny nie może być pusty"):
            Machine("", "Koparka", "koparka")

    def test_whitespace_uid_raises(self):
        with pytest.raises(ValueError, match="UID maszyny nie może być pusty"):
            Machine("   ", "Koparka", "koparka")

    def test_from_dict_missing_uid_raises(self):
        with pytest.raises(KeyError):
            Machine.from_dict({"name": "Koparka", "type": "koparka"})


# =============================================================================
# Reservation
# =============================================================================


class TestReservation:
    def test_create_valid_reservation(self):
        r = Reservation(
            "RES-001", "UID001", "2025-04-01", "2025-04-10",
            "Jan Kowalski", "BUD-2025-001",
        )
        assert r.status == "oczekująca"
        assert r.title == "BUD-2025-001 / Jan Kowalski"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            Reservation(
                "RES-001", "UID001", "2025-04-01", "2025-04-10",
                "Jan", "P100", status="aktywna",
            )

    def test_all_valid_statuses(self):
        """Wszystkie zdefiniowane statusy powinny być akceptowane."""
        for status in Reservation.VALID_STATUSES:
            r = Reservation(
                "RES-001", "UID001", "2025-04-01", "2025-04-10",
                "Jan", "P100", status=status,
            )
            assert r.status == status

    def test_validate_date_range_valid(self):
        assert Reservation.validate_date_range(
            "2025-04-01", "2025-04-10"
        ) is True

    def test_validate_date_range_same_day(self):
        assert Reservation.validate_date_range(
            "2025-04-01", "2025-04-01"
        ) is True

    def test_validate_date_range_invalid(self):
        assert Reservation.validate_date_range(
            "2025-04-10", "2025-04-01"
        ) is False

    def test_to_dict_and_back(self):
        r = Reservation(
            "RES-001", "UID001", "2025-04-01", "2025-04-10",
            "Jan", "P100", "Warszawa ul. Budowlana 5",
        )
        d = r.to_dict()
        r2 = Reservation.from_dict(d)
        assert r2.id == r.id
        assert r2.person == "Jan"
        assert r2.address == "Warszawa ul. Budowlana 5"

    def test_repr(self):
        r = Reservation(
            "RES-001", "UID001", "2025-04-01", "2025-04-10",
            "Jan", "P100",
        )
        assert "RES-001" in repr(r)

    def test_empty_id_raises(self):
        with pytest.raises(
            ValueError, match="ID rezerwacji nie może być puste"
        ):
            Reservation(
                "", "UID001", "2025-04-01", "2025-04-10", "Jan", "P100"
            )

    def test_whitespace_id_raises(self):
        with pytest.raises(
            ValueError, match="ID rezerwacji nie może być puste"
        ):
            Reservation(
                "   ", "UID001", "2025-04-01", "2025-04-10",
                "Jan", "P100",
            )


# =============================================================================
# ServiceRecord
# =============================================================================


class TestServiceRecord:
    def test_create_valid_inspection(self):
        s = ServiceRecord("SRV-001", "UID001", "2025-04-01", "przegląd")
        assert s.record_type == "przegląd"

    def test_create_valid_repair(self):
        s = ServiceRecord(
            "SRV-001", "UID001", "2025-04-01", "naprawa",
            "Wymiana filtra oleju", 1250.00,
        )
        assert s.record_type == "naprawa"
        assert s.cost == 1250.00

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Nieprawidłowy typ"):
            ServiceRecord("SRV-001", "UID001", "2025-04-01", "czyszczenie")

    def test_calculate_next_inspection(self):
        result = ServiceRecord.calculate_next_inspection("2025-01-01", 3)
        assert result == "2025-04-01"

    def test_to_dict_and_back(self):
        s = ServiceRecord(
            "SRV-001", "UID001", "2025-04-01", "naprawa",
            "Wymiana filtra", 250.0,
        )
        d = s.to_dict()
        s2 = ServiceRecord.from_dict(d)
        assert s2.cost == 250.0
        assert s2.description == "Wymiana filtra"

    def test_empty_id_raises(self):
        with pytest.raises(
            ValueError, match="ID wpisu serwisowego nie może być puste"
        ):
            ServiceRecord("", "UID001", "2025-04-01", "przegląd")

    def test_whitespace_id_raises(self):
        with pytest.raises(
            ValueError, match="ID wpisu serwisowego nie może być puste"
        ):
            ServiceRecord("   ", "UID001", "2025-04-01", "przegląd")
