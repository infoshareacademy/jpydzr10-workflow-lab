"""Tests for the Hard Return Policy and the four rules of ``run_daily_sync``.

Each rule is covered by a dedicated test; ``freezegun`` is used to lock the
"today" value so the assertions are stable across timezones / clocks.

Rules under test:

1. Machine ``W serwisie`` is skipped.
2. Active reservation (``start <= today <= end``) flips the machine to
   ``Na budowie``.
3. Overdue confirmed reservation (machine still ``Na budowie``) gets the
   ``end_date`` extended to today (Hard Return Policy).
4. Warehouse machine with a future confirmed reservation flips to
   ``Zarezerwowana`` (pass 2 — order-independent).
"""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.services import run_daily_sync


@pytest.mark.django_db
class TestRuleOneServiceTakesPrecedence:
    def test_in_service_machine_is_not_touched(self, machine):
        machine.status = Machine.Status.W_SERWISIE
        machine.save()
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        run_daily_sync(today=date(2030, 1, 5))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_SERWISIE


@pytest.mark.django_db
class TestRuleTwoActiveReservationFlipsToOnSite:
    def test_active_reservation_promotes_machine(self, machine, site):
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        result = run_daily_sync(today=date(2030, 1, 5))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.NA_BUDOWIE
        assert result["updated"] == 1

    def test_reservation_address_overrides_site_address(self, machine, site):
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
            address="Adres dostawy bezpośredni",
        )
        run_daily_sync(today=date(2030, 1, 5))
        machine.refresh_from_db()
        assert machine.location == "Adres dostawy bezpośredni"

    def test_already_on_site_no_double_count(self, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 5))
        assert result["updated"] == 0  # already correct status


@pytest.mark.django_db
class TestRuleThreeHardReturnPolicy:
    def test_overdue_on_site_extends_end_date(self, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 20))
        res.refresh_from_db()
        assert res.end_date == date(2030, 1, 20)
        assert result["extended"] == 1

    def test_overdue_warehouse_machine_not_extended(self, machine):
        """If the machine is already W magazynie there is nothing to extend."""
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 20))
        assert result["extended"] == 0


@pytest.mark.django_db
class TestRuleFourFutureReservationFlipsToReserved:
    def test_future_reservation_promotes_warehouse_to_reserved(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 5, 1), end_date=date(2030, 5, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 1))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.ZAREZERWOWANA
        assert result["reserved"] == 1

    def test_already_reserved_is_idempotent(self, machine):
        machine.status = Machine.Status.ZAREZERWOWANA
        machine.save()
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 5, 1), end_date=date(2030, 5, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 1))
        assert result["reserved"] == 0


@pytest.mark.django_db
class TestPendingAndCancelledIgnored:
    def test_pending_does_not_flip_anything(self, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 5))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE
        assert (result["updated"], result["extended"], result["reserved"]) == (0, 0, 0)

    def test_cancelled_does_not_flip_anything(self, machine):
        CancelledReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        result = run_daily_sync(today=date(2030, 1, 5))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE
        assert result == {
            "updated": 0,
            "extended": 0,
            "reserved": 0,
            "released": 0,
            "today": date(2030, 1, 5),
        }


@pytest.mark.django_db
class TestTwoPassOrderIndependence:
    """Pass 2 ensures a machine cleared by an overdue rez. still gets flipped.

    Scenario: machine has an overdue confirmed reservation (Hard Return
    Policy extends end_date) AND a future confirmed reservation. After the
    daily sync, the machine should be ``Na budowie`` (covered by the
    extended booking) — the future booking is a no-op here. But if the
    iteration order processed the future booking first, a naïve single-pass
    impl could have moved the machine to ``Zarezerwowana`` then NOT back.
    """

    def test_two_overlapping_confirmed_results_in_on_site(self, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        # Overdue
        overdue = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        # Future (no conflict with extended date because Hard Return only
        # extends to today=2030-01-20 < 2030-02-01).
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 10)
        )
        run_daily_sync(today=date(2030, 1, 20))
        overdue.refresh_from_db()
        machine.refresh_from_db()
        assert overdue.end_date == date(2030, 1, 20)
        assert machine.status == Machine.Status.NA_BUDOWIE


@pytest.mark.django_db
class TestFreezegunCompat:
    """run_daily_sync() with no today argument uses date.today()."""

    def test_uses_today_when_no_arg(self, machine):
        with freeze_time("2030-06-15"):
            ConfirmedReservationFactory(
                machine=machine, start_date=date(2030, 6, 10), end_date=date(2030, 6, 20)
            )
            result = run_daily_sync()
            assert result["today"] == date(2030, 6, 15)


@pytest.mark.django_db
class TestDailySyncBoundaries:
    """Boundary tests dla ``start <= today <= end`` w run_daily_sync.

    Mutation analysis pokazał że granice tej nierówności są "luźne" — można
    było zmienić ``<=`` → ``<`` (na obu końcach) bez wykrycia przez istniejące
    testy, które używały day-in-middle scenariusza (np. today=2030-01-05
    pomiędzy 01-01 a 01-10). Te testy dotykają każdą z granic dokładnie.
    """

    @freeze_time("2030-06-01")
    def test_sync_active_when_start_equals_today(self, machine):
        """today == start_date → maszyna przechodzi na NA_BUDOWIE (lower bound).

        Bez tego testu mutacja ``start <= today`` → ``start < today`` przeszłaby:
        machine zostałby w W_MAGAZYNIE/ZAREZERWOWANA pierwszego dnia rezerwacji.
        """
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        run_daily_sync(today=date(2030, 6, 1))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.NA_BUDOWIE

    @freeze_time("2030-06-05")
    def test_sync_active_when_end_equals_today(self, machine):
        """today == end_date → maszyna NADAL NA_BUDOWIE (upper bound, inkluzywny).

        Bez tego testu mutacja ``today <= end`` → ``today < end`` przeszłaby:
        machine ostatniego dnia rezerwacji uznano by za zakończoną i Hard
        Return Policy by przedłużyło end_date.
        """
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        run_daily_sync(today=date(2030, 6, 5))
        machine.refresh_from_db()
        res.refresh_from_db()
        assert machine.status == Machine.Status.NA_BUDOWIE
        # End_date NIE rozszerzony — booking jest w aktywnym oknie.
        assert res.end_date == date(2030, 6, 5)

    @freeze_time("2030-06-06")
    def test_sync_extends_when_today_just_past_end(self, machine):
        """today == end_date + 1 → Hard Return Policy: end_date rozszerza się.

        Granica drugiej strony: o jeden dzień po zakończeniu rezerwacji,
        machine NADAL NA_BUDOWIE (= nie wrócił do magazynu), end_date
        powinien być rozszerzony do today.
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        result = run_daily_sync(today=date(2030, 6, 6))
        res.refresh_from_db()
        assert res.end_date == date(2030, 6, 6)
        assert result["extended"] == 1
