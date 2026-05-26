"""Tests for the construction-site service helpers."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from reservations.factories import ConfirmedReservationFactory
from reservations.models import ConstructionSite
from reservations.services import create_site, delete_site, update_site


@pytest.mark.django_db
class TestCreateSite:
    def test_creates_with_valid_data(self):
        site = create_site(
            project_number="BUD-2026-099",
            name="Demo",
            address="ul. Demo 1",
            client_name="Klient SA",
        )
        assert site.pk is not None
        assert site.status == ConstructionSite.Status.AKTYWNA

    def test_rejects_invalid_project_number(self):
        with pytest.raises(ValidationError):
            create_site(project_number="123", name="X", address="Y")

    def test_rejects_duplicate_project_number(self):
        create_site(project_number="BUD-2026-100", name="X", address="Y")
        with pytest.raises(ValidationError):
            create_site(project_number="BUD-2026-100", name="X", address="Y")

    def test_rejects_end_before_start(self):
        with pytest.raises(ValidationError):
            create_site(
                project_number="BUD-2026-101",
                name="X",
                address="Y",
                start_date=date(2030, 6, 1),
                end_date=date(2030, 5, 1),
            )


@pytest.mark.django_db
class TestUpdateSite:
    def test_updates_allowed_fields(self, site):
        update_site(site, name="Nowa nazwa", city="Gdańsk")
        site.refresh_from_db()
        assert site.name == "Nowa nazwa"
        assert site.city == "Gdańsk"

    def test_ignores_project_number_in_update(self, site):
        original = site.project_number
        update_site(site, project_number="BUD-9999-999", name="x")
        site.refresh_from_db()
        assert site.project_number == original


@pytest.mark.django_db
class TestDeleteSite:
    def test_deletes_site_without_reservations(self, site):
        pk = site.pk
        delete_site(site)
        assert not ConstructionSite.objects.filter(pk=pk).exists()

    def test_refuses_with_active_reservations(self, site, machine):
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        with pytest.raises(ValidationError, match="aktywnych rezerwacji"):
            delete_site(site)
        assert ConstructionSite.objects.filter(pk=site.pk).exists()
