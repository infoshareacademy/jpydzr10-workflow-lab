"""Testy logiki biznesowej: konflikty, synchronizacja statusów."""

from datetime import date, timedelta

import pytest
from models import Machine, Reservation
from logic import has_conflict, run_daily_sync


# =============================================================================
# Helpers
# =============================================================================

def _date_str(offset_days=0):
    """Zwraca datę jako string RRRR-MM-DD z przesunięciem od dziś."""
    return (date.today() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _machine(uid="M001", status="In Magazijn"):
    return Machine(uid, "Testowa", "crane", status=status)


def _reservation(machine_id="M001", start_offset=0, end_offset=5,
                 status="confirmed", res_id="RES-001"):
    return Reservation(
        res_id, machine_id,
        _date_str(start_offset), _date_str(end_offset),
        "Jan", "P100", status=status,
    )


# =============================================================================
# has_conflict
# =============================================================================


class TestHasConflict:
    def test_no_conflict_different_machine(self):
        reservations = [_reservation(machine_id="M002")]
        assert has_conflict(reservations, "M001", _date_str(0), _date_str(5)) is False

    def test_conflict_overlapping(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(reservations, "M001", _date_str(3), _date_str(8)) is True

    def test_no_conflict_after(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(reservations, "M001", _date_str(6), _date_str(10)) is False

    def test_no_conflict_before(self):
        reservations = [_reservation(start_offset=5, end_offset=10)]
        assert has_conflict(reservations, "M001", _date_str(0), _date_str(4)) is False

    def test_conflict_exact_overlap(self):
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(reservations, "M001", _date_str(0), _date_str(5)) is True

    def test_no_conflict_rejected(self):
        reservations = [_reservation(status="rejected")]
        assert has_conflict(reservations, "M001", _date_str(0), _date_str(5)) is False

    def test_no_conflict_completed(self):
        reservations = [_reservation(status="completed")]
        assert has_conflict(reservations, "M001", _date_str(0), _date_str(5)) is False

    def test_exclude_id(self):
        reservations = [_reservation(res_id="RES-001")]
        assert has_conflict(
            reservations, "M001", _date_str(0), _date_str(5), exclude_id="RES-001"
        ) is False

    def test_adjacent_dates_no_conflict(self):
        """Rezerwacja kończy się dzień przed nową — brak konfliktu."""
        reservations = [_reservation(start_offset=0, end_offset=4)]
        assert has_conflict(reservations, "M001", _date_str(5), _date_str(10)) is False

    def test_adjacent_dates_touching(self):
        """Rezerwacja kończy się tego samego dnia co nowa zaczyna — JEST konflikt."""
        reservations = [_reservation(start_offset=0, end_offset=5)]
        assert has_conflict(reservations, "M001", _date_str(5), _date_str(10)) is True


# =============================================================================
# run_daily_sync
# =============================================================================


class TestRunDailySync:
    def test_active_reservation_sets_op_de_werf(self):
        m = _machine(status="In Magazijn")
        r = _reservation(start_offset=-2, end_offset=3)
        result = run_daily_sync([m], [r])
        assert m.status == "Op de werf"
        assert result["updated"] == 1

    def test_in_herstelling_not_touched(self):
        m = _machine(status="In Herstelling")
        r = _reservation(start_offset=-2, end_offset=3)
        run_daily_sync([m], [r])
        assert m.status == "In Herstelling"

    def test_overdue_extends_end_date(self):
        m = _machine(status="Op de werf")
        r = _reservation(start_offset=-10, end_offset=-2)
        result = run_daily_sync([m], [r])
        assert r.end_date == _date_str(0)
        assert result["extended"] == 1

    def test_future_reservation_sets_gereserveerd(self):
        m = _machine(status="In Magazijn")
        r = _reservation(start_offset=5, end_offset=10)
        result = run_daily_sync([m], [r])
        assert m.status == "Gereserveerd"
        assert result["reserved"] == 1

    def test_rejected_reservation_ignored(self):
        m = _machine(status="In Magazijn")
        r = _reservation(start_offset=-2, end_offset=3, status="rejected")
        run_daily_sync([m], [r])
        assert m.status == "In Magazijn"

    def test_no_machine_found_no_crash(self):
        r = _reservation(machine_id="NIEISTNIEJĄCA")
        result = run_daily_sync([], [r])
        assert result["updated"] == 0

    # --- Nowy test: edge case z review ---

    def test_active_plus_future_reservation_stays_op_de_werf(self):
        """Maszyna z aktywną I przyszłą rezerwacją — status nie przeskakuje.

        Scenariusz: maszyna jest na budowie (aktywna rezerwacja) i ma
        kolejną rezerwację za tydzień. Po synchronizacji powinna pozostać
        'Op de werf' (nie przeskoczyć na 'Gereserveerd').
        """
        m = _machine(status="In Magazijn")
        r_active = _reservation(
            start_offset=-2, end_offset=3, res_id="RES-ACTIVE"
        )
        r_future = _reservation(
            start_offset=7, end_offset=14, res_id="RES-FUTURE"
        )
        result = run_daily_sync([m], [r_active, r_future])

        # Maszyna powinna być Op de werf (aktywna rezerwacja wygrywa)
        assert m.status == "Op de werf"
        assert result["updated"] == 1
        # Przyszła rezerwacja NIE powinna zmienić statusu na Gereserveerd,
        # bo maszyna jest już Op de werf (nie In Magazijn)
        assert result["reserved"] == 0
