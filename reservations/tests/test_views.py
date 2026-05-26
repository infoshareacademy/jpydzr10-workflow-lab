"""Tests for the reservation views (CRUD + HTMX endpoints).

Coverage focuses on the contract — login required, redirect on success,
form errors render, conflict pre-check returns the right HTML/204 — not on
internal implementation details.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from reservations.factories import ConfirmedReservationFactory, PendingReservationFactory
from reservations.models import Reservation


@pytest.mark.django_db
class TestListView:
    def test_redirects_when_not_logged_in(self, client):
        response = client.get(reverse("reservations:list"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url or "/login/" in response.url

    def test_renders_list_for_logged_user(self, client_logged, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        response = client_logged.get(reverse("reservations:list"))
        assert response.status_code == 200
        assert b"Rezerwacje" in response.content

    def test_htmx_returns_partial(self, client_logged, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        response = client_logged.get(reverse("reservations:list"), HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        # Partial — no <header> from base.html.
        assert b"<header" not in response.content

    def test_status_filter_applied(self, client_logged, machine):
        PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 2, 1), end_date=date(2030, 2, 5)
        )
        response = client_logged.get(reverse("reservations:list"), {"status": "potwierdzona"})
        assert response.status_code == 200
        # `reservations` may be either a Page (when paginated) or a QuerySet
        # (single page); both expose len(...) reliably.
        assert len(response.context["reservations"]) == 1

    def test_search_filters_by_person(self, client_logged, machine):
        """F-5: ``?q=...`` użyje search() managera — przeszukuje person/notes/site."""
        ConfirmedReservationFactory(
            machine=machine,
            person="Anna Search Target",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            person="Bartek Other",
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        response = client_logged.get(reverse("reservations:list"), {"q": "Search Target"})
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1
        assert response.context["reservations"][0].person == "Anna Search Target"

    def test_search_filters_by_notes(self, client_logged, machine):
        """F-5: search() przeszukuje też notatki — globalny scope."""
        ConfirmedReservationFactory(
            machine=machine,
            person="X",
            notes="Awaria silnika hydraulicznego",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            person="Y",
            notes="Plan przeglądu",
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        response = client_logged.get(reverse("reservations:list"), {"q": "hydraulicznego"})
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1


@pytest.mark.django_db
class TestDetailView:
    def test_renders_existing_reservation(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.get(reverse("reservations:detail", args=[res.pk]))
        assert response.status_code == 200
        assert machine.uid.encode() in response.content

    def test_404_for_missing_reservation(self, client_logged):
        response = client_logged.get(reverse("reservations:detail", args=[99999]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestCreateView:
    def test_get_renders_form(self, client_logged):
        response = client_logged.get(reverse("reservations:create"))
        assert response.status_code == 200
        assert b"<form" in response.content

    @freeze_time("2026-05-16")
    def test_post_creates_reservation(self, client_logged, machine, site):
        start = date.today() + timedelta(days=5)
        end = start + timedelta(days=3)
        response = client_logged.post(
            reverse("reservations:create"),
            data={
                "machine": machine.pk,
                "site": site.pk,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "person": "Anna Test",
                # Wave 14-A Bundle 4 -- address + responsible_person wymagane.
                "address": "Polna 5, Krakow",
                "responsible_person": "Jan Kowalski",
                "notes": "",
            },
        )
        assert response.status_code == 302  # redirect to detail
        assert Reservation.objects.filter(machine=machine, start_date=start).exists()

    @freeze_time("2026-05-16")
    def test_post_with_conflict_renders_form_with_error(self, client_logged, machine):
        start = date.today() + timedelta(days=5)
        end = start + timedelta(days=3)
        ConfirmedReservationFactory(machine=machine, start_date=start, end_date=end)
        response = client_logged.post(
            reverse("reservations:create"),
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "person": "Anna",
                "address": "Polna 5, Krakow",
                "responsible_person": "Jan Kowalski",
                "notes": "",
            },
        )
        # Form re-renders with the conflict message attached as non-field error.
        assert response.status_code == 200
        assert b"koliduj" in response.content.lower() or b"kolid" in response.content


@pytest.mark.django_db
class TestStateTransitionViews:
    def test_confirm_view_promotes_status(self, client_logged, machine):
        res = PendingReservationFactory(machine=machine)
        response = client_logged.post(reverse("reservations:confirm", args=[res.pk]))
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA

    def test_cancel_view_cancels(self, client_logged, machine):
        """B-2: cancel view wymaga cancellation_reason w POST data."""
        res = PendingReservationFactory(machine=machine)
        response = client_logged.post(
            reverse("reservations:cancel", args=[res.pk]),
            data={"cancellation_reason": "klient_zrezygnowal"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA
        assert res.cancellation_reason == "klient_zrezygnowal"

    def test_cancel_view_rejects_missing_reason(self, client_logged, machine):
        """B-2: brak reason → flash error, brak transition."""
        res = PendingReservationFactory(machine=machine)
        response = client_logged.post(reverse("reservations:cancel", args=[res.pk]))
        assert response.status_code == 302  # redirect z flash
        res.refresh_from_db()
        assert res.status == Reservation.Status.OCZEKUJACA  # bez zmian

    def test_complete_view_completes(self, client_logged, machine):
        res = ConfirmedReservationFactory(machine=machine)
        response = client_logged.post(reverse("reservations:complete", args=[res.pk]))
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA


@pytest.mark.django_db
class TestCheckConflictView:
    def test_returns_204_when_no_conflict(self, client_logged, machine):
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-01",
                "end_date": "2030-01-05",
            },
        )
        assert response.status_code == 204

    def test_returns_html_when_conflict(self, client_logged, machine):
        ConfirmedReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 10)
        )
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-05",
                "end_date": "2030-01-08",
            },
        )
        assert response.status_code == 200
        assert b"Konflikt" in response.content

    def test_handles_bad_input_gracefully(self, client_logged):
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {"machine": "abc", "start_date": "nope", "end_date": "also-nope"},
        )
        assert response.status_code == 204


@pytest.mark.django_db
class TestSiteViews:
    def test_site_list_renders(self, client_logged, site):
        response = client_logged.get(reverse("reservations:site_list"))
        assert response.status_code == 200
        assert site.project_number.encode() in response.content

    def test_site_create_post(self, client_logged):
        response = client_logged.post(
            reverse("reservations:site_create"),
            data={
                "project_number": "BUD-2026-555",
                "name": "Testowa",
                "client_name": "",
                "address": "ul. Testowa 1",
                "city": "Warszawa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "",
            },
        )
        assert response.status_code == 302

    def test_site_inline_create_succeeds_without_status_field(self, client_logged):
        """Regression: inline modal renderuje tylko 5 pól (no status field).
        View MUSI wstrzyknąć default status=aktywna inaczej silent failure
        (form invalid + brak feedback do usera bo `status` errors nie
        renderowane w template).
        """
        from reservations.models import ConstructionSite

        response = client_logged.post(
            reverse("reservations:site_inline_create"),
            data={
                "project_number": "BUD-2026-999",
                "name": "Inline test",
                "client_name": "Acme",
                "address": "ul. Inline 1",
                "city": "Warszawa",
                # NIE wysyłamy status — symulacja inline modal payload
            },
        )
        assert response.status_code == 204, (
            f"Expected 204 No Content on success, got {response.status_code} "
            f"(silent validation failure regression?). Body head: {response.content[:200]!r}"
        )
        assert "HX-Trigger" in response.headers
        site = ConstructionSite.objects.get(project_number="BUD-2026-999")
        assert site.status == ConstructionSite.Status.AKTYWNA


# =============================================================================
# WAVE 14-A BUNDLE 2 + 3 — Timeline Modal Views
# =============================================================================


@pytest.mark.django_db
class TestReservationModalView:
    """Wave 14-A Bundle 2 — klik bar na timeline -> popup pelnej rezerwacji."""

    def test_modal_renders_for_existing_reservation(self, client_logged, machine):
        res = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        response = client_logged.get(reverse("reservations:modal", args=[res.pk]))
        assert response.status_code == 200
        # Partial template -- nie powinien zawierac base.html headera.
        assert b"<form" in response.content
        # ReservationForm reuse -- pola standardowe.
        assert b"start_date" in response.content
        assert b"end_date" in response.content
        # Modal header z numerem rezerwacji.
        assert f"#{res.pk}".encode() in response.content

    def test_modal_404_for_nonexistent(self, client_logged):
        response = client_logged.get(reverse("reservations:modal", args=[99999]))
        assert response.status_code == 404

    def test_modal_redirects_when_not_logged_in(self, client, machine):
        res = PendingReservationFactory(
            machine=machine, start_date=date(2030, 1, 1), end_date=date(2030, 1, 5)
        )
        response = client.get(reverse("reservations:modal", args=[res.pk]))
        assert response.status_code == 302


@pytest.mark.django_db
class TestReservationQuickModalView:
    """Wave 14-A Bundle 3 — klik pusty cell -> pelen ReservationForm modal z preselect."""

    def test_quick_modal_with_preselect(self, client_logged, machine):
        response = client_logged.get(
            reverse("reservations:quick_modal"),
            {"machine_uid": machine.uid, "day": "2030-06-05"},
        )
        assert response.status_code == 200
        # Modal w trybie "create" pokazuje "Nowa rezerwacja".
        assert b"Nowa rezerwacja" in response.content
        # Preselect machine_uid widoczny w headerze.
        assert machine.uid.encode("utf-8") in response.content

    def test_quick_modal_without_preselect_renders_blank_form(self, client_logged):
        response = client_logged.get(reverse("reservations:quick_modal"))
        assert response.status_code == 200
        assert b"<form" in response.content

    def test_quick_modal_invalid_machine_uid_does_not_crash(self, client_logged):
        """Wave 14-A Bundle 3: bogus machine_uid pomijany (initial pusty)."""
        response = client_logged.get(
            reverse("reservations:quick_modal"),
            {"machine_uid": "NIE-MA-TAKIEJ-999", "day": "2030-06-05"},
        )
        assert response.status_code == 200
        assert b"<form" in response.content

    def test_quick_modal_invalid_day_does_not_crash(self, client_logged, machine):
        """Wave 14-A Bundle 3: malformed day jest silently ignored (initial pusty)."""
        response = client_logged.get(
            reverse("reservations:quick_modal"),
            {"machine_uid": machine.uid, "day": "not-a-date"},
        )
        assert response.status_code == 200

    def test_quick_modal_redirects_when_not_logged_in(self, client):
        response = client.get(reverse("reservations:quick_modal"))
        assert response.status_code == 302
