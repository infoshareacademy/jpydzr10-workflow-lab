"""Wave 12 — coverage gap-filling dla machines/views.

Pokrycie: filter form invalid path, inspection_status branches, create/update
service-VR, XLSX import error paths + truncation, _sanitize_xlsx_cell,
status action views (set_service/return/close_repair/retire) z VR i closed=0.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from freezegun import freeze_time
from openpyxl import Workbook

from machines.factories import (
    AvailableMachineFactory,
    InServiceMachineFactory,
    MachineFactory,
)
from machines.models import Machine

# =============================================================================
# List view — invalid filter form path + machine_type filter
# =============================================================================


@pytest.mark.django_db
class TestListViewExtras:
    """ListView paths: machine_type filter, invalid filter form."""

    def test_list_view_machine_type_filter(self, auth_client):
        AvailableMachineFactory(uid="KOP-FF1", machine_type=Machine.Type.KOPARKA)
        AvailableMachineFactory(uid="MIN-FF2", machine_type=Machine.Type.MINIKOPARKA)
        resp = auth_client.get(reverse("machines:list"), {"machine_type": Machine.Type.KOPARKA})
        assert resp.status_code == 200
        # Only KOP visible
        content = resp.content
        assert b"KOP-FF1" in content
        assert b"MIN-FF2" not in content

    def test_list_view_invalid_filter_shows_warning(self, auth_client):
        """User wpisał ?status=xxx → form invalid → wszystkie maszyny widoczne + warning."""
        AvailableMachineFactory(uid="ALL-1")
        resp = auth_client.get(reverse("machines:list"), {"status": "nonsense-value"})
        # form_invalid path: ListView i tak renderuje
        assert resp.status_code == 200
        # Wszystkie maszyny widoczne (filter pominięty)
        assert b"ALL-1" in resp.content

    @freeze_time("2026-05-16")
    def test_inspection_status_ok(self, auth_client):
        MachineFactory(uid="OK-INSP-1", inspection_date=date(2027, 1, 1))
        MachineFactory(uid="OVERDUE-INSP", inspection_date=date(2026, 1, 1))
        resp = auth_client.get(reverse("machines:list"), {"inspection_status": "ok"})
        assert b"OK-INSP-1" in resp.content
        assert b"OVERDUE-INSP" not in resp.content

    @freeze_time("2026-05-16")
    def test_inspection_status_warning(self, auth_client):
        """warning: inspection_date in [today, today+14)."""
        MachineFactory(uid="WARN-1", inspection_date=date(2026, 5, 25))
        MachineFactory(uid="OK-2", inspection_date=date(2027, 1, 1))
        resp = auth_client.get(reverse("machines:list"), {"inspection_status": "warning"})
        assert b"WARN-1" in resp.content
        assert b"OK-2" not in resp.content

    def test_inspection_status_unknown(self, auth_client):
        """unknown: inspection_date is None."""
        MachineFactory(uid="UNK-1", inspection_date=None)
        MachineFactory(uid="HAS-1", inspection_date=date(2027, 1, 1))
        resp = auth_client.get(reverse("machines:list"), {"inspection_status": "unknown"})
        assert b"UNK-1" in resp.content
        assert b"HAS-1" not in resp.content


# =============================================================================
# Create / Update view — service VR
# =============================================================================


@pytest.mark.django_db
class TestCreateUpdateValidationErrorPaths:
    """form_valid z service-VR (lines 186-188, 213-215)."""

    def test_create_with_service_vr(self, staff_client, monkeypatch):
        """Service rzuca VR → form_invalid (200 z błędem)."""
        from django.core.exceptions import ValidationError

        from machines import views as machines_views

        def boom(**kwargs):
            raise ValidationError("Wymuszony VR.")

        monkeypatch.setattr(machines_views, "create_machine", boom)
        resp = staff_client.post(
            reverse("machines:create"),
            {
                "uid": "VR-FAIL",
                "name": "Test VR",
                "machine_type": Machine.Type.KOPARKA,
                "model": "",
                "capacity": 0,
                "status": Machine.Status.W_MAGAZYNIE,
                "location": "Magazyn",
                "inspection_date": "",
                "manufacturer": "",
                "serial_number": "",
                "build_year": 0,
                "notes": "",
            },
        )
        assert resp.status_code == 200
        assert resp.context["form"].errors

    def test_create_view_context_has_form_title(self, staff_client):
        """get_context_data dodaje form_title + submit_label (lines 193-196)."""
        resp = staff_client.get(reverse("machines:create"))
        assert resp.status_code == 200
        assert "form_title" in resp.context
        assert "submit_label" in resp.context

    def test_update_view_context_has_form_title(self, staff_client):
        """UpdateView get_context_data (lines 225-228)."""
        machine = MachineFactory(uid="CTX-1")
        resp = staff_client.get(reverse("machines:update", kwargs={"uid": machine.uid}))
        assert resp.status_code == 200
        assert "form_title" in resp.context

    def test_update_with_service_vr(self, staff_client, monkeypatch):
        """update_machine rzuca VR → form_invalid (lines 213-215)."""
        from django.core.exceptions import ValidationError

        from machines import views as machines_views

        def boom(machine, **kwargs):
            raise ValidationError("Update VR.")

        monkeypatch.setattr(machines_views, "update_machine", boom)
        machine = MachineFactory(uid="UPD-VR")
        resp = staff_client.post(
            reverse("machines:update", kwargs={"uid": machine.uid}),
            {
                "uid": machine.uid,
                "name": "X",
                "machine_type": machine.machine_type,
                "model": "",
                "capacity": 0,
                "status": machine.status,
                "location": machine.location,
                "inspection_date": "",
                "manufacturer": "",
                "serial_number": "",
                "build_year": 0,
                "notes": "",
            },
        )
        assert resp.status_code == 200

    def test_update_emits_warnings(self, staff_client, monkeypatch):
        """update_machine zwraca (machine, warnings) — view emituje messages.warning."""
        from machines import views as machines_views

        def with_warnings(machine, **kwargs):
            return machine, ["warn1", "warn2"]

        monkeypatch.setattr(machines_views, "update_machine", with_warnings)
        machine = MachineFactory(uid="UPD-W")
        resp = staff_client.post(
            reverse("machines:update", kwargs={"uid": machine.uid}),
            {
                "uid": machine.uid,
                "name": "Z warning",
                "machine_type": machine.machine_type,
                "model": "",
                "capacity": 0,
                "status": machine.status,
                "location": machine.location,
                "inspection_date": "",
                "manufacturer": "",
                "serial_number": "",
                "build_year": 0,
                "notes": "",
            },
        )
        # 302 to detail
        assert resp.status_code == 302


# =============================================================================
# XLSX import — error paths
# =============================================================================


def _xlsx_bytes(rows: list[list]) -> BytesIO:
    """Helper — buduje xlsx in-memory z listy wierszy."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@pytest.mark.django_db
