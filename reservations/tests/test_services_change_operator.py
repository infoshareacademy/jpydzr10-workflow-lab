"""Testy serwisu ``change_operator`` — szybka zmiana osoby (B-4).

Pokrywa:

* happy path — pole ``person`` zostaje zmienione, audit przez simple-history,
* odrzucenie zamkniętych rezerwacji (ZAKONCZONA / ANULOWANA),
* walidacja: empty, whitespace-only, za krótkie, identyczne (case-insensitive),
* nie modyfikuje innych pól (maszyna, daty, status, budowa),
* history_user — ``actor`` zostaje zapisany w ``HistoricalReservation``,
* integracja widoku — POST + flash + redirect + perm guard.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import change_operator


@pytest.fixture
def actor(db):
    user_model = get_user_model()
    return user_model.objects.create_user(
        username="magazynierka",
        password="secret-pw-123!",
        first_name="Maria",
        last_name="Kowalska",
    )


@pytest.mark.django_db
class TestChangeOperatorHappy:
    """Happy path — pole ``person`` zmienione, reszta bez zmian."""

    def test_changes_person_on_confirmed_reservation(self, machine, actor):
        """Confirmed reservation z 'Tomek Nowak' → 'Sven Olsen'."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")

        returned = change_operator(res, new_person="Sven Olsen", actor=actor)

        res.refresh_from_db()
        assert res.person == "Sven Olsen"
        assert returned.pk == res.pk
        assert returned.person == "Sven Olsen"

    def test_changes_person_on_pending_reservation(self, machine, actor):
        """Pending reservation też pozwala na zmianę osoby."""
        res = PendingReservationFactory(machine=machine, person="Anna Kowalska")
        change_operator(res, new_person="Bartek Wójcik", actor=actor)
        res.refresh_from_db()
        assert res.person == "Bartek Wójcik"

    def test_strips_whitespace_around_name(self, machine, actor):
        """Whitespace na brzegach jest stripowany przed save."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")
        change_operator(res, new_person="   Sven Olsen   ", actor=actor)
        res.refresh_from_db()
        assert res.person == "Sven Olsen"

    def test_does_not_modify_other_fields(self, machine, site, actor):
        """Zmiana osoby NIE rusza maszyny/dat/statusu/budowy/notatek."""
        res = ConfirmedReservationFactory(
            machine=machine,
            site=site,
            person="Tomek Nowak",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
            address="Stara 123, Kraków",
            notes="Pilne",
        )
        original_machine_id = res.machine_id
        original_site_id = res.site_id
        original_status = res.status
        original_start = res.start_date
        original_end = res.end_date
        original_address = res.address
        original_notes = res.notes

        change_operator(res, new_person="Sven Olsen", actor=actor)
        res.refresh_from_db()

        assert res.machine_id == original_machine_id
        assert res.site_id == original_site_id
        assert res.status == original_status
        assert res.start_date == original_start
        assert res.end_date == original_end
        assert res.address == original_address
        assert res.notes == original_notes
        assert res.person == "Sven Olsen"

    def test_simple_history_captures_change(self, machine, actor):
        """django-simple-history zapisuje snapshot przy każdym save."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")
        initial_history_count = res.history.count()

        change_operator(res, new_person="Sven Olsen", actor=actor)
        res.refresh_from_db()

        # Co najmniej +1 nowy rekord historii (snapshot po zmianie).
        assert res.history.count() >= initial_history_count + 1
        # Najnowszy rekord historii zawiera nowe imię.
        latest = res.history.order_by("-history_date").first()
        assert latest.person == "Sven Olsen"

    def test_history_user_is_actor(self, machine, actor):
        """``_history_user`` hook zapisuje aktora w HistoricalReservation."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")

        change_operator(res, new_person="Sven Olsen", actor=actor)

        latest = res.history.order_by("-history_date").first()
        assert latest.history_user_id == actor.pk

    def test_no_actor_logs_system_path(self, machine):
        """Brak actora — service path nadal działa, history_user=NULL."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")

        change_operator(res, new_person="Sven Olsen", actor=None)

        res.refresh_from_db()
        assert res.person == "Sven Olsen"
        latest = res.history.order_by("-history_date").first()
        assert latest.history_user_id is None


