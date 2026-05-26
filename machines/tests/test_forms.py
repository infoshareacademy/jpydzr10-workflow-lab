"""Tests for :mod:`machines.forms`."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from machines.forms import MachineFilterForm, MachineForm, MachineImportXlsxForm
from machines.models import Machine


@pytest.mark.django_db
def test_machine_form_valid_minimum():
    form = MachineForm(
        data={
            "uid": "F-1",
            "name": "Test form",
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
        }
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_machine_form_missing_uid_is_invalid():
    form = MachineForm(
        data={
            "uid": "",
            "name": "Test",
            "machine_type": Machine.Type.KOPARKA,
            "status": Machine.Status.W_MAGAZYNIE,
            "location": "Magazyn",
        }
    )
    assert not form.is_valid()
    assert "uid" in form.errors


def test_filter_form_empty_is_valid():
    form = MachineFilterForm(data={})
    assert form.is_valid()
    assert form.cleaned_data["search"] == ""
    assert form.cleaned_data["status"] == ""


def test_filter_form_with_invalid_status_is_invalid():
    form = MachineFilterForm(data={"status": "NIEPRAWIDLOWY"})
    assert not form.is_valid()


def test_import_xlsx_form_rejects_oversize():
    big = SimpleUploadedFile("big.xlsx", b"a" * (6 * 1024 * 1024))
    form = MachineImportXlsxForm(data={}, files={"file": big})
    assert not form.is_valid()
    assert "5 MB" in form.errors["file"][0]


def test_import_xlsx_form_rejects_wrong_extension():
    txt = SimpleUploadedFile("data.txt", b"hello", content_type="text/plain")
    form = MachineImportXlsxForm(data={}, files={"file": txt})
    assert not form.is_valid()


def test_import_xlsx_form_accepts_small_xlsx():
    # Magic bytes 'PK\x03\x04' wymagane przez clean_file (C2-4 P0 fix) — nie
    # walidujemy całego XLSX bo to oddzielne testy w test_views.py.
    buffer = BytesIO(b"PK\x03\x04" + b"x" * 100)
    upload = SimpleUploadedFile(
        "ok.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    form = MachineImportXlsxForm(data={}, files={"file": upload})
    assert form.is_valid(), form.errors


def test_import_xlsx_form_rejects_invalid_magic_bytes():
    """Plik z .xlsx ext ale bez nagłówka ZIP (PK) jest odrzucony (C2-4 P0)."""
    fake = SimpleUploadedFile(
        "fake.xlsx",
        b"<html>not a xlsx</html>",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    form = MachineImportXlsxForm(data={}, files={"file": fake})
    assert not form.is_valid()
    assert "magic bytes" in form.errors["file"][0].lower()