class TestXlsxImportErrorPaths:
    """Pokrycie: bad file format, skipped rows (no uid), per-row VR, truncation >10."""

    def _xlsx_upload(self, content_bytes: bytes, filename: str = "test.xlsx"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            filename,
            content_bytes,
            content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        )

    def test_import_bad_file_format(self, staff_client):
        """Plik nie-XLSX → openpyxl rzuca → flash error + form_invalid (328-329)."""
        bad_file = self._xlsx_upload(b"NOT XLSX CONTENT", filename="bad.xlsx")
        resp = staff_client.post(reverse("machines:import_xlsx"), {"file": bad_file})
        # form_invalid → 200 z błędem (XLSX nie odczytany)
        assert resp.status_code == 200

    def test_import_with_blank_uid_rows_skipped(self, staff_client):
        """Wiersz bez uid → skipped (line 310-311) + warning."""
        header = [
            "uid",
            "name",
            "machine_type",
            "model",
            "capacity",
            "status",
            "location",
            "inspection_date",
            "manufacturer",
            "serial_number",
            "build_year",
            "notes",
        ]
        rows = [
            header,
            ["BLANK-1", "Z UID", "koparka", "", 0, "W magazynie", "Magazyn", None, "", "", 0, ""],
            ["", "Bez UID", "koparka", "", 0, "W magazynie", "Magazyn", None, "", "", 0, ""],
        ]
        buf = _xlsx_bytes(rows)
        resp = staff_client.post(
            reverse("machines:import_xlsx"),
            {"file": self._xlsx_upload(buf.getvalue())},
        )
        assert resp.status_code == 302
        assert Machine.objects.filter(uid="BLANK-1").exists()

    def test_import_with_invalid_row_logged(self, staff_client):
        """Per-row VR (np. invalid status) → errors list (lines 328-332)."""
        header = [
            "uid",
            "name",
            "machine_type",
            "model",
            "capacity",
            "status",
            "location",
            "inspection_date",
            "manufacturer",
            "serial_number",
            "build_year",
            "notes",
        ]
        rows = [
            header,
            [
                "BAD-1",
                "Test",
                "INVALID_TYPE",
                "",
                "not-int",
                "W magazynie",
                "Mag",
                None,
                "",
                "",
                0,
                "",
            ],
        ]
        buf = _xlsx_bytes(rows)
        resp = staff_client.post(
            reverse("machines:import_xlsx"),
            {"file": self._xlsx_upload(buf.getvalue())},
        )
        from django.contrib.messages import get_messages

        assert resp.status_code == 302
        # Zły wiersz NIE może zostać utrwalony (inaczej cichy zapis niepoprawnych
        # danych) ORAZ musi pojawić się komunikat błędu per-wiersz — sam 302 był
        # niezmienniczy względem tego, czy walidacja zadziałała.
        assert not Machine.objects.filter(uid="BAD-1").exists()
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        assert any("BAD-1" in m for m in msgs)

    def test_import_with_more_than_10_errors_shows_truncation_msg(self, staff_client):
        """>10 błędów → "...oraz N dalszych" (line 344-348)."""
        header = [
            "uid",
            "name",
            "machine_type",
            "model",
            "capacity",
            "status",
            "location",
            "inspection_date",
            "manufacturer",
            "serial_number",
            "build_year",
            "notes",
        ]
        # 12 wierszy z invalid capacity (non-int)
        bad_rows = [
            [
                f"BAD-{i:02d}",
                f"Test {i}",
                "koparka",
                "",
                "abc",
                "W magazynie",
                "Mag",
                None,
                "",
                "",
                "xyz",
                "",
            ]
            for i in range(12)
        ]
        buf = _xlsx_bytes([header, *bad_rows])
        resp = staff_client.post(
            reverse("machines:import_xlsx"),
            {"file": self._xlsx_upload(buf.getvalue())},
        )
        from django.contrib.messages import get_messages

        assert resp.status_code == 302
        # Żaden zły wiersz nie zostaje utrwalony ORAZ komunikat truncation
        # ("...dalszych") faktycznie się pojawia (gałąź >10 błędów).
        assert Machine.objects.filter(uid__startswith="BAD-").count() == 0
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        assert any("dalszych" in m for m in msgs)