@pytest.mark.django_db
class TestChangeOperatorGuards:
    """Validation + transition guards."""

    def test_completed_reservation_cannot_change(self, machine, actor):
        res = CompletedReservationFactory(machine=machine, person="Tomek")
        with pytest.raises(ValidationError, match="zamkniętej"):
            change_operator(res, new_person="Sven", actor=actor)

    def test_cancelled_reservation_cannot_change(self, machine, actor):
        res = CancelledReservationFactory(machine=machine, person="Tomek")
        with pytest.raises(ValidationError, match="zamkniętej"):
            change_operator(res, new_person="Sven", actor=actor)

    def test_empty_string_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")
        with pytest.raises(ValidationError, match="wymagana"):
            change_operator(res, new_person="", actor=actor)

    def test_whitespace_only_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")
        with pytest.raises(ValidationError, match="wymagana"):
            change_operator(res, new_person="     ", actor=actor)

    def test_too_short_rejected(self, machine, actor):
        """Single-char i 2-char wartości są odrzucane (literówki defence)."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        with pytest.raises(ValidationError, match="3 znaki"):
            change_operator(res, new_person="X", actor=actor)
        with pytest.raises(ValidationError, match="3 znaki"):
            change_operator(res, new_person="Xy", actor=actor)

    def test_identical_name_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        with pytest.raises(ValidationError, match="różnić"):
            change_operator(res, new_person="Tomek Nowak", actor=actor)

    def test_identical_name_case_insensitive_rejected(self, machine, actor):
        """Case-insensitive — 'tomek nowak' jest identyczne z 'Tomek Nowak'."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        with pytest.raises(ValidationError, match="różnić"):
            change_operator(res, new_person="tomek nowak", actor=actor)

    def test_identical_name_with_whitespace_rejected(self, machine, actor):
        """Whitespace strip — '  Tomek Nowak  ' jest identyczne z 'Tomek Nowak'."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        with pytest.raises(ValidationError, match="różnić"):
            change_operator(res, new_person="  Tomek Nowak  ", actor=actor)

    def test_failed_validation_does_not_mutate(self, machine, actor):
        """Atomicity — failed validation nie zostawia śladu w DB."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek")
        original_person = res.person
        initial_history = res.history.count()

        with pytest.raises(ValidationError):
            change_operator(res, new_person="", actor=actor)

        res.refresh_from_db()
        assert res.person == original_person
        assert res.history.count() == initial_history


@pytest.mark.django_db
class TestChangeOperatorView:
    """Integration testy widoku — POST + flash + redirect + perm."""

    def test_view_changes_person_and_redirects(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")

        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Sven Olsen"},
        )

        assert response.status_code == 302
        assert response.url.endswith(f"/rezerwacje/{res.pk}/")
        res.refresh_from_db()
        assert res.person == "Sven Olsen"

    def test_view_rejects_empty_with_flash(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")

        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": ""},
            follow=False,
        )

        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Tomek Nowak"  # bez zmian

    def test_view_rejects_too_short(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")

        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Sv"},
        )

        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Tomek Nowak"

    def test_view_rejects_identical_via_service(self, client_logged, machine):
        """Service-level guard — identyczne imię = flash error."""
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")

        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Tomek Nowak"},
        )

        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Tomek Nowak"

    def test_view_requires_permission(self, client_no_perms, machine):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        response = client_no_perms.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Sven Olsen"},
        )
        assert response.status_code == 403

    def test_view_requires_post(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine, person="Tomek Nowak")
        response = client_logged.get(reverse("reservations:change_operator", args=[res.pk]))
        assert response.status_code == 405

    def test_view_404_for_missing_pk(self, client_logged):
        response = client_logged.post(
            reverse("reservations:change_operator", args=[99999]),
            data={"new_person": "Sven Olsen"},
        )
        assert response.status_code == 404

    def test_view_rejects_closed_reservation(self, client_logged, machine):
        res = CompletedReservationFactory(machine=machine, person="Tomek Nowak")

        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Sven Olsen"},
        )

        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Tomek Nowak"  # bez zmian
        assert res.status == Reservation.Status.ZAKONCZONA
