"""Tests for the create/update/cancel/complete/confirm services."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory
from reservations.models import Reservation
from reservations.services import (
    cancel_reservation,
    complete_reservation,
    confirm_reservation,
    create_reservation,
    update_reservation,
)

# =============================================================================
# create_reservation
# =============================================================================


@pytest.mark.django_db
class TestCreateReservation:
    def test_creates_with_default_status_oczekujaca(self, machine):
        today = date(2030, 1, 1)
        res = create_reservation(
            machine_id=machine.pk,
            site_id=None,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="Anna Test",
            today=today,
        )
        assert res.pk is not None
        assert res.status == Reservation.Status.OCZEKUJACA
        assert res.person == "Anna Test"

    def test_rejects_past_dates(self, machine):
        today = date(2030, 1, 15)
        with pytest.raises(ValidationError):
            create_reservation(
                machine_id=machine.pk,
                site_id=None,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 10),
                person="Anna",
                today=today,
            )

    def test_rejects_end_before_start(self, machine):
        today = date(2030, 1, 1)
        with pytest.raises(ValidationError):
            create_reservation(
                machine_id=machine.pk,
                site_id=None,
                start_date=date(2030, 2, 10),
                end_date=date(2030, 2, 5),
                person="Anna",
                today=today,
            )

    def test_rejects_empty_person(self, machine):
        with pytest.raises(ValidationError):
            create_reservation(
                machine_id=machine.pk,
                site_id=None,
                start_date=date(2030, 2, 1),
                end_date=date(2030, 2, 5),
                person="   ",
                today=date(2030, 1, 1),
            )

    def test_rejects_when_conflict(self, machine):
        today = date(2030, 1, 1)
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        with pytest.raises(ValidationError, match="kolidujących"):
            create_reservation(
                machine_id=machine.pk,
                site_id=None,
                start_date=date(2030, 2, 3),
                end_date=date(2030, 2, 6),
                person="Anna",
                today=today,
            )

    def test_rejects_unknown_machine(self, db):
        with pytest.raises(ValidationError):
            create_reservation(
                machine_id=99999,
                site_id=None,
                start_date=date(2030, 2, 1),
                end_date=date(2030, 2, 5),
                person="Anna",
                today=date(2030, 1, 1),
            )

    def test_creates_with_site(self, machine, site):
        res = create_reservation(
            machine_id=machine.pk,
            site_id=site.pk,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="Anna",
            today=date(2030, 1, 1),
        )
        assert res.site_id == site.pk

    def test_creates_when_end_date_equals_today(self, machine):
        """Boundary: end_date == today powinno przejść (granica włączna).

        Service używa ``end_date < today`` jako rejection rule. Dzisiejsze
        zakończenie jest ważne (one-day booking, np. transport jednodniowy).
        Bez tego testu mutacja ``< `` → ``<=`` przeszłaby bez wykrycia.
        """
        today = date(2030, 6, 1)
        res = create_reservation(
            machine_id=machine.pk,
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 1),
            person="Anna Test",
            today=today,
        )
        assert res.pk is not None
        assert res.end_date == today

    def test_creates_when_start_date_equals_today(self, machine):
        """Boundary: start_date == today (start "dziś" jest legalny)."""
        today = date(2030, 6, 1)
        res = create_reservation(
            machine_id=machine.pk,
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="Anna Test",
            today=today,
        )
        assert res.pk is not None
        assert res.start_date == today

    def test_rejects_wycofana_machine(self, db):
        """Wave 4 P0: maszyna WYCOFANA z floty nie może mieć nowych rezerwacji.

        Forma już ją wyklucza z dropdownu (test_forms), ale defence-in-depth:
        service layer też blokuje (bezpośrednie wywołanie z admin / chatbot /
        API). Bez tego operator mógł zarezerwować już sprzedaną maszynę.
        """
        retired = Machine.objects.create(
            uid="K-RETIRED",
            name="Sprzedana koparka",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.WYCOFANA,
        )
        with pytest.raises(ValidationError, match="wycofana z floty"):
            create_reservation(
                machine_id=retired.pk,
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Anna Test",
                today=date(2030, 5, 1),
            )


# =============================================================================
# update_reservation
# =============================================================================


@pytest.mark.django_db
class TestUpdateReservation:
    def test_updates_simple_fields(self, machine):
        res = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        update_reservation(res, person="Nowa Osoba", notes="extra")
        res.refresh_from_db()
        assert res.person == "Nowa Osoba"
        assert res.notes == "extra"

    def test_rejects_end_before_start(self, machine):
        res = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        with pytest.raises(ValidationError):
            update_reservation(res, start_date=date(2030, 2, 10), end_date=date(2030, 2, 1))

    def test_rejects_when_new_dates_conflict_with_another(self, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 3, 1), end_date=date(2030, 3, 10)
        )
        res = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 4, 1), end_date=date(2030, 4, 5)
        )
        with pytest.raises(ValidationError, match="koliduje"):
            update_reservation(res, start_date=date(2030, 3, 5), end_date=date(2030, 3, 8))

    def test_can_move_dates_when_no_conflict(self, machine):
        res = ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 4, 1), end_date=date(2030, 4, 5)
        )
        update_reservation(res, start_date=date(2030, 5, 1), end_date=date(2030, 5, 5))
        res.refresh_from_db()
        assert res.start_date == date(2030, 5, 1)
        assert res.end_date == date(2030, 5, 5)

    def test_ignores_unknown_fields(self, machine):
        res = ConfirmedReservationFactory(machine=machine)
        update_reservation(res, person="Test", bogus="ignored")
        res.refresh_from_db()
        assert res.person == "Test"

    def test_rejects_direct_status_zakonczona(self, machine):
        """Hard Return Policy: nie można ustawić ZAKONCZONA przez update_reservation.

        Bezpośredni setattr pominąłby return_machine_to_warehouse — maszyna
        zostałaby z statusem ``Na budowie``, mimo że rezerwacja jest formalnie
        zakończona. Service musi rzucić ValidationError z komunikatem
        wskazującym właściwą drogę (complete_reservation).
        """
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="complete_reservation"):
            update_reservation(res, status=Reservation.Status.ZAKONCZONA)
        res.refresh_from_db()
        # Status pozostaje POTWIERDZONA — guard nie wpuścił zmiany.
        assert res.status == Reservation.Status.POTWIERDZONA


# =============================================================================
# state transitions: confirm / cancel / complete
# =============================================================================


@pytest.mark.django_db
class TestConfirmReservation:
    def test_oczekujaca_to_potwierdzona(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="X",
            status=Reservation.Status.OCZEKUJACA,
        )
        confirm_reservation(res)
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA

    def test_rejects_when_not_pending(self, machine):
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError):
            confirm_reservation(res)


@pytest.mark.django_db
class TestCancelReservation:
    def test_pending_can_cancel(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="X",
            status=Reservation.Status.OCZEKUJACA,
        )
        cancel_reservation(res, reason="klient_zrezygnowal")
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA
        assert res.cancellation_reason == "klient_zrezygnowal"

    def test_confirmed_can_cancel(self, machine):
        res = ConfirmedReservationFactory(machine=machine)
        cancel_reservation(res, reason="zmiana_terminu", note="Klient prosi o przesunięcie")
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA
        assert res.cancellation_reason == "zmiana_terminu"
        assert res.cancellation_note == "Klient prosi o przesunięcie"

    def test_completed_cannot_cancel(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="X",
            status=Reservation.Status.ZAKONCZONA,
        )
        with pytest.raises(ValidationError):
            cancel_reservation(res, reason="klient_zrezygnowal")

    def test_already_cancelled_is_noop(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="X",
            status=Reservation.Status.ANULOWANA,
        )
        # Idempotent — reason nie wymagany dla already-cancelled.
        cancel_reservation(res)
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA

    def test_reason_required(self, machine):
        """B-2: brak reason rzuca ValidationError."""
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="Powód anulowania jest wymagany"):
            cancel_reservation(res)

    def test_unknown_reason_rejected(self, machine):
        """B-2: reason musi być w CancellationReason choices."""
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="Nieznany powód"):
            cancel_reservation(res, reason="totally_made_up")


@pytest.mark.django_db
class TestCompleteReservation:
    def test_confirmed_completes_and_returns_machine(self, machine):
        machine.status = Machine.Status.NA_BUDOWIE
        machine.location = "Budowa testowa"
        machine.save()
        res = ConfirmedReservationFactory(machine=machine)
        complete_reservation(res)
        res.refresh_from_db()
        machine.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert machine.status == Machine.Status.W_MAGAZYNIE
        assert machine.location == "Magazyn"

    def test_pending_cannot_complete(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
            person="X",
            status=Reservation.Status.OCZEKUJACA,
        )
        with pytest.raises(ValidationError):
            complete_reservation(res)
