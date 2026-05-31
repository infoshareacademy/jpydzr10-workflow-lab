"""Testy macierzy legalnych przejść statusów rezerwacji.

Pokrywa :data:`reservations.services.RESERVATION_TRANSITIONS` oraz guard
:func:`_assert_legal_transition` — wszystkie cztery wartości
:class:`Reservation.Status` przetestowane parami legal / illegal.

Sens biznesowy:

* OCZEKUJACA → POTWIERDZONA / ANULOWANA — manager może zatwierdzić lub odrzucić.
* POTWIERDZONA → ZAKONCZONA / ANULOWANA — booking aktywny → koniec lub anulacja.
* ZAKONCZONA / ANULOWANA — stany terminalne, brak resurrection.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import (
    RESERVATION_TRANSITIONS,
    _assert_legal_transition,
    cancel_reservation,
    complete_reservation,
    confirm_reservation,
)

# =============================================================================
# RESERVATION_TRANSITIONS — macierz strukturalna
# =============================================================================


class TestTransitionMatrix:
    """Snapshot macierzy — chroni przed przypadkowym poluzowaniem reguł."""

    def test_pending_can_go_to_confirmed_or_cancelled(self):
        assert RESERVATION_TRANSITIONS[Reservation.Status.OCZEKUJACA] == {
            Reservation.Status.POTWIERDZONA,
            Reservation.Status.ANULOWANA,
        }

    def test_confirmed_can_go_to_completed_or_cancelled(self):
        assert RESERVATION_TRANSITIONS[Reservation.Status.POTWIERDZONA] == {
            Reservation.Status.ZAKONCZONA,
            Reservation.Status.ANULOWANA,
        }

    def test_completed_is_terminal(self):
        assert RESERVATION_TRANSITIONS[Reservation.Status.ZAKONCZONA] == set()

    def test_cancelled_is_terminal(self):
        assert RESERVATION_TRANSITIONS[Reservation.Status.ANULOWANA] == set()


# =============================================================================
# _assert_legal_transition — czysty guard (no DB)
# =============================================================================


class TestAssertLegalTransition:
    """Bezpośrednie testy guardu — bez ORM-u, czysta logika."""

    def test_legal_pending_to_confirmed_passes(self):
        # Nie powinno rzucić.
        _assert_legal_transition(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)

    def test_illegal_completed_to_confirmed_raises(self):
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            _assert_legal_transition(Reservation.Status.ZAKONCZONA, Reservation.Status.POTWIERDZONA)

    def test_illegal_cancelled_to_confirmed_raises(self):
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            _assert_legal_transition(Reservation.Status.ANULOWANA, Reservation.Status.POTWIERDZONA)

    def test_illegal_pending_to_completed_skips_confirmation(self):
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            _assert_legal_transition(Reservation.Status.OCZEKUJACA, Reservation.Status.ZAKONCZONA)

    def test_illegal_confirmed_to_pending_no_backtrack(self):
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            _assert_legal_transition(Reservation.Status.POTWIERDZONA, Reservation.Status.OCZEKUJACA)


# =============================================================================
# Integration — services używają guardu
# =============================================================================


@pytest.mark.django_db
class TestServiceTransitions:
    """Testy że confirm/cancel/complete wywołują guard."""

    def test_legal_pending_to_confirmed_via_service(self, machine):
        res = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        result = confirm_reservation(res)
        assert result.status == Reservation.Status.POTWIERDZONA

    def test_legal_pending_to_cancelled_via_service(self, machine):
        res = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        # B-2: reason wymagany
        result = cancel_reservation(res, reason="klient_zrezygnowal")
        assert result.status == Reservation.Status.ANULOWANA

    def test_legal_confirmed_to_completed_via_service(self, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        # Bug 19 walidacja: today musi byc >= start_date (maszyna juz wyjechala)
        result = complete_reservation(res, today=date(2030, 2, 3))
        assert result.status == Reservation.Status.ZAKONCZONA

    def test_legal_confirmed_to_cancelled_via_service(self, machine):
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        # B-2: reason wymagany
        result = cancel_reservation(res, reason="awaria")
        assert result.status == Reservation.Status.ANULOWANA

    def test_illegal_completed_to_confirmed_via_service(self, machine):
        res = CompletedReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            confirm_reservation(res)

    def test_illegal_cancelled_to_confirmed_via_service(self, machine):
        res = CancelledReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            confirm_reservation(res)

    def test_illegal_pending_to_completed_bypass(self, machine):
        """Próba "skoku" OCZEKUJACA → ZAKONCZONA z pominięciem confirm."""
        res = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            complete_reservation(res)

    def test_illegal_confirmed_to_pending_no_backtrack_via_service(self, machine):
        """Confirmed rezerwacja nie może cofnąć się do oczekującej.

        Brak dedykowanego service do tego przejścia — pokazujemy że
        :data:`RESERVATION_TRANSITIONS` blokuje próbę z poziomu guardu.
        """
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            _assert_legal_transition(Reservation.Status.POTWIERDZONA, Reservation.Status.OCZEKUJACA)
