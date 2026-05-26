"""Testy admina (django-unfold) dla ReservationAdmin.

Pokrywają bulk actions ``action_confirm`` / ``action_cancel`` / ``action_complete``
— sprawdzają, że wywołanie z ModelAdmin faktycznie zmienia statusy rezerwacji
za pomocą serwisów (confirm/cancel/complete_reservation) ORAZ że nielegalne
przejścia są skipowane (bulk action zgłasza failures via messages.WARNING
zamiast crashować na pierwszej błędnej rezerwacji).

C3-4 P0 fix per audit cluster reservations.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage

from machines.models import Machine
from reservations.admin import ReservationAdmin
from reservations.factories import (
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation

User = get_user_model()


def _request_with_messages(rf, user):
    """Buduje request z włączonym messages framework (FallbackStorage).

    Bulk actions używają :meth:`ModelAdmin.message_user`, który wymaga
    ``request._messages`` — bez tej infrastruktury wywołanie wybuchłoby
    AttributeError.
    """
    request = rf.post("/admin/reservations/reservation/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.fixture
def superuser_request(rf, db):
    """Superuser jako request.user dla testów admin actions."""
    user = User.objects.create_superuser(username="boss", password="pw", email="b@x.pl")
    return _request_with_messages(rf, user)


@pytest.mark.django_db
def test_reservation_is_registered_with_admin():
    assert site.is_registered(Reservation)


@pytest.mark.django_db
class TestActionConfirm:
    """``action_confirm`` promuje OCZEKUJACA → POTWIERDZONA bulk-wise."""

    def test_action_confirm_promotes_pending(self, superuser_request, machine):
        p1 = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        p2 = PendingReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk__in=[p1.pk, p2.pk])
        admin.action_confirm(superuser_request, queryset)

        p1.refresh_from_db()
        p2.refresh_from_db()
        assert p1.status == Reservation.Status.POTWIERDZONA
        assert p2.status == Reservation.Status.POTWIERDZONA

    def test_action_confirm_skips_completed(self, superuser_request, machine):
        """Już ZAKONCZONA → guard rzuca ValidationError, action loguje failure
        zamiast crashować."""
        pending = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        completed = CompletedReservationFactory(
            machine=machine, start_date=date(2030, 3, 1), end_date=date(2030, 3, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk__in=[pending.pk, completed.pk])
        admin.action_confirm(superuser_request, queryset)

        pending.refresh_from_db()
        completed.refresh_from_db()
        # Pending promowana (legal), completed nieruszona (illegal skipped).
        assert pending.status == Reservation.Status.POTWIERDZONA
        assert completed.status == Reservation.Status.ZAKONCZONA


@pytest.mark.django_db
class TestActionCancel:
    """``action_cancel`` ustawia ANULOWANA dla nie-terminalnych rezerwacji."""

    def test_action_cancel_cancels_pending(self, superuser_request, machine):
        pending = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk=pending.pk)
        admin.action_cancel(superuser_request, queryset)

        pending.refresh_from_db()
        assert pending.status == Reservation.Status.ANULOWANA

    def test_action_cancel_skips_completed(self, superuser_request, machine):
        """ZAKONCZONA → ANULOWANA jest nielegalne (terminalny), action loguje
        warning zamiast crashować."""
        completed = CompletedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk=completed.pk)
        admin.action_cancel(superuser_request, queryset)

        completed.refresh_from_db()
        # Status nieruszony — guard zadziałał, action zalogował failure.
        assert completed.status == Reservation.Status.ZAKONCZONA


@pytest.mark.django_db
class TestActionComplete:
    """``action_complete`` zamyka POTWIERDZONA → ZAKONCZONA i zwraca maszynę."""

    def test_action_complete_returns_machines(self, superuser_request, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.location = "Plac budowy"
        machine.save()
        confirmed = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk=confirmed.pk)
        admin.action_complete(superuser_request, queryset)

        confirmed.refresh_from_db()
        machine.refresh_from_db()
        assert confirmed.status == Reservation.Status.ZAKONCZONA
        # Service complete_reservation wywołało return_machine_to_warehouse.
        assert machine.status == Machine.Status.W_MAGAZYNIE
        assert machine.location == "Magazyn"

    def test_action_complete_skips_pending(self, superuser_request, machine):
        """OCZEKUJACA → ZAKONCZONA nielegalne (skip POTWIERDZONA), action loguje."""
        pending = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )

        admin = ReservationAdmin(Reservation, site)
        queryset = Reservation.objects.filter(pk=pending.pk)
        admin.action_complete(superuser_request, queryset)

        pending.refresh_from_db()
        assert pending.status == Reservation.Status.OCZEKUJACA
