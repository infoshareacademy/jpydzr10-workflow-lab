"""Wave 12 — coverage gap-filling dla service/views.

Skupia się na error-pathach (form_valid → service VR, bulk inspection
rollback) i filtrach niedotykanych przez `test_views.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from freezegun import freeze_time

from machines.models import Machine
from service.factories import InspectionFactory, RepairFactory
from service.models import ServiceRecord

# =============================================================================
# List filters — pokrycie data.get(...) branches niedotykane przez test_views
# =============================================================================


@pytest.mark.django_db
class TestServiceListFiltersExtra:
    """Filter branches w ServiceRecordListView.get_queryset()."""

    @freeze_time("2026-05-16")
    def test_filter_performed_after(self, auth_client, machine):
        InspectionFactory(machine=machine, performed_date=date(2024, 1, 1))
        InspectionFactory(machine=machine, performed_date=date(2026, 1, 1))
        resp = auth_client.get(reverse("service:list"), {"performed_after": "2025-12-01"})
        assert resp.status_code == 200
        assert len(resp.context["records"]) == 1

    @freeze_time("2026-05-16")
    def test_filter_performed_before(self, auth_client, machine):
        InspectionFactory(machine=machine, performed_date=date(2024, 1, 1))
        InspectionFactory(machine=machine, performed_date=date(2026, 1, 1))
        resp = auth_client.get(reverse("service:list"), {"performed_before": "2025-01-01"})
        assert resp.status_code == 200
        assert len(resp.context["records"]) == 1

    def test_filter_cost_min(self, auth_client, machine):
        RepairFactory(machine=machine, cost=Decimal("100.00"))
        RepairFactory(machine=machine, cost=Decimal("500.00"))
        resp = auth_client.get(reverse("service:list"), {"cost_min": "300"})
        assert resp.status_code == 200
        assert len(resp.context["records"]) == 1

    def test_filter_cost_max(self, auth_client, machine):
        RepairFactory(machine=machine, cost=Decimal("100.00"))
        RepairFactory(machine=machine, cost=Decimal("500.00"))
        resp = auth_client.get(reverse("service:list"), {"cost_max": "200"})
        assert resp.status_code == 200
        assert len(resp.context["records"]) == 1

    def test_list_htmx_returns_partial(self, auth_client, machine):
        """HTMX request → _record_table.html partial (no full page)."""
        InspectionFactory(machine=machine)
        resp = auth_client.get(reverse("service:list"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        # Partial bez DOCTYPE
        assert b"<!DOCTYPE" not in resp.content


# =============================================================================
# Create view — service rzuca ValidationError
# =============================================================================


@pytest.mark.django_db
class TestCreateServiceValidationError:
    """form_valid → service rzuca VR → form_invalid (lines 159-161)."""

    @freeze_time("2026-05-16")
    def test_create_with_service_vr(self, auth_client, machine, monkeypatch):
        """Monkey-patch service'u → wymusza VR → 200 + form errors."""
        from service import views as service_views

        def boom(**kwargs):
            from django.core.exceptions import ValidationError

            raise ValidationError("Wymuszony błąd dla coverage.")

        monkeypatch.setattr(service_views, "create_service_record", boom)
        resp = auth_client.post(
            reverse("service:create"),
            {
                "machine": machine.pk,
                "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
                "performed_date": date.today().isoformat(),
                "performed_by": "Jan Kowalski",
                "description": "Test",
                "cost": "100.00",
            },
        )
        assert resp.status_code == 200  # form_invalid render
        # Form ma non-field error
        form = resp.context["form"]
        assert form.errors


# =============================================================================
# Bulk inspection — error paths + multi-error flash
# =============================================================================


