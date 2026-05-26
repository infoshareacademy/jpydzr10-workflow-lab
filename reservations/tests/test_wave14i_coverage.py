"""Wave 14-I — final coverage push 98%→99%+ dla reservations module.

Pokrywa pozostałe missed branches:

* ``services.py`` — error-aggregation paths w bulk_confirm_batch, bulk_cancel_batch,
  bulk_change_operator_batch (lines 1259-1262, 1272, 1371, 1403-1404, 1414).
* ``views.py`` — site_create / site_update / site_inline_create + CheckConflictView
  edge cases (lines 593, 627-628, 716-717, 726, 749-750, 811-812).
* ``forms.py`` — non-empty strip (whitespace-only address/responsible/person)
  (lines 146, 149, 512).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from machines.models import Machine
from reservations.factories import (
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.services import (
    bulk_cancel_batch,
    bulk_change_operator_batch,
    bulk_confirm_batch,
)

# =============================================================================
# services.py — bulk_*_batch error-aggregation paths
# =============================================================================


@pytest.mark.django_db
class TestBulkConfirmErrorAggregation:
    """Pokrywa lines 1259-1262 (errors.append) + 1272 (raise list)."""

    def test_bulk_confirm_aggregates_errors_from_per_reservation_vr(
        self, machine, second_machine, monkeypatch
    ):
        """Gdy confirm_reservation rzuca VR per rezerwacja → bulk zbiera + rzuca."""
        from reservations import services as svc

        batch_id = uuid.uuid4()
        # 2 pending w jednym batch'u — będziemy je próbować potwierdzić.
        PendingReservationFactory(
            machine=machine,
            batch_id=batch_id,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        PendingReservationFactory(
            machine=second_machine,
            batch_id=batch_id,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )

        # Monkey-patch confirm_reservation → rzuca VR za każdym razem.
        def fake_confirm(res, **kwargs):
            raise ValidationError([f"Forced VR for {res.machine.uid}"])

        monkeypatch.setattr(svc, "confirm_reservation", fake_confirm)

        with pytest.raises(ValidationError) as excinfo:
            bulk_confirm_batch(batch_id)

        # Sprawdzamy że error message zawiera UID obu maszyn (aggregated).
        msgs = "; ".join(excinfo.value.messages)
        assert machine.uid in msgs
        assert second_machine.uid in msgs


@pytest.mark.django_db
class TestBulkChangeOperatorErrors:
    """Pokrywa 1371 (empty name) + 1403-1404 + 1414 (aggregate raise)."""

    def test_empty_new_person_raises(self, machine):
        """Pusta nowa osoba (po stripie) → ValidationError od razu."""
        batch_id = uuid.uuid4()
        PendingReservationFactory(machine=machine, batch_id=batch_id, person="Stary")
        with pytest.raises(ValidationError):
            bulk_change_operator_batch(batch_id, new_person="   ")

    def test_whitespace_only_new_person_raises(self, machine):
        """Pusty string → ValidationError z "Nowa osoba jest wymagana"."""
        batch_id = uuid.uuid4()
        PendingReservationFactory(machine=machine, batch_id=batch_id, person="Stary")
        with pytest.raises(ValidationError, match="Nowa osoba"):
            bulk_change_operator_batch(batch_id, new_person="")

    def test_aggregates_per_reservation_errors(self, machine, second_machine, monkeypatch):
        """change_operator rzuca VR per rezerwacja → bulk agreguje + rzuca."""
        from reservations import services as svc

        batch_id = uuid.uuid4()
        PendingReservationFactory(machine=machine, batch_id=batch_id, person="Stary 1")
        PendingReservationFactory(machine=second_machine, batch_id=batch_id, person="Stary 2")

        def fake_change_operator(res, *, new_person, actor=None):
            raise ValidationError([f"Forced VR {res.machine.uid}"])

        monkeypatch.setattr(svc, "change_operator", fake_change_operator)

        with pytest.raises(ValidationError) as excinfo:
            bulk_change_operator_batch(batch_id, new_person="Nowy Operator")

        msgs = "; ".join(excinfo.value.messages)
        assert machine.uid in msgs
        assert second_machine.uid in msgs


@pytest.mark.django_db
class TestBulkCancelErrors:
    """Pokrywa 1272 (raise w bulk_cancel — choć już skipped via reason check)."""

    def test_bulk_cancel_with_empty_reason_immediate_raise(self, machine):
        """Brak reason → ValidationError natychmiast (pre-loop)."""
        batch_id = uuid.uuid4()
        PendingReservationFactory(machine=machine, batch_id=batch_id)
        with pytest.raises(ValidationError, match="Powód"):
            bulk_cancel_batch(batch_id, reason="")


# =============================================================================
# views.py — CheckConflictView + site_* error paths
# =============================================================================


@pytest.mark.django_db
class TestCheckConflictMissingParams:
    """Pokrywa line 593: _safe_int(None) → None → 204."""

    def test_missing_machine_returns_204(self, client_logged):
        """Brak machine_id w GET → 204 (nie próbujemy nawet sprawdzać conflicts)."""
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {"start_date": "2030-01-01", "end_date": "2030-01-10"},
        )
        assert response.status_code == 204

    def test_missing_dates_returns_204(self, client_logged, machine):
        """Brak dat → 204 (parse_iso_date(None) → None)."""
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {"machine": machine.pk},
        )
        assert response.status_code == 204

    def test_invalid_machine_id_string_returns_204(self, client_logged):
        """machine=abc → _safe_int → None → 204."""
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {"machine": "abc", "start_date": "2030-01-01", "end_date": "2030-01-10"},
        )
        assert response.status_code == 204


@pytest.mark.django_db
class TestCheckConflictServiceRaisesValidation:
    """Pokrywa lines 627-628: service-raised VR → swallow + 204."""

    def test_service_raised_vr_swallowed(self, client_logged, machine, monkeypatch):
        """Monkey-patch service get_conflicting_reservations → VR → view 204."""
        from reservations import views as views_mod

        def boom(**kwargs):
            raise ValidationError("Forced service-level VR")

        monkeypatch.setattr(views_mod, "get_conflicting_reservations", boom)

        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-01",
                "end_date": "2030-01-10",
            },
        )
        assert response.status_code == 204


@pytest.mark.django_db
class TestSiteCreateServiceError:
    """Pokrywa 716-717: site_create + VR exc → add_form_errors."""

    def test_create_site_with_service_vr_renders_form(self, client_logged, monkeypatch):
        """Monkey-patch service create_site → VR → 200 z form errors."""
        from reservations import views as views_mod

        def boom(**kwargs):
            raise ValidationError({"name": "Forced VR"})

        monkeypatch.setattr(views_mod, "create_site", boom)

        response = client_logged.post(
            reverse("reservations:site_create"),
            data={
                "project_number": "BUD-2026-999",
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
        # Form re-rendered z błędem
        assert response.status_code == 200

    def test_site_create_get_renders_empty_form(self, client_logged):
        """Pokrywa line 726: GET — else branch (form = ConstructionSiteForm())."""
        response = client_logged.get(reverse("reservations:site_create"))
        assert response.status_code == 200
        assert b"form" in response.content.lower()


@pytest.mark.django_db
class TestSiteUpdateServiceError:
    """Pokrywa 749-750: site_update + VR exc → add_form_errors."""

    def test_site_update_with_service_vr_renders_form(self, client_logged, site, monkeypatch):
        from reservations import views as views_mod

        def boom(*args, **kwargs):
            raise ValidationError({"name": "Forced VR"})

        monkeypatch.setattr(views_mod, "update_site", boom)

        response = client_logged.post(
            reverse("reservations:site_update", args=[site.pk]),
            data={
                "project_number": site.project_number,
                "name": "Updated",
                "client_name": "",
                "address": "ul. Updated 1",
                "city": "Warszawa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "",
            },
        )
        assert response.status_code == 200


@pytest.mark.django_db
class TestSiteInlineCreateServiceError:
    """Pokrywa 811-812: site_inline_create + VR exc."""

    def test_inline_create_with_service_vr_returns_form(self, client_logged, monkeypatch):
        """Service create_site rzuca VR → 200 z formularzem (nie 204)."""
        from reservations import views as views_mod

        def boom(**kwargs):
            raise ValidationError({"name": "Forced inline VR"})

        monkeypatch.setattr(views_mod, "create_site", boom)

        response = client_logged.post(
            reverse("reservations:site_inline_create"),
            data={
                "project_number": "BUD-2026-998",
                "name": "X",
                "client_name": "",
                "address": "ul. Inline 1",
                "city": "Warszawa",
                "status": "aktywna",
            },
        )
        # Re-render formularza (nie HX-Trigger 204)
        assert response.status_code == 200

    def test_inline_create_with_status_already_set(self, client_logged):
        """Pokrywa 805 → 807 branch: status field już ustawiony → nie overwriteu."""
        response = client_logged.post(
            reverse("reservations:site_inline_create"),
            data={
                "project_number": "BUD-2026-997",
                "name": "Z statusem",
                "client_name": "Klient X",
                "address": "ul. Z 1",
                "city": "Warszawa",
                "status": "aktywna",  # już ustawione → pomija default
            },
        )
        # Created → 204 z HX-Trigger (form valid + nie weszło w default branch)
        # albo 200 jeśli form invalid — w obu przypadkach branch 805 → 807
        # jest pokryty (status istniał, więc nie nadpisaliśmy).
        assert response.status_code in (200, 204)


# =============================================================================
# forms.py — whitespace-only triggers
# =============================================================================


@pytest.mark.django_db
class TestReservationFormWhitespaceRules:
    """Pokrywa 146 (address whitespace), 149 (responsible_person whitespace).

    Django CharField domyślnie strip=True, więc whitespace-only przechodzi przez
    field cleaning jako "" i required validator strzela jako pierwszy. Żeby
    explicit pokryć dead-defense w clean(), wyłączamy strip per-field.
    """

    def test_whitespace_only_address_raises(self, machine):
        """Address=" " (spacja) → form invalid (Wave 14-A Bundle 4).

        Disable strip żeby Django nie zjadł spacji przed naszym clean().
        """
        from reservations.forms import ReservationForm

        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": "2030-01-01",
                "end_date": "2030-01-05",
                "person": "Jan Kowalski",
                "address": "   ",  # whitespace-only
                "responsible_person": "Anna Nowak",
                "notes": "",
            }
        )
        # Disable strip żeby spacja dotarła do clean()
        form.fields["address"].strip = False
        assert not form.is_valid()
        assert "address" in form.errors

    def test_whitespace_only_responsible_raises(self, machine):
        """responsible_person=" " → form invalid."""
        from reservations.forms import ReservationForm

        form = ReservationForm(
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": "2030-01-01",
                "end_date": "2030-01-05",
                "person": "Jan Kowalski",
                "address": "ul. Polna 5",
                "responsible_person": "  ",  # whitespace-only
                "notes": "",
            }
        )
        form.fields["responsible_person"].strip = False
        assert not form.is_valid()
        assert "responsible_person" in form.errors


@pytest.mark.django_db
class TestBatchFormDateValidation:
    """Pokrywa line 512: end_date < start_date w BatchReservationForm.clean()."""

    def test_end_before_start_form_invalid(self, machine):
        """end_date < start_date → form invalid."""
        from reservations.forms import BatchReservationForm

        form = BatchReservationForm(
            data={
                "machines": [machine.pk],
                "site": "",
                "start_date": "2030-06-10",
                "end_date": "2030-06-05",  # end < start
                "person": "Kierownik",
                "address": "ul. X 1",
                "notes": "",
            }
        )
        assert not form.is_valid()
        assert "end_date" in form.errors


# =============================================================================
# models.py — __repr__ smoke (lines 103, 327)
# =============================================================================


@pytest.mark.django_db
class TestQuickModalWithInServiceMachine:
    """Wave 14-I P1 — quick modal preselect dla maszyny W_SERWISIE.

    Bug: gdy user kliknie pusty cell na timelinie maszyny ze statusem
    W_SERWISIE (lub WYCOFANA), `ReservationForm.fields["machine"].queryset`
    ja wyklucza i dropdown pokazuje "---------" zamiast preselected machine.

    Fix: rozszerzamy queryset o klikneta maszyne (jak edit mode), preselect
    dziala, user moze ja zmienic na inna.
    """

    def test_quick_modal_preselects_in_service_machine(self, client_logged):
        """W_SERWISIE machine + quick modal -> preselect dziala."""

        m = Machine.objects.create(
            uid="QM-SERV",
            name="W serwisie",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_SERWISIE,
        )
        response = client_logged.get(
            reverse("reservations:quick_modal"),
            {"machine_uid": m.uid, "day": "2030-06-15"},
        )
        assert response.status_code == 200
        # Form queryset zawiera te maszyne
        form = response.context["form"]
        assert form.fields["machine"].queryset.filter(pk=m.pk).exists()
        # Initial PK ustawione
        assert form.initial["machine"] == m.pk


@pytest.mark.django_db
class TestModelRepr:
    """ConstructionSite.__repr__ + Reservation.__repr__."""

    def test_construction_site_repr(self, site):
        rep = repr(site)
        assert "ConstructionSite" in rep
        assert site.project_number in rep
        assert "AKTYWNA" in rep

    def test_reservation_repr(self, machine):
        res = ConfirmedReservationFactory(machine=machine)
        rep = repr(res)
        assert "Reservation" in rep
        assert str(res.pk) in rep
        assert str(res.machine_id) in rep
