"""Testy modeli danych: Machine, Reservation, ServiceRecord."""

import pytest
from models import Machine, Reservation, ServiceRecord


# =============================================================================
# Machine
# =============================================================================


class TestMachine:
    def test_create_valid_machine(self):
        m = Machine("UID001", "Dźwig", "crane", status="In Magazijn")
        assert m.uid == "UID001"
        assert m.name == "Dźwig"
        assert m.status == "In Magazijn"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Nieprawidłowy status"):
            Machine("UID001", "Dźwig", "crane", status="NIEZNANY")

    def test_status_setter_validates(self):
        m = Machine("UID001", "Dźwig", "crane")
        with pytest.raises(ValueError):
            m.status = "bzdura"

    def test_status_setter_accepts_valid(self):
        m = Machine("UID001", "Dźwig", "crane")
        m.status = "Op de werf"
        assert m.status == "Op de werf"

    def test_to_dict_and_back(self):
        m = Machine("UID001", "Dźwig", "crane", model="XL", capacity=5)
        d = m.to_dict()
        m2 = Machine.from_dict(d)
        assert m2.uid == m.uid
        assert m2.name == m.name
        assert m2.model == m.model

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
        m = Machine("UID001", "Dźwig", "crane")
        assert "UID001" in repr(m)

    # --- Nowe testy: walidacja UID ---

    def test_empty_uid_raises(self):
        """Maszyna z pustym UID nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="UID maszyny nie może być pusty"):
            Machine("", "Dźwig", "crane")

    def test_whitespace_uid_raises(self):
        """Maszyna z UID zawierającym same spacje nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="UID maszyny nie może być pusty"):
            Machine("   ", "Dźwig", "crane")

    def test_from_dict_missing_uid_raises(self):
        """from_dict z brakującym kluczem 'uid' powinien rzucić KeyError."""
        with pytest.raises(KeyError):
            Machine.from_dict({"name": "Dźwig", "type": "crane"})


# =============================================================================
# Reservation
# =============================================================================


class TestReservation:
    def test_create_valid_reservation(self):
        r = Reservation("RES-001", "UID001", "2025-04-01", "2025-04-10", "Jan", "P100")
        assert r.status == "pending"
        assert r.title == "P100 / Jan"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            Reservation("RES-001", "UID001", "2025-04-01", "2025-04-10",
                        "Jan", "P100", status="aktywna")

    def test_validate_date_range_valid(self):
        assert Reservation.validate_date_range("2025-04-01", "2025-04-10") is True

    def test_validate_date_range_same_day(self):
        assert Reservation.validate_date_range("2025-04-01", "2025-04-01") is True

    def test_validate_date_range_invalid(self):
        assert Reservation.validate_date_range("2025-04-10", "2025-04-01") is False

    def test_to_dict_and_back(self):
        r = Reservation("RES-001", "UID001", "2025-04-01", "2025-04-10",
                        "Jan", "P100", "Gent")
        d = r.to_dict()
        r2 = Reservation.from_dict(d)
        assert r2.id == r.id
        assert r2.person == "Jan"
        assert r2.address == "Gent"

    def test_repr(self):
        r = Reservation("RES-001", "UID001", "2025-04-01", "2025-04-10", "Jan", "P100")
        assert "RES-001" in repr(r)

    # --- Walidacja ID ---

    def test_empty_id_raises(self):
        """Rezerwacja z pustym ID nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="ID rezerwacji nie może być puste"):
            Reservation("", "UID001", "2025-04-01", "2025-04-10", "Jan", "P100")

    def test_whitespace_id_raises(self):
        """Rezerwacja z ID zawierającym same spacje nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="ID rezerwacji nie może być puste"):
            Reservation("   ", "UID001", "2025-04-01", "2025-04-10", "Jan", "P100")


# =============================================================================
# ServiceRecord
# =============================================================================


class TestServiceRecord:
    def test_create_valid_inspection(self):
        s = ServiceRecord("SRV-001", "UID001", "2025-04-01", "inspection")
        assert s.record_type == "inspection"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Nieprawidłowy typ"):
            ServiceRecord("SRV-001", "UID001", "2025-04-01", "cleaning")

    def test_calculate_next_inspection(self):
        # 3 miesiące * 30 dni = 90 dni od 2025-01-01 → 2025-04-01
        result = ServiceRecord.calculate_next_inspection("2025-01-01", 3)
        assert result == "2025-04-01"

    def test_to_dict_and_back(self):
        s = ServiceRecord("SRV-001", "UID001", "2025-04-01", "repair",
                          "Wymiana filtra", 250.0)
        d = s.to_dict()
        s2 = ServiceRecord.from_dict(d)
        assert s2.cost == 250.0
        assert s2.description == "Wymiana filtra"

    # --- Walidacja ID ---

    def test_empty_id_raises(self):
        """ServiceRecord z pustym ID nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="ID wpisu serwisowego nie może być puste"):
            ServiceRecord("", "UID001", "2025-04-01", "inspection")

    def test_whitespace_id_raises(self):
        """ServiceRecord z ID zawierającym same spacje nie powinna przejść walidacji."""
        with pytest.raises(ValueError, match="ID wpisu serwisowego nie może być puste"):
            ServiceRecord("   ", "UID001", "2025-04-01", "inspection")
