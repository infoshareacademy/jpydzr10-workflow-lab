"""Testy serwisu ``report_breakdown`` — one-click flow "Zgłoś awarię" (B-1).

Pokrywa:

* happy path — rezerwacja zamykana dziś, maszyna do serwisu, ServiceRecord
  typu "naprawa" utworzony z opisem,
* atomic guard — zamknięta rezerwacja nie może zgłosić awarii,
* validation — opis za krótki rzuca ``ValidationError``,
* end_date trim — rezerwacja kończąca się w przyszłości jest skracana do dziś,
* end_date preserved — rezerwacja kończąca się w przeszłości NIE jest wydłużona,
* actor → ServiceRecord.performed_by — audit trail kto zgłosił.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import report_breakdown
from service.models import ServiceRecord


@pytest.fixture
def actor(db):
    user_model = get_user_model()
    return user_model.objects.create_user(
        username="zgloszeniowiec",
        password="secret-pw-123!",
        first_name="Maria",
        last_name="Magazynierka",
    )


@pytest.mark.django_db
class TestReportBreakdown:
    """Happy path + side-effects."""

    @freeze_time("2026-06-15")
    def test_happy_path_closes_reservation_and_starts_repair(self, machine, actor):
        """Confirmed reservation + future end_date → today, machine W_SERWISIE, record naprawa."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        result = report_breakdown(res, description="Silnik nie startuje", actor=actor)

        res.refresh_from_db()
        machine.refresh_from_db()

        assert res.status == Reservation.Status.ZAKONCZONA
        assert res.end_date == date(2026, 6, 15)
        assert machine.status == Machine.Status.W_SERWISIE

        record = ServiceRecord.objects.get(pk=result["service_record_id"])
        assert record.record_type == ServiceRecord.RecordType.NAPRAWA
        assert record.performed_date == date(2026, 6, 15)
        assert "Silnik nie startuje" in record.description
        assert f"#{res.pk}" in record.description
        assert record.performed_by == "Maria Magazynierka"

        assert result == {
            "reservation_id": res.pk,
            "machine_uid": machine.uid,
            "service_record_id": record.pk,
        }

    @freeze_time("2026-06-15")
    def test_works_for_pending_reservation_too(self, machine, actor):
        """Pending rezerwacja (jeszcze nie potwierdzona) też może mieć awarię."""
        res = PendingReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 16),
            end_date=date(2026, 6, 20),
        )
        report_breakdown(res, description="Silnik źle pracuje", actor=actor)

        res.refresh_from_db()
        machine.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert machine.status == Machine.Status.W_SERWISIE

    @freeze_time("2026-06-15")
    def test_end_date_not_extended_if_in_past(self, machine, actor):
        """Jeśli end_date już w przeszłości (overdue), nie wydłużamy — zostaje sprzed.

        To różnica od Hard Return Policy: tam wydłużamy, bo maszyna fizycznie
        jeszcze nie wróciła. Tu mamy awarię — fizycznie nadal jest u klienta,
        ale closing dniem dzisiejszym byłoby przedłużeniem przestoju. Polityka:
        ``end_date = min(current_end_date, today)`` — czyli zostaje sprzed
        jeśli już była w przeszłości.
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),  # past relative to today=2026-06-15
        )

        report_breakdown(res, description="Awaria silnika", actor=actor)

        res.refresh_from_db()
        assert res.end_date == date(2026, 6, 10)  # preserved (no extension)

    @freeze_time("2026-06-15")
    def test_actor_none_results_in_empty_performed_by(self, machine):
        """Brak actora (anonymous chatbot path?) → performed_by="" (puste OK)."""
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()

        result = report_breakdown(res, description="Awaria silnika", actor=None)

        record = ServiceRecord.objects.get(pk=result["service_record_id"])
        assert record.performed_by == ""

    @freeze_time("2026-06-15")
    def test_actor_without_full_name_uses_username(self, machine, db):
        """User bez first_name/last_name → fallback do username."""
        user_model = get_user_model()
        bare_user = user_model.objects.create_user(username="anonim", password="secret-pw-123!")
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()

        result = report_breakdown(res, description="Awaria silnika", actor=bare_user)

        record = ServiceRecord.objects.get(pk=result["service_record_id"])
        assert record.performed_by == "anonim"


@pytest.mark.django_db
class TestReportBreakdownGuards:
    """Validation + transition guards."""

    def test_completed_reservation_cannot_report(self, machine, actor):
        res = CompletedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="zamkniętej"):
            report_breakdown(res, description="Po fakcie", actor=actor)

    def test_cancelled_reservation_cannot_report(self, machine, actor):
        res = CancelledReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="zamkniętej"):
            report_breakdown(res, description="Po fakcie", actor=actor)

    def test_empty_description_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="5 znaków"):
            report_breakdown(res, description="", actor=actor)

    def test_too_short_description_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="5 znaków"):
            report_breakdown(res, description="hm", actor=actor)

    def test_whitespace_only_description_rejected(self, machine, actor):
        res = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="5 znaków"):
            report_breakdown(res, description="     ", actor=actor)

    def test_guard_failure_does_not_mutate_state(self, machine, actor):
        """Atomicity: gdy report_breakdown rzuca, NIC się nie zmienia."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(machine=machine)
        original_status = res.status
        original_machine_status = machine.status

        with pytest.raises(ValidationError):
            report_breakdown(res, description="zz", actor=actor)  # za krótki

        res.refresh_from_db()
        machine.refresh_from_db()
        assert res.status == original_status
        assert machine.status == original_machine_status
        assert not ServiceRecord.objects.filter(machine=machine).exists()


