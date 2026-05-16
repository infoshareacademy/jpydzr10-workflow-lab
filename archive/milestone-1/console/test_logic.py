"""Testy logiki biznesowej: konflikty, synchronizacja statusów."""

from datetime import date, timedelta

from logic import has_conflict, run_daily_sync
from models import Machine, Reservation

# =============================================================================
# Helpers
# =============================================================================


def _date_str(offset_days=0):
    """Zwraca datę jako string RRRR-MM-DD z przesunięciem od dziś."""
    return (date.today() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _machine(uid="M001", status="W magazynie"):
    return Machine(uid, "Testowa", "koparka", status=status)


def _reservation(
    machine_id="M001",
    start_offset=0,
    end_offset=5,
    status="potwierdzona",
    res_id="RES-001",
):
    return Reservation(
        res_id,
        machine_id,
        _date_str(start_offset),
        _date_str(end_offset),
        "Jan Kowalski",
        "BUD-100",
        status=status,
    )


# =============================================================================
# has_conflict
# =============================================================================


class TestHasConflict:
    def test_no_conflict_different_machine(self):
        reservations = [_reservation(machine_id="M002")]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5)
        ) is False

    def test_conflict_overlapping(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(
            reservations, "M001", _date_str(3), _date_str(8)
        ) is True

    def test_no_conflict_after(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(
            reservations, "M001", _date_str(6), _date_str(10)
        ) is False

    def test_no_conflict_before(self):
        reservations = [_reservation(start_offset=5, end_offset=10)]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(4)
        ) is False

    def test_conflict_exact_overlap(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5)
        ) is True

    def test_no_conflict_rejected(self):
        reservations = [_reservation(status="anulowana")]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5)
        ) is False

    def test_no_conflict_completed(self):
        reservations = [_reservation(status="zakończona")]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5)
        ) is False

    def test_exclude_id(self):
        reservations = [_reservation(res_id="RES-001")]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5),
            exclude_id="RES-001",
        ) is False

    def test_adjacent_dates_no_conflict(self):
        """Rezerwacja kończy się dzień przed nową — brak konfliktu."""
        reservations = [_reservation(start_offset=0, end_offset=4)]
        assert has_conflict(
            reservations, "M001", _date_str(5), _date_str(10)
        ) is False

    def test_adjacent_dates_touching(self):
        """Stykające się daty — JEST konflikt (potrzebny dzień na transport)."""
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(
            reservations, "M001", _date_str(5), _date_str(10)
        ) is True


# =============================================================================
# run_daily_sync
# =============================================================================


class TestRunDailySync:
    def test_active_reservation_sets_na_budowie(self):
        m = _machine(status="W magazynie")
        r = _reservation(start_offset=-2, end_offset=3)
        result = run_daily_sync([m], [r])
        assert m.status == "Na budowie"
        assert result["updated"] == 1

    def test_w_serwisie_not_touched(self):
        m = _machine(status="W serwisie")
        r = _reservation(start_offset=-2, end_offset=3)
        run_daily_sync([m], [r])
        assert m.status == "W serwisie"

    def test_overdue_extends_end_date(self):
        m = _machine(status="Na budowie")
        r = _reservation(start_offset=-10, end_offset=-2)
        result = run_daily_sync([m], [r])
        assert r.end_date == _date_str(0)
        assert result["extended"] == 1

    def test_future_reservation_sets_zarezerwowana(self):
        m = _machine(status="W magazynie")
        r = _reservation(start_offset=5, end_offset=10)
        result = run_daily_sync([m], [r])
        assert m.status == "Zarezerwowana"
        assert result["reserved"] == 1

    def test_rejected_reservation_ignored(self):
        m = _machine(status="W magazynie")
        r = _reservation(
            start_offset=-2, end_offset=3, status="anulowana"
        )
        run_daily_sync([m], [r])
        assert m.status == "W magazynie"

    def test_no_machine_found_no_crash(self):
        r = _reservation(machine_id="NIEISTNIEJĄCA")
        result = run_daily_sync([], [r])
        assert result["updated"] == 0

    def test_active_plus_future_stays_na_budowie(self):
        """Maszyna z aktywną i przyszłą rezerwacją — zostaje 'Na budowie'."""
        m = _machine(status="W magazynie")
        r_active = _reservation(
            start_offset=-2, end_offset=3, res_id="RES-ACTIVE"
        )
        r_future = _reservation(
            start_offset=7, end_offset=14, res_id="RES-FUTURE"
        )
        result = run_daily_sync([m], [r_active, r_future])

        assert m.status == "Na budowie"
        assert result["updated"] == 1
        assert result["reserved"] == 0
