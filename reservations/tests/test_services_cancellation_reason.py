"""Testy pola "Powód anulowania" (B-2) — service + view.

Pokrywa:

* service ``cancel_reservation`` wymaga reason — wszystkie pięć wartości
  :class:`Reservation.CancellationReason` przechodzi happy path,
* nieznany reason → ValidationError,
* note jest stripowana (defensive) i opcjonalna,
* status=ANULOWANA już istniejący — idempotent path NIE wymaga reason,
* view POST przyjmuje cancellation_reason + cancellation_note.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from reservations.factories import (
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import cancel_reservation


@pytest.mark.django_db
class TestCancelReservationReason:
    """Service-level — wszystkie 5 wartości CancellationReason."""

    @pytest.mark.parametrize(
        "reason_value",
        [
            "klient_zrezygnowal",
            "awaria",
            "zmiana_terminu",
            "brak_dostepnosci",
            "inne",
        ],
    )
    def test_each_valid_reason_accepted(self, machine, reason_value):
        res = ConfirmedReservationFactory(machine=machine)
        result = cancel_reservation(res, reason=reason_value)
        result.refresh_from_db()
        assert result.status == Reservation.Status.ANULOWANA
        assert result.cancellation_reason == reason_value

    def test_note_is_stripped(self, machine):
        """Defensive: note jest stripowana z whitespace."""
        res = PendingReservationFactory(machine=machine)
        cancel_reservation(res, reason="inne", note="  doprecyzowanie  ")
        res.refresh_from_db()
        assert res.cancellation_note == "doprecyzowanie"

    def test_note_default_empty(self, machine):
        """Brak note → puste w DB."""
        res = PendingReservationFactory(machine=machine)
        cancel_reservation(res, reason="klient_zrezygnowal")
        res.refresh_from_db()
        assert res.cancellation_note == ""

    def test_unknown_reason_rejected(self, machine):
        res = PendingReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="Nieznany powód"):
            cancel_reservation(res, reason="totaly_invented")

    def test_empty_reason_rejected(self, machine):
        res = PendingReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="wymagany"):
            cancel_reservation(res, reason="")

    def test_idempotent_path_does_not_require_reason(self, machine):
        """Already-cancelled — drugi call bez reason jest OK (idempotent)."""
        res = ConfirmedReservationFactory(machine=machine)
        cancel_reservation(res, reason="awaria")
        # Second call bez reason — nie powinno rzucić
        cancel_reservation(res)
        res.refresh_from_db()
        # Reason zachowany z pierwszego wywołania
        assert res.cancellation_reason == "awaria"

    def test_reason_field_choices_match_textchoices(self):
        """Snapshot: dropdown ma 5 wartości — chroni przed nieprzemyślaną zmianą."""
        values = [c[0] for c in Reservation.CancellationReason.choices]
        assert values == [
            "klient_zrezygnowal",
            "awaria",
            "zmiana_terminu",
            "brak_dostepnosci",
            "inne",
        ]


@pytest.mark.django_db
class TestCancelViewReason:
    """View-level — POST cancellation_reason + cancellation_note."""

    def test_view_accepts_reason_and_note(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.post(
            reverse("reservations:cancel", args=[res.pk]),
            data={
                "cancellation_reason": "awaria",
                "cancellation_note": "Hydraulika padła",
            },
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA
        assert res.cancellation_reason == "awaria"
        assert res.cancellation_note == "Hydraulika padła"

    def test_view_unknown_reason_redirects_with_flash(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.post(
            reverse("reservations:cancel", args=[res.pk]),
            data={"cancellation_reason": "made_up"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        # Status NIE zmieniony — service zablokował
        assert res.status == Reservation.Status.POTWIERDZONA


@pytest.mark.django_db
class TestCancellationReasonMigration:
    """Sanity: nowe pola są w DB i ma indeks."""

    def test_can_save_with_cancellation_reason(self, machine):
        """Field migrated correctly — można zapisać + odczytać."""
        res = ConfirmedReservationFactory(machine=machine)
        res.status = Reservation.Status.ANULOWANA
        res.cancellation_reason = "awaria"
        res.cancellation_note = "Z notatką"
        res.save()
        res.refresh_from_db()
        assert res.cancellation_reason == "awaria"
        assert res.cancellation_note == "Z notatką"

    def test_field_can_be_empty_for_non_cancelled(self, machine):
        """Pole blank=True — non-cancelled rezerwacje mają puste reason."""
        res = ConfirmedReservationFactory(machine=machine, start_date=date(2030, 1, 1))
        assert res.cancellation_reason == ""
        assert res.cancellation_note == ""
