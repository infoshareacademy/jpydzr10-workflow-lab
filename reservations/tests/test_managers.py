"""Tests for the :class:`reservations.managers.ReservationManager` queryset helpers."""

from __future__ import annotations

from datetime import date

import pytest

from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation


@pytest.mark.django_db
class TestStatusFilters:
    def test_active_includes_pending_and_confirmed(self, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        CancelledReservationFactory(
            machine=machine, start_date=date(2030, 3, 1), end_date=date(2030, 3, 5)
        )
        CompletedReservationFactory(
            machine=machine, start_date=date(2030, 4, 1), end_date=date(2030, 4, 5)
        )
        assert Reservation.objects.active().count() == 2

    def test_pending_only(self, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        assert Reservation.objects.pending().count() == 1

    def test_confirmed_only(self, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        assert Reservation.objects.confirmed().count() == 1


@pytest.mark.django_db
class TestDateFilters:
    def test_for_period_overlaps_inclusive(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 10)
        )
        # Overlap: only the January one
        assert Reservation.objects.for_period(date(2030, 1, 5), date(2030, 1, 12)).count() == 1
        # Overlap: both
        assert Reservation.objects.for_period(date(2030, 1, 1), date(2030, 3, 1)).count() == 2

    def test_overdue_returns_confirmed_past_end(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2025, 1, 1), end_date=date(2025, 1, 10)
        )
        PendingReservationFactory(
            machine=machine, start_date=date(2025, 2, 1), end_date=date(2025, 2, 10)
        )
        assert Reservation.objects.overdue(today=date(2030, 1, 1)).count() == 1

    def test_upcoming(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 5, 1), end_date=date(2030, 5, 10)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2025, 1, 1), end_date=date(2025, 1, 10)
        )
        assert Reservation.objects.upcoming(today=date(2030, 1, 1)).count() == 1


@pytest.mark.django_db
class TestConflictsFor:
    def test_excludes_self(self, machine):
        existing = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        qs = Reservation.objects.conflicts_for(
            machine_id=machine.pk,
            start=date(2030, 1, 5),
            end=date(2030, 1, 8),
            exclude_pk=existing.pk,
        )
        assert qs.count() == 0


@pytest.mark.django_db
class TestSearch:
    def test_search_matches_person(self, machine):
        ConfirmedReservationFactory(
            machine=machine,
            person="Jan Kowalski",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            person="Anna Nowak",
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        assert Reservation.objects.search("Kowalski").count() == 1

    def test_search_empty_returns_all(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        assert Reservation.objects.search("").count() == 2


# =============================================================================
# Wave 12 — coverage gap-filling: cancelled, completed, active_today, for_machine, for_site
# =============================================================================


@pytest.mark.django_db
class TestExtraManagerMethods:
    """Pokrycie metod managera niedotykanych przez wcześniejsze testy."""

    def test_cancelled_returns_only_anulowana(self, machine):
        CancelledReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        assert Reservation.objects.cancelled().count() == 1

    def test_completed_returns_only_zakonczona(self, machine):
        CompletedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        assert Reservation.objects.completed().count() == 1

    def test_active_today_returns_only_period_covering_today(self, machine):
        # Pokrywa dziś
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 31)
        )
        # Nie pokrywa
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 6, 1), end_date=date(2030, 6, 30)
        )
        qs = Reservation.objects.active_today(today=date(2030, 1, 15))
        assert qs.count() == 1

    def test_for_machine_filters_by_machine_id(self, machine):
        from machines.models import Machine

        other_machine = Machine.objects.create(
            uid="OTHR-1",
            name="Inna",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=other_machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        assert Reservation.objects.for_machine(machine_id=machine.pk).count() == 1

    def test_for_site_filters_by_site_id(self, machine):
        from reservations.factories import ConstructionSiteFactory

        site_a = ConstructionSiteFactory(project_number="BUD-AAA")
        site_b = ConstructionSiteFactory(project_number="BUD-BBB")
        ConfirmedReservationFactory(
            machine=machine,
            site=site_a,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            site=site_b,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        assert Reservation.objects.for_site(site_id=site_a.pk).count() == 1

    def test_active_in_period_combines_active_and_for_period(self, machine):
        # Active in period
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        # Cancelled w okresie — wykluczona przez .active()
        CancelledReservationFactory(
            machine=machine, start_date=date(2030, 1, 5), end_date=date(2030, 1, 8)
        )
        # Active poza okresem — wykluczona przez .for_period()
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 6, 1), end_date=date(2030, 6, 10)
        )
        qs = Reservation.objects.active_in_period(start=date(2030, 1, 1), end=date(2030, 1, 15))
        assert qs.count() == 1

    def test_upcoming_default_uses_date_today(self, machine):
        """upcoming() bez ``today`` używa date.today() (line 100)."""
        from freezegun import freeze_time

        with freeze_time("2030-01-01"):
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 5, 1),
                end_date=date(2030, 5, 5),
            )
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2029, 5, 1),
                end_date=date(2029, 5, 5),
            )
            assert Reservation.objects.upcoming().count() == 1

    def test_active_today_default_uses_date_today(self, machine):
        """active_today() bez parametru używa date.today() (line 105-106)."""
        from freezegun import freeze_time

        with freeze_time("2030-01-15"):
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 31),
            )
            assert Reservation.objects.active_today().count() == 1