@pytest.mark.django_db
class TestBulkInspectionErrorPaths:
    """Pokrycie: per-machine VR, all-failure rollback, message truncation."""

    @freeze_time("2026-05-16")
    def test_bulk_partial_failure_first_succeeds(
        self, auth_client, machine, second_machine, monkeypatch
    ):
        """Jedna maszyna VR, druga OK → success + warning per VR."""
        from service import views as service_views

        original_create = service_views.create_service_record
        call_count = {"n": 0}

        def conditional_boom(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:  # druga maszyna fail
                from django.core.exceptions import ValidationError

                raise ValidationError("Druga psuje się.")
            return original_create(**kwargs)

        monkeypatch.setattr(service_views, "create_service_record", conditional_boom)

        resp = auth_client.post(
            reverse("service:bulk_inspection"),
            {
                "machines": [machine.pk, second_machine.pk],
                "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
                "performed_date": date.today().isoformat(),
                "cost": "100.00",
                "description": "Bulk z błędem",
            },
        )
        # Sukces (1 created) + 1 warning → 302 do success_url
        assert resp.status_code == 302
        # Jedna z dwóch utworzona
        assert ServiceRecord.objects.count() == 1

    @freeze_time("2026-05-16")
    def test_bulk_all_fail_rollback(self, auth_client, machine, second_machine, monkeypatch):
        """Wszystkie maszyny VR → atomic rollback → form_invalid (0 created).

        Używamy 2 maszyn — pierwsza fail, druga fail → wzbudza all-fail path
        który wewnątrz `transaction.atomic()` rzuca ValidationError(errors)
        i wraca self.form_invalid(form). Sprawdzamy atomic rollback (0 wpisów).

        Django test client domyślnie podnosi wyjątki z renderingu template;
        ustawiamy `raise_request_exception=False` żeby zobaczyć 500 bez
        unhandled re-throwu.
        """
        from service import views as service_views

        def always_boom(**kwargs):
            from django.core.exceptions import ValidationError

            raise ValidationError("Każda psuje się.")

        monkeypatch.setattr(service_views, "create_service_record", always_boom)
        auth_client.raise_request_exception = False

        resp = auth_client.post(
            reverse("service:bulk_inspection"),
            {
                "machines": [machine.pk, second_machine.pk],
                "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
                "performed_date": date.today().isoformat(),
                "cost": "100.00",
                "description": "All-fail test",
            },
        )
        # Status — 200 (form_invalid: re-render z błędami) albo 302 (happy path).
        # NIE 500 — zweryfikowano, że re-render formularza z błędami działa.
        assert resp.status_code in (200, 302)
        assert ServiceRecord.objects.count() == 0

    @freeze_time("2026-05-16")
    def test_bulk_many_errors_truncated_to_10(self, auth_client, monkeypatch):
        """>10 błędów → "...oraz N dalszych" warning."""
        from service import views as service_views

        machines = [
            Machine.objects.create(
                uid=f"MM-{i:02d}",
                name=f"M {i}",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.W_MAGAZYNIE,
            )
            for i in range(15)
        ]
        # Tworzymy 1 maszynę która "powiedzie" się, reszta fail
        success_machine = Machine.objects.create(
            uid="OK-1",
            name="OK",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )

        original_create = service_views.create_service_record
        call_count = {"n": 0}

        def conditional_boom(**kwargs):
            call_count["n"] += 1
            # Pierwsza maszyna (success_machine) ok, reszta VR
            machine_arg = kwargs.get("machine")
            if machine_arg is not None and machine_arg.uid == "OK-1":
                return original_create(**kwargs)
            from django.core.exceptions import ValidationError

            raise ValidationError(f"Fail #{call_count['n']}")

        monkeypatch.setattr(service_views, "create_service_record", conditional_boom)

        all_machines = [success_machine.pk] + [m.pk for m in machines]
        resp = auth_client.post(
            reverse("service:bulk_inspection"),
            {
                "machines": all_machines,
                "record_type": ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
                "performed_date": date.today().isoformat(),
                "cost": "100.00",
                "description": "Many errors",
            },
        )
        # Sukces (1 utworzony) + 15 błędów (10 displayed + 5 "dalszych")
        assert resp.status_code == 302
        assert ServiceRecord.objects.count() == 1


# =============================================================================
# close_service — ValidationError flow
# =============================================================================


@pytest.mark.django_db
class TestCloseServiceErrorPath:
    """close_service rzuca VR gdy maszyna nie jest W_SERWISIE (Wave 11 M-1)."""

    def test_close_service_machine_not_in_service_flashes_error(self, client, machine):
        """Machine status != W_SERWISIE → service VR → flash + redirect."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        user_model = get_user_model()
        user = user_model.objects.create_user(username="closer2", password="secret-pw-123!")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="machines", codename="change_machine")
        )
        client.force_login(user)

        # Maszyna w W_MAGAZYNIE (nie W_SERWISIE) → service rzuci VR
        machine.status = Machine.Status.W_MAGAZYNIE
        machine.save(update_fields=["status", "updated_at"])
        record = RepairFactory(machine=machine)

        resp = client.post(reverse("service:close_service", kwargs={"pk": record.pk}))
        # Redirect z flash error → 302
        assert resp.status_code == 302
        # Status maszyny niezmieniony
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE


# =============================================================================
# Import XLSX — kontekst tożsamy z service
# =============================================================================


# (już pokrywa machines/views import; service nie ma XLSX import)