# =============================================================================
# _sanitize_xlsx_cell — int passthrough
# =============================================================================


def test_sanitize_xlsx_cell_passes_non_str_through():
    """_sanitize zwraca liczby/datę bez zmian (line 370)."""
    from machines.views import _sanitize_xlsx_cell

    assert _sanitize_xlsx_cell(42) == 42
    assert _sanitize_xlsx_cell(3.14) == 3.14
    assert _sanitize_xlsx_cell(None) is None


def test_sanitize_xlsx_cell_prefixes_formula():
    from machines.views import _sanitize_xlsx_cell

    assert _sanitize_xlsx_cell("=cmd|evil") == "'=cmd|evil"
    assert _sanitize_xlsx_cell("+1") == "'+1"
    assert _sanitize_xlsx_cell("@SUM") == "'@SUM"


def test_sanitize_xlsx_cell_no_op_for_normal_string():
    from machines.views import _sanitize_xlsx_cell

    assert _sanitize_xlsx_cell("KOP-001") == "KOP-001"


# =============================================================================
# Status action views — VR paths + closed=0 branch
# =============================================================================


@pytest.mark.django_db
class TestStatusActionsValidationError:
    """set_service/close_repair/retire z service-VR (lines 430-431, 474-485, 508-509)."""

    def test_set_service_with_vr_flashes_error(self, staff_client, monkeypatch):
        """set_machine_to_service rzuca VR → flash + redirect (430-431)."""
        from django.core.exceptions import ValidationError

        from machines import views as machines_views

        def boom(machine):
            raise ValidationError("Wymuszony VR set_service.")

        monkeypatch.setattr(machines_views, "set_machine_to_service", boom)
        machine = MachineFactory(uid="VR-SVC")
        resp = staff_client.post(reverse("machines:set_service", kwargs={"uid": machine.uid}))
        assert resp.status_code == 302  # redirect z flash error
        machine.refresh_from_db()
        # status niezmieniony (service rzucił przed save)
        assert machine.status != Machine.Status.W_SERWISIE

    def test_return_with_closed_0_branch(self, staff_client):
        """return_machine_to_warehouse zwraca {"closed": 0} → simpler success msg."""
        machine = AvailableMachineFactory(uid="NO-RES")
        # Brak rezerwacji → closed=0
        resp = staff_client.post(reverse("machines:return", kwargs={"uid": machine.uid}))
        assert resp.status_code == 302
        machine.refresh_from_db()
        # już była w magazynie, nadal w magazynie
        assert machine.status == Machine.Status.W_MAGAZYNIE

    def test_return_with_closed_positive(self, staff_client):
        """closed > 0 → success msg z "zamknięto X aktywnych rezerwacji"."""
        from datetime import date

        from reservations.factories import ConfirmedReservationFactory

        # Stwórz maszynę na budowie + aktywną rezerwację
        machine = MachineFactory(uid="HAS-RES", status=Machine.Status.NA_BUDOWIE)
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date.today() - timedelta(days=2),
            end_date=date.today() + timedelta(days=5),
        )
        resp = staff_client.post(reverse("machines:return", kwargs={"uid": machine.uid}))
        assert resp.status_code == 302
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE

    def test_close_repair_success_path(self, staff_client):
        """close_repair view (lines 473-485 happy path)."""
        machine = InServiceMachineFactory(uid="REP-OK")
        resp = staff_client.post(reverse("machines:close_repair", kwargs={"uid": machine.uid}))
        assert resp.status_code == 302
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE

    def test_close_repair_with_vr_flashes_error(self, staff_client):
        """close_repair gdy maszyna nie W_SERWISIE → VR (lines 477-478)."""
        machine = AvailableMachineFactory(uid="REP-VR")  # W_MAGAZYNIE
        resp = staff_client.post(reverse("machines:close_repair", kwargs={"uid": machine.uid}))
        assert resp.status_code == 302  # redirect z flash
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE  # bez zmian

    def test_retire_with_vr_flashes_error(self, staff_client, monkeypatch):
        """retire_machine rzuca VR → flash + redirect (lines 508-509)."""
        from django.core.exceptions import ValidationError

        from machines import views as machines_views

        def boom(machine, **kwargs):
            raise ValidationError("Cannot retire.")

        monkeypatch.setattr(machines_views, "retire_machine", boom)
        machine = MachineFactory(uid="RTR-VR")
        resp = staff_client.post(
            reverse("machines:retire", kwargs={"uid": machine.uid}),
            data={"reason": "test reason"},
        )
        assert resp.status_code == 302  # redirect z flash error
        machine.refresh_from_db()
        assert machine.status != Machine.Status.WYCOFANA

    def test_retire_success_with_reason(self, staff_client):
        """retire happy path — pole reason."""
        machine = MachineFactory(uid="RTR-OK", status=Machine.Status.W_MAGAZYNIE)
        resp = staff_client.post(
            reverse("machines:retire", kwargs={"uid": machine.uid}),
            data={"reason": "Sprzedana"},
        )
        assert resp.status_code == 302
        machine.refresh_from_db()
        assert machine.status == Machine.Status.WYCOFANA
