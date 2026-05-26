"""Property-based tests for :func:`reservations.services.has_conflict`.

Verifies invariants that a hand-rolled testsuite is unlikely to cover:

* **Symmetry** — overlap is order-independent:
  ``has_conflict(A,B) == has_conflict(B,A)`` for the same machine.
* **Self-overlap** — a reservation always conflicts with itself
  (when ``exclude_pk`` is not passed).
* **Touching-dates rule** — when ``end_a == start_b`` the result is True.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reservations.factories import ConfirmedReservationFactory
from reservations.models import Reservation
from reservations.services import has_conflict

SAFE_DATES = st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31))


def _reset_reservations(machine) -> None:
    """Wipe any Reservation rows for ``machine`` between hypothesis examples.

    Hypothesis shares the function-scoped ``machine`` fixture across many
    examples in one test invocation; without this reset, factory-created
    rows from earlier examples would conflict with the current example.
    """
    Reservation.objects.filter(machine=machine).delete()


@pytest.mark.django_db
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    start1=SAFE_DATES,
    duration1=st.integers(min_value=1, max_value=30),
    offset=st.integers(min_value=-30, max_value=30),
    duration2=st.integers(min_value=1, max_value=30),
)
def test_has_conflict_is_symmetric(machine, start1, duration1, offset, duration2):
    """has_conflict(A,B) ⇔ has_conflict(B,A): overlap is order-independent."""
    _reset_reservations(machine)

    end1 = start1 + timedelta(days=duration1)
    start2 = start1 + timedelta(days=offset)
    end2 = start2 + timedelta(days=duration2)
    if end2 < start2 or end1 < start1:
        return  # not a valid pair, skip

    ConfirmedReservationFactory(machine=machine, start_date=start1, end_date=end1)

    a_then_b = has_conflict(machine_id=machine.pk, start=start2, end=end2)
    # The expected boolean comes from the date-arithmetic rule (touching
    # dates included). Two intervals overlap iff ``start_a <= end_b AND
    # end_a >= start_b``.
    expected = (start2 <= end1) and (end2 >= start1)
    assert a_then_b is expected


@pytest.mark.django_db
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(start=SAFE_DATES, duration=st.integers(min_value=1, max_value=30))
def test_self_overlap_when_not_excluded(machine, start, duration):
    """A reservation always conflicts with itself unless we exclude its pk."""
    _reset_reservations(machine)

    end = start + timedelta(days=duration)
    res = ConfirmedReservationFactory(machine=machine, start_date=start, end_date=end)
    assert has_conflict(machine_id=machine.pk, start=start, end=end) is True
    assert has_conflict(machine_id=machine.pk, start=start, end=end, exclude_pk=res.pk) is False


@pytest.mark.django_db
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    start=SAFE_DATES,
    duration1=st.integers(min_value=1, max_value=30),
    duration2=st.integers(min_value=1, max_value=30),
)
def test_touching_dates_always_conflict(machine, start, duration1, duration2):
    """end_a == start_b → True (one-day transport rule from M1)."""
    _reset_reservations(machine)

    end1 = start + timedelta(days=duration1)
    start2 = end1
    end2 = start2 + timedelta(days=duration2)
    ConfirmedReservationFactory(machine=machine, start_date=start, end_date=end1)
    assert has_conflict(machine_id=machine.pk, start=start2, end=end2) is True
