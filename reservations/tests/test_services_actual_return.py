"""Testy "Faktyczna data zwrotu" (B-3) — wcześniejszy zwrot zwalnia maszynę.

Pokrywa:

* service ``complete_reservation`` przyjmuje opcjonalny ``actual_return_date``,
* walidacja: actual_return_date >= start_date,
* walidacja: actual_return_date <= today,
* default: brak parametru → actual_return_date pozostaje NULL,
* po zakończeniu z wcześniejszą datą — nowa rezerwacja może być utworzona
  w terminie po actual_return_date (machine status W_MAGAZYNIE),
* display właściwości w detail page (model.actual_return_date),
* view POST przyjmuje pole actual_return_date.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory
from reservations.models import Reservation
from reservations.services import (
    complete_reservation,
    create_reservation,
)


@pytest.mark.django_db
class TestCompleteReservationWithActualReturn:
    """Service-level: complete_reservation + actual_return_date."""

    def test_default_no_actual_return_date(self, machine):
        """Brak parametru — pole pozostaje NULL (legacy behavior)."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        # Bug 19 walidacja: today musi byc >= start_date (maszyna juz wyjechala)
        complete_reservation(res, today=date(2030, 1, 5))
        res.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert res.actual_return_date is None

    @freeze_time("2030-01-05")
    def test_actual_return_date_saved(self, machine):
        """Z parametrem — actual_return_date jest zapisana."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        complete_reservation(res, actual_return_date=date(2030, 1, 5))
        res.refresh_from_db()
        assert res.actual_return_date == date(2030, 1, 5)
        assert res.status == Reservation.Status.ZAKONCZONA

    @freeze_time("2030-01-05")
    def test_actual_return_before_start_rejected(self, machine):
        """B-3: actual_return_date < start_date rzuca ValidationError."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 3),
            end_date=date(2030, 1, 10),
        )
        with pytest.raises(ValidationError, match="wcześniejsza niż data początku"):
            complete_reservation(res, actual_return_date=date(2030, 1, 1))
        res.refresh_from_db()
        # Rollback — status pozostaje POTWIERDZONA (atomic)
        assert res.status == Reservation.Status.POTWIERDZONA

    @freeze_time("2030-01-05")
    def test_actual_return_in_future_rejected(self, machine):
        """B-3: actual_return_date > today rzuca ValidationError."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        with pytest.raises(ValidationError, match="w przyszłości"):
            complete_reservation(res, actual_return_date=date(2030, 1, 6))
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA

    @freeze_time("2030-01-05")
    def test_actual_return_equals_today_allowed(self, machine):
        """Boundary: actual_return_date == today jest OK."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        complete_reservation(res, actual_return_date=date(2030, 1, 5))
        res.refresh_from_db()
        assert res.actual_return_date == date(2030, 1, 5)

    @freeze_time("2030-01-05")
    def test_actual_return_equals_start_allowed(self, machine):
        """Boundary: same-day reservation — actual_return_date == start_date OK."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 5),
            end_date=date(2030, 1, 10),
        )
        complete_reservation(res, actual_return_date=date(2030, 1, 5))
        res.refresh_from_db()
        assert res.actual_return_date == date(2030, 1, 5)


@pytest.mark.django_db
class TestEarlyReturnFreesMachine:
    """Integration: wcześniejszy zwrot → kolejna rezerwacja możliwa."""

    @freeze_time("2030-01-05")
    def test_early_return_allows_new_reservation_for_same_machine(self, machine):
        """Klient zwraca 5 dni wcześniej → następny może użyć od jutro.

        Scenariusz biznesowy:
          1. Rezerwacja A: 1-15 stycznia, dziś jest 5.
          2. Klient zwraca dziś (5 stycznia) — actual_return_date=2030-01-05.
          3. Maszyna → W_MAGAZYNIE (zachowanie complete_reservation).
          4. Nowa rezerwacja B: 6 stycznia w przód.
          5. Rezerwacja B nie koliduje z A (A ma status ZAKONCZONA).
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()

        # Step 1: aktywna rezerwacja
        res_a = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 15),  # 10 dni przed planem
        )

        # Step 2-3: wcześniejszy zwrot
        complete_reservation(res_a, actual_return_date=date(2030, 1, 5))
        res_a.refresh_from_db()
        machine.refresh_from_db()
        assert res_a.actual_return_date == date(2030, 1, 5)
        assert machine.status == Machine.Status.W_MAGAZYNIE

        # Step 4-5: nowa rezerwacja może się utworzyć (bo res_a ma status ZAKONCZONA)
        res_b = create_reservation(
            machine_id=machine.pk,
            site_id=None,
            start_date=date(2030, 1, 6),
            end_date=date(2030, 1, 20),
            person="Nowy Klient",
            today=date(2030, 1, 5),
        )
        assert res_b.pk is not None
        # Old rezerwacja nie blokuje, bo conflicts_for filtruje po aktywnych statusach
        assert res_b.status == Reservation.Status.OCZEKUJACA

    @freeze_time("2030-01-05")
    def test_completed_without_actual_return_does_not_block(self, machine):
        """Sanity: standardowy complete (bez actual_return_date) też zwalnia maszynę."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 15),
        )
        complete_reservation(res)  # bez actual_return_date

        res.refresh_from_db()
        machine.refresh_from_db()
        assert res.actual_return_date is None
        assert machine.status == Machine.Status.W_MAGAZYNIE

        # Nowa rezerwacja jutro też OK (res.status == ZAKONCZONA, więc nie konflikt)
        res_b = create_reservation(
            machine_id=machine.pk,
            site_id=None,
            start_date=date(2030, 1, 6),
            end_date=date(2030, 1, 20),
            person="X",
            today=date(2030, 1, 5),
        )
        assert res_b.pk is not None


@pytest.mark.django_db
class TestCompleteViewActualReturn:
    """View-level: POST actual_return_date."""

    def test_view_accepts_actual_return_date(self, client_logged, machine):
        """POST z actual_return_date → field saved."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        # rezerwacja z end_date w przyszłości, ale jakaś start_date przeszła
        start = date.today() - timedelta(days=3)
        end = date.today() + timedelta(days=10)
        res = ConfirmedReservationFactory(machine=machine, start_date=start, end_date=end)
        actual = date.today() - timedelta(days=1)
        response = client_logged.post(
            reverse("reservations:complete", args=[res.pk]),
            data={"actual_return_date": actual.isoformat()},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert res.actual_return_date == actual

    def test_view_without_field_works_default(self, client_logged, machine):
        """POST bez pola — pole pozostaje NULL (legacy)."""
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.post(reverse("reservations:complete", args=[res.pk]))
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert res.actual_return_date is None

    def test_view_rejects_invalid_date_silently(self, client_logged, machine):
        """Niepoprawny format daty → parse_iso_date zwraca None, traktowane jak brak."""
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.post(
            reverse("reservations:complete", args=[res.pk]),
            data={"actual_return_date": "not-a-date"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        # parse_iso_date(zwraca None) → traktowane jak brak parametru
        assert res.status == Reservation.Status.ZAKONCZONA
        assert res.actual_return_date is None
