"""Tests for the form classes in :mod:`reservations.forms`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from freezegun import freeze_time

from reservations.forms import (
    ConstructionSiteForm,
    ReservationFilterForm,
    ReservationForm,
)
from reservations.models import ConstructionSite


@pytest.mark.django_db
class TestReservationForm:
    @freeze_time("2026-05-16")
    def test_valid_data_passes(self, machine):
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "Anna",
                # Wave 14-A Bundle 4 -- address + responsible_person required.
                "address": "Krakowska 123, Warszawa",
                "responsible_person": "Jan Kowalski",
                "notes": "",
            }
        )
        assert form.is_valid(), form.errors

    def test_end_before_start_fails(self, machine):
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": "2030-02-10",
                "end_date": "2030-02-01",
                "person": "Anna",
                "address": "Krakowska 123",
                "responsible_person": "Jan Kowalski",
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "end_date" in form.errors

    def test_required_fields(self):
        form = ReservationForm(data={})
        assert not form.is_valid()
        # Wave 14-A Bundle 4 -- address + responsible_person teraz required.
        for required in (
            "machine",
            "start_date",
            "end_date",
            "person",
            "address",
            "responsible_person",
        ):
            assert required in form.errors

    @freeze_time("2026-05-16")
    def test_address_blank_rejected(self, machine):
        """Wave 14-A Bundle 4: empty address na ReservationForm = invalid."""
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "Anna",
                "address": "",  # Pusty adres → blokada
                "responsible_person": "Jan Kowalski",
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "address" in form.errors

    @freeze_time("2026-05-16")
    def test_address_whitespace_rejected(self, machine):
        """Wave 14-A Bundle 4: same whitespace w address tez rejected."""
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "Anna",
                "address": "   ",  # Tylko spacje → invalid
                "responsible_person": "Jan Kowalski",
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "address" in form.errors

    @freeze_time("2026-05-16")
    def test_responsible_person_blank_rejected(self, machine):
        """Wave 14-A Bundle 4: empty responsible_person na ReservationForm = invalid."""
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "Anna",
                "address": "Krakowska 123",
                "responsible_person": "",  # Pusty → blokada
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "responsible_person" in form.errors

    @freeze_time("2026-05-16")
    def test_responsible_person_persisted_via_form(self, machine):
        """Wave 14-A Bundle 4: responsible_person zapisuje sie do modelu."""
        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "Anna",
                "address": "Krakowska 123",
                "responsible_person": "Brygadzista Marek",
                "notes": "",
            }
        )
        assert form.is_valid(), form.errors
        # cleaned_data zawiera responsible_person
        assert form.cleaned_data["responsible_person"] == "Brygadzista Marek"


@pytest.mark.django_db
class TestConstructionSiteForm:
    @pytest.mark.parametrize(
        "valid",
        ["BUD-2026-001", "BUD-9999-999"],
    )
    def test_accepts_valid_project_number(self, valid):
        form = ConstructionSiteForm(
            data={
                "project_number": valid,
                "name": "X",
                "client_name": "",
                "address": "Y",
                "city": "",
                "status": ConstructionSite.Status.AKTYWNA,
                "start_date": "",
                "end_date": "",
                "notes": "",
            }
        )
        assert form.is_valid(), form.errors

    @pytest.mark.parametrize(
        "bad",
        ["BUD-26-001", "123456789", "bud-2026-001", "", "BUD-2026-1"],
    )
    def test_rejects_invalid_project_number(self, bad):
        form = ConstructionSiteForm(
            data={
                "project_number": bad,
                "name": "X",
                "client_name": "",
                "address": "Y",
                "city": "",
                "status": ConstructionSite.Status.AKTYWNA,
                "start_date": "",
                "end_date": "",
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "project_number" in form.errors

    def test_project_number_disabled_when_editable_false(self, site):
        form = ConstructionSiteForm(instance=site, editable_project_number=False)
        assert form.fields["project_number"].disabled is True


@pytest.mark.django_db
class TestReservationFormQuerysetExclusions:
    """Wave 4 P0: WYCOFANA i W_SERWISIE są wykluczone z dropdownu maszyn."""

    def test_dropdown_excludes_wycofana_machines(self, machine):
        """Maszyna WYCOFANA z floty nie pojawia się w dropdownie rezerwacji."""
        from machines.models import Machine

        Machine.objects.create(
            uid="K-OLD",
            name="Sprzedana koparka",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.WYCOFANA,
        )
        form = ReservationForm()
        uids = list(form.fields["machine"].queryset.values_list("uid", flat=True))
        assert "K-OLD" not in uids
        assert machine.uid in uids  # dostępna maszyna nadal się pokazuje

    def test_dropdown_keeps_w_serwisie_excluded(self, machine):
        """W_SERWISIE też wykluczone (zachowanie istniejące, regression test)."""
        from machines.models import Machine

        Machine.objects.create(
            uid="K-SVC",
            name="W serwisie",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_SERWISIE,
        )
        form = ReservationForm()
        uids = list(form.fields["machine"].queryset.values_list("uid", flat=True))
        assert "K-SVC" not in uids


@pytest.mark.django_db
class TestReservationFilterForm:
    def test_empty_form_is_valid(self):
        form = ReservationFilterForm(data={})
        assert form.is_valid()
        # cleaned_data is all-empty (or None for ModelChoiceFields)
        assert form.cleaned_data.get("status") in ("", None)

    def test_status_value_accepted(self):
        form = ReservationFilterForm(data={"status": "potwierdzona"})
        assert form.is_valid()
        assert form.cleaned_data["status"] == "potwierdzona"

    def test_invalid_status_rejected(self):
        form = ReservationFilterForm(data={"status": "nope"})
        assert not form.is_valid()
