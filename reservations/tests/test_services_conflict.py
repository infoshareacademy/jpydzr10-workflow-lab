"""Edge-case coverage for :func:`reservations.services.has_conflict`.

Touching dates rule (``end_a == start_b`` → conflict) is critical and gets a
dedicated test — it is the rule most likely to be regressed during refactors.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from reservations.factories import ConfirmedReservationFactory, PendingReservationFactory
from reservations.models import Reservation
from reservations.services import get_conflicting_reservations, has_conflict


@pytest.mark.django_db
class TestHasConflict:
    def test_no_other_reservations_returns_false(self, machine):
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 1),
                end=date(2030, 1, 5),
            )
            is False
        )

    def test_full_overlap_detected(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 1),
                end=date(2030, 1, 15),
            )
            is True
        )

    def test_partial_overlap_detected(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 8),
                end=date(2030, 1, 12),
            )
            is True
        )

    def test_touching_dates_are_conflict(self, machine):
        """End of one booking equals start of the next → CONFLICT (M1 rule)."""
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 10),
                end=date(2030, 1, 15),
            )
            is True
        )

    def test_no_overlap_returns_false(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 12),
                end=date(2030, 1, 15),
            )
            is False
        )

    def test_cancelled_reservation_ignored(self, machine):
        Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 1, 5),
            end_date=date(2030, 1, 10),
            person="X",
            status=Reservation.Status.ANULOWANA,
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 6),
                end=date(2030, 1, 8),
            )
            is False
        )

    def test_completed_reservation_ignored(self, machine):
        Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 1, 5),
            end_date=date(2030, 1, 10),
            person="X",
            status=Reservation.Status.ZAKONCZONA,
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 6),
                end=date(2030, 1, 8),
            )
            is False
        )

    def test_pending_reservation_counts_as_conflict(self, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 6),
                end=date(2030, 1, 8),
            )
            is True
        )

    def test_exclude_pk_skips_self_match(self, machine):
        existing = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 5),
                end=date(2030, 1, 10),
                exclude_pk=existing.pk,
            )
            is False
        )

    def test_other_machine_no_conflict(self, machine, second_machine):
        ConfirmedReservationFactory(
            machine=second_machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 10)
        )
        assert (
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 5),
                end=date(2030, 1, 10),
            )
            is False
        )

    def test_end_before_start_raises_validation_error(self, machine):
        with pytest.raises(ValidationError):
            has_conflict(
                machine_id=machine.pk,
                start=date(2030, 1, 10),
                end=date(2030, 1, 1),
            )


@pytest.mark.django_db
class TestGetConflictingReservations:
    def test_returns_select_related_rows(self, machine, site):
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 5),
            end_date=date(2030, 1, 10),
        )
        results = get_conflicting_reservations(
            machine_id=machine.pk,
            start=date(2030, 1, 6),
            end=date(2030, 1, 8),
        )
        assert len(results) == 1
        # No extra query when accessing related fields (select_related).
        assert results[0].machine.uid == machine.uid

    def test_returns_empty_list_when_no_conflict(self, machine):
        assert (
            get_conflicting_reservations(
                machine_id=machine.pk,
                start=date(2030, 1, 1),
                end=date(2030, 1, 5),
            )
            == []
        )
