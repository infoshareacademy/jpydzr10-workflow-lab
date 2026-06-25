"""Testy permission_required + ownership na widokach zapisujących.

C2-3 P0 SECURITY: bez ``permission_required`` dowolny zalogowany użytkownik
mógł tworzyć/edytować/anulować/kończyć rezerwacje. Po naprawie:

* create / QuickReserve wymagają ``reservations.add_reservation``,
* update / confirm / cancel / complete wymagają ``reservations.change_reservation``,
* superuser nadal widzi wszystkie rezerwacje w UpdateView,
* non-superuser widzi tylko swoje (queryset filtered by ``created_by``).

Decyzja projektowa: ownership check po FK ``created_by`` (User) — jednoznaczne
przypisanie zamiast dawnego dopasowania po free-text ``person``.
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

    def test_site_delete_with_permission_removes_site(self, client_logged, site):
        """User Z ``delete_constructionsite`` faktycznie usuwa budowę (302 + zniknięcie).

        Pozytywny kontrapunkt do testu 403: gwarantuje, że ``permission_required``
        egzekwuje WŁAŚCIWE uprawnienie (a nie tylko że jakikolwiek guard istnieje)
        — i że ścieżka usuwania działa, gdy uprawnienie jest nadane.
        """
        from reservations.models import ConstructionSite

        pk = site.pk
        response = client_logged.post(reverse("reservations:site_delete", args=[pk]))
        assert response.status_code == 302
        assert not ConstructionSite.objects.filter(pk=pk).exists()

    def test_site_create_with_permission_creates_site(self, client_logged):
        """User Z ``add_constructionsite`` tworzy budowę (302 + obiekt w bazie)."""
        from reservations.models import ConstructionSite

        project_number = "BUD-2099-777"
        assert not ConstructionSite.objects.filter(project_number=project_number).exists()
        response = client_logged.post(
            reverse("reservations:site_create"),
            data={
                "project_number": project_number,
                "name": "Budowa OK",
                "client_name": "",
                "address": "ul. Pozytywna 7",
                "city": "Warszawa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "",
            },
        )
        assert response.status_code == 302
        assert ConstructionSite.objects.filter(project_number=project_number).exists()


@pytest.mark.django_db
class TestUpdateViewOwnership:
    """Non-superuser widzi i edytuje tylko rezerwacje, które sam utworzył (FK
    ``created_by``)."""

    def test_update_404_when_not_owner_and_not_superuser(self, client_logged, machine):
        """Rezerwacja utworzona przez kogoś innego → 404 z queryset filter."""
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(username="ktos-inny", password="x")
        someone_else_reservation = PendingReservationFactory(
            machine=machine,
            created_by=other,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(
            reverse("reservations:update", args=[someone_else_reservation.pk])
        )
        assert response.status_code == 404

    def test_update_404_when_created_by_null(self, client_logged, machine):
        """Rezerwacja bez ``created_by`` (import/historia) → 404 dla nie-superusera."""
        orphan = PendingReservationFactory(
            machine=machine,
            created_by=None,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(reverse("reservations:update", args=[orphan.pk]))
        assert response.status_code == 404

    def test_update_200_when_owner(self, client_logged, user, machine):
        """Własna rezerwacja (``created_by`` == zalogowany user) → 200 OK."""
        own_reservation = PendingReservationFactory(
            machine=machine,
            created_by=user,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client_logged.get(reverse("reservations:update", args=[own_reservation.pk]))
        assert response.status_code == 200
