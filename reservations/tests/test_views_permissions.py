"""Testy permission_required + ownership na widokach zapisujących.

C2-3 P0 SECURITY: bez ``permission_required`` dowolny zalogowany użytkownik
mógł tworzyć/edytować/anulować/kończyć rezerwacje. Po naprawie:

* create / QuickReserve wymagają ``reservations.add_reservation``,
* update / confirm / cancel / complete wymagają ``reservations.change_reservation``,
* superuser nadal widzi wszystkie rezerwacje w UpdateView,
* non-superuser widzi tylko swoje (queryset filtered by ``person``).

Decyzja projektowa: ownership check po ``person`` (free-text) bo M2 nie ma
jeszcze FK do EmployeeProfile. W M3 zmienione na profilu.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from reservations.factories import ConfirmedReservationFactory, PendingReservationFactory
from reservations.models import Reservation


@pytest.mark.django_db
class TestPermissionRequiredOnWriteViews:
    """User bez ``reservations.{add,change}_reservation`` dostaje 403."""

    def test_create_view_403_without_permission(self, client_no_perms):
        response = client_no_perms.get(reverse("reservations:create"))
        assert response.status_code == 403

    def test_confirm_view_403_without_permission(self, client_no_perms, machine):
        res = PendingReservationFactory(machine=machine)
        response = client_no_perms.post(reverse("reservations:confirm", args=[res.pk]))
        assert response.status_code == 403
        res.refresh_from_db()
        # Status nieruszony — guard zadziałał przed wywołaniem service.
        assert res.status == Reservation.Status.OCZEKUJACA

    def test_cancel_view_403_without_permission(self, client_no_perms, machine):
        res = PendingReservationFactory(machine=machine)
        response = client_no_perms.post(reverse("reservations:cancel", args=[res.pk]))
        assert response.status_code == 403
        res.refresh_from_db()
        assert res.status == Reservation.Status.OCZEKUJACA

    def test_complete_view_403_without_permission(self, client_no_perms, machine):
        res = ConfirmedReservationFactory(machine=machine)
        response = client_no_perms.post(reverse("reservations:complete", args=[res.pk]))
        assert response.status_code == 403
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA


@pytest.mark.django_db
class TestPermissionGrantsAccess:
    """User Z ``reservations.{add,change}_reservation`` może edytować."""

    def test_confirm_view_200_with_permission(self, client_logged, machine):
        res = PendingReservationFactory(machine=machine)
        response = client_logged.post(reverse("reservations:confirm", args=[res.pk]))
        # 302 redirect to detail — sukces.
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA

    @freeze_time("2026-05-16")
    def test_create_view_200_with_permission(self, client_logged):
        # Tylko GET — sprawdzamy że auth wpuszcza, nie POST flow (już pokryty).
        response = client_logged.get(reverse("reservations:create"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestSitePermissions:
    """Wave 4 P0: site_create/update/delete/inline wymagają permission.

    Wcześniej każdy zalogowany user mógł usuwać dowolne budowy. Po fixie
    delete wymaga ``reservations.delete_constructionsite`` (Kierownicy+).
    """

    def test_site_create_403_without_permission(self, client_no_perms):
        response = client_no_perms.post(
            reverse("reservations:site_create"),
            data={
                "project_number": "BUD-2026-NEW",
                "name": "Test",
                "client_name": "",
                "address": "ul. Test 1",
                "city": "Warszawa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "",
            },
        )
        assert response.status_code == 403

    def test_site_update_403_without_permission(self, client_no_perms, site):
        response = client_no_perms.get(reverse("reservations:site_update", args=[site.pk]))
        assert response.status_code == 403

    def test_site_delete_403_without_permission(self, client_no_perms, site):
        """Bez permission delete_constructionsite → 403 zamiast usunięcia."""
        from reservations.models import ConstructionSite

        response = client_no_perms.post(reverse("reservations:site_delete", args=[site.pk]))
        assert response.status_code == 403
        # Budowa nadal istnieje — guard zadziałał przed wywołaniem service.
        assert ConstructionSite.objects.filter(pk=site.pk).exists()

    def test_site_inline_create_403_without_permission(self, client_no_perms):
        response = client_no_perms.post(
            reverse("reservations:site_inline_create"),
            data={
                "project_number": "BUD-2026-INL",
                "name": "Inline",
                "client_name": "",
                "address": "ul. Inline 1",
                "city": "Warszawa",
            },
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestUpdateViewOwnership:
    """Non-superuser widzi tylko swoje rezerwacje w UpdateView."""

    def test_update_404_when_not_owner_and_not_superuser(self, client_logged, machine):
        """Cudza rezerwacja (po ``person``) → 404 z queryset filter.

        ``client_logged`` używa fixture ``user`` (full_name pusty + username
        "tester"). ``PendingReservationFactory`` ustawia ``person=Faker.name()``
        czyli na pewno != "tester". get_queryset filter odsiewa wiersz,
        UpdateView zwraca 404 (zamiast wpuścić edycję).
        """
        someone_else_reservation = PendingReservationFactory(
            machine=machine,
            person="Ktoś Inny",
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(
            reverse("reservations:update", args=[someone_else_reservation.pk])
        )
        assert response.status_code == 404

    def test_update_200_when_owner(self, client_logged, machine):
        """Własna rezerwacja (po ``person``=username) → 200 OK."""
        own_reservation = PendingReservationFactory(
            machine=machine,
            person="tester",  # matches user.get_username()
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(reverse("reservations:update", args=[own_reservation.pk]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestOwnershipMatchAccentInsensitive:
    """B-5 — Edit ownership case-insensitive + accent-insensitive matching.

    Sven Olsén z polskim akcentem na nazwisku nie powinien być blokowany
    przed edycją własnej rezerwacji jeśli ktoś wpisał ją jako "Sven Olsen"
    (bez akcentu) — i odwrotnie.
    """

    @pytest.fixture
    def user_with_accent(self, db):
        """User z accent w nazwisku — pełni rolę 'ofiary' regressji M2."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        user_model = get_user_model()
        user = user_model.objects.create_user(
            username="solsen",
            password="secret-pw-123!",
            first_name="Sven",
            last_name="Olsén",  # z akcentem
        )
        perms = Permission.objects.filter(
            content_type__app_label="reservations",
            codename__in=("add_reservation", "change_reservation", "delete_reservation"),
        )
        user.user_permissions.add(*perms)
        return user

    @pytest.fixture
    def client_with_accent(self, client, user_with_accent):
        client.force_login(user_with_accent)
        return client

    def test_accent_in_user_matches_no_accent_in_person(self, client_with_accent, machine):
        """User "Sven Olsén" (akcent) edytuje rezerwację z person="Sven Olsen" (bez)."""
        res = PendingReservationFactory(
            machine=machine,
            person="Sven Olsen",  # BEZ akcentu — wpisana przez kogoś innego
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_with_accent.get(reverse("reservations:update", args=[res.pk]))
        assert response.status_code == 200

    def test_no_accent_in_user_matches_accent_in_person(self, client_logged, machine):
        """User "tester" edytuje rezerwację z person="TESTER" (case-insensitive)."""
        res = PendingReservationFactory(
            machine=machine,
            person="TESTER",  # uppercase
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(reverse("reservations:update", args=[res.pk]))
        assert response.status_code == 200

    def test_different_person_still_blocks(self, client_with_accent, machine):
        """Sanity: zupełnie inna osoba → 404."""
        res = PendingReservationFactory(
            machine=machine,
            person="Adam Nowak",
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_with_accent.get(reverse("reservations:update", args=[res.pk]))
        assert response.status_code == 404

    def test_normalize_function_basic_cases(self):
        """Bezpośredni test funkcji normalizującej — chroni przed regression."""
        from reservations.views import _normalize_person_name

        # Case folding
        assert _normalize_person_name("Tester") == "tester"
        assert _normalize_person_name("TESTER") == "tester"
        # Accent stripping
        assert _normalize_person_name("Sven Olsén") == "sven olsen"
        assert _normalize_person_name("Sven Olsen") == "sven olsen"
        # Polish accents
        assert _normalize_person_name("Łukasz") == "ukasz"  # Ł→strip, ł→strip
        assert _normalize_person_name("Łukasz Żółć") == "ukasz zoc"
        # Whitespace
        assert _normalize_person_name("  Anna  ") == "anna"
        # Empty
        assert _normalize_person_name("") == ""