@pytest.mark.django_db
class TestReportBreakdownView:
    """Integration testy widoku — flash, redirect, perm guards."""

    def test_view_creates_service_record(self, client_logged, machine):
        """Integracja widoku — bez freeze_time (kolizja z session middleware).

        Service używa ``date.today()`` jako default — testujemy że flow
        side-effekty są poprawne dla dziś, niezależnie od konkretnej daty.
        """
        from django.urls import reverse

        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        # start_date / end_date w przyszłości żeby uniknąć past-date validation
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date.today(),
            end_date=date.today().replace(year=date.today().year + 1),
        )

        response = client_logged.post(
            reverse("reservations:report_breakdown", args=[res.pk]),
            data={"description": "Silnik zacina się przy starcie"},
        )

        assert response.status_code == 302
        assert response.url.endswith(f"/rezerwacje/{res.pk}/")

        res.refresh_from_db()
        machine.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA
        assert machine.status == Machine.Status.W_SERWISIE
        assert ServiceRecord.objects.filter(machine=machine, record_type="naprawa").exists()

    def test_view_rejects_empty_description(self, client_logged, machine):
        from django.urls import reverse

        res = ConfirmedReservationFactory(machine=machine)

        response = client_logged.post(
            reverse("reservations:report_breakdown", args=[res.pk]),
            data={"description": ""},
        )
        assert response.status_code == 302  # redirect z flash error
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA  # bez zmian

    def test_view_requires_permission(self, client_no_perms, machine):
        from django.urls import reverse

        res = ConfirmedReservationFactory(machine=machine)
        response = client_no_perms.post(
            reverse("reservations:report_breakdown", args=[res.pk]),
            data={"description": "abcdef"},
        )
        assert response.status_code == 403

    def test_view_requires_post(self, client_logged, machine):
        from django.urls import reverse

        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.get(reverse("reservations:report_breakdown", args=[res.pk]))
        assert response.status_code == 405  # method not allowed

    def test_view_404_for_missing_pk(self, client_logged):
        from django.urls import reverse

        response = client_logged.post(
            reverse("reservations:report_breakdown", args=[99999]),
            data={"description": "abcdef"},
        )
        assert response.status_code == 404
