"""Tests for :mod:`machines.services`."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from machines.factories import (
    InServiceMachineFactory,
    MachineFactory,
    OnSiteMachineFactory,
)
from machines.models import Machine
from machines.services import (
    close_repair,
    create_machine,
    retire_machine,
    return_machine_to_warehouse,
    set_machine_to_service,
    update_machine,
)


@pytest.mark.django_db
def test_create_machine_minimum_fields():
    machine = create_machine(uid="NEW-001", name="Nowa koparka")
    assert machine.pk is not None
    assert machine.uid == "NEW-001"  # already upper-case
    assert machine.status == Machine.Status.W_MAGAZYNIE
    assert machine.location == "Magazyn"


@pytest.mark.django_db
def test_create_machine_uid_strip_and_upper():
    machine = create_machine(uid="  abc-1  ", name="Test")
    assert machine.uid == "ABC-1"


@pytest.mark.django_db
def test_create_machine_empty_uid_raises():
    with pytest.raises(ValidationError):
        create_machine(uid="  ", name="X")


@pytest.mark.django_db
def test_update_machine_changes_only_passed_fields():
    machine = MachineFactory(uid="U-1", name="Stara", location="Magazyn")
    _, warnings = update_machine(machine, name="Nowa")
    machine.refresh_from_db()
    assert machine.name == "Nowa"
    assert machine.location == "Magazyn"  # untouched
    assert warnings == []


@pytest.mark.django_db
def test_update_machine_ignores_unknown_keys():
    machine = MachineFactory(uid="U-2", name="A")
    update_machine(machine, name="B", non_existing_field="ignored")
    machine.refresh_from_db()
    assert machine.name == "B"


@pytest.mark.django_db
def test_update_machine_warns_on_manual_na_budowie():
    """Ręczne ustawienie NA_BUDOWIE produkuje warning (powinno przejść przez reservation flow)."""
    machine = MachineFactory(uid="U-3", status=Machine.Status.W_MAGAZYNIE)
    _, warnings = update_machine(machine, status=Machine.Status.NA_BUDOWIE)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.NA_BUDOWIE
    assert len(warnings) == 1
    assert "Na budowie" in warnings[0]


@pytest.mark.django_db
def test_update_machine_no_warning_when_already_on_site():
    """Brak warning gdy status NA_BUDOWIE pozostaje bez zmian (np. tylko edycja notatki)."""
    machine = MachineFactory(uid="U-4", status=Machine.Status.NA_BUDOWIE)
    _, warnings = update_machine(machine, notes="aktualizacja notatki")
    machine.refresh_from_db()
    assert warnings == []


@pytest.mark.django_db
def test_set_machine_to_service_happy_path():
    machine = MachineFactory(uid="S-1", status=Machine.Status.W_MAGAZYNIE)
    set_machine_to_service(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_SERWISIE


@pytest.mark.django_db
def test_set_machine_to_service_blocks_on_site():
    machine = OnSiteMachineFactory(uid="S-2")
    with pytest.raises(ValidationError, match="na budowie"):
        set_machine_to_service(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.NA_BUDOWIE


@pytest.mark.django_db
def test_set_machine_to_service_blocks_when_already_in_service():
    machine = InServiceMachineFactory(uid="S-3")
    with pytest.raises(ValidationError, match="już w serwisie"):
        set_machine_to_service(machine)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_set_machine_to_service_blocks_with_future_reservations():
    """D6 rule — block service if there are future CONFIRMED reservations."""
    machine = MachineFactory(uid="S-4", status=Machine.Status.W_MAGAZYNIE)

    # Build a stub queryset that mimics ``Reservation.objects.filter(...).order_by(...)``.
    fake_reservation = type("R", (), {"start_date": date(2026, 6, 1), "uid": "RES-1"})()

    class _QS:
        def exists(self):
            return True

        def count(self):
            return 2

        def first(self):
            return fake_reservation

        def order_by(self, *_a, **_k):
            return self

    with (
        patch("machines.services._get_future_confirmed_reservations", return_value=_QS()),
        pytest.raises(ValidationError, match="2 potwierdzonych rezerwacji"),
    ):
        set_machine_to_service(machine)

    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_MAGAZYNIE  # not changed


@pytest.mark.django_db
def test_return_machine_to_warehouse():
    machine = OnSiteMachineFactory(uid="R-1", location="Warszawa, ul. Test 5")
    result = return_machine_to_warehouse(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_MAGAZYNIE
    assert machine.location == "Magazyn"
    assert result == {"closed": 0, "machine_status": Machine.Status.W_MAGAZYNIE}


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_return_machine_to_warehouse_closes_active_reservations():
    """Aktywna rezerwacja (POTWIERDZONA, pokrywająca dziś) jest zamykana + end_date truncate."""
    from reservations.models import Reservation

    machine = OnSiteMachineFactory(uid="R-2")
    active = Reservation.objects.create(
        machine=machine,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 25),  # przyszłość → powinno zostać przycięte
        person="Magazynier Test",
        status=Reservation.Status.POTWIERDZONA,
    )

    # Rezerwacja oczekująca nie powinna być ruszana — zostaje nietknięta.
    pending = Reservation.objects.create(
        machine=machine,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 20),
        person="Inny",
        status=Reservation.Status.OCZEKUJACA,
    )

    result = return_machine_to_warehouse(machine)
    active.refresh_from_db()
    pending.refresh_from_db()

    assert result["closed"] == 1
    assert active.status == Reservation.Status.ZAKONCZONA
    assert active.end_date == date(2026, 5, 16)  # truncate do today
    assert pending.status == Reservation.Status.OCZEKUJACA  # nietknięta


@pytest.mark.django_db
def test_close_repair_flips_to_warehouse():
    """W serwisie → W magazynie po wywołaniu close_repair."""
    machine = InServiceMachineFactory(uid="CR-1")
    close_repair(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_MAGAZYNIE


@pytest.mark.django_db
def test_close_repair_blocks_when_not_in_service():
    """Nie można zakończyć naprawy maszyny która nie jest w serwisie."""
    machine = MachineFactory(uid="CR-2", status=Machine.Status.W_MAGAZYNIE)
    with pytest.raises(ValidationError, match="W serwisie"):
        close_repair(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.W_MAGAZYNIE  # bez zmian


@pytest.mark.django_db
def test_retire_machine_sets_status_wycofana_from_warehouse():
    """Po refaktorze retire flipuje status z dowolnego stanu — nie wymaga już serwisu."""
    machine = MachineFactory(uid="RT-1", status=Machine.Status.W_MAGAZYNIE)
    retire_machine(machine)
    machine.refresh_from_db()
    assert machine.status == Machine.Status.WYCOFANA


@pytest.mark.django_db
def test_retire_machine_sets_status_wycofana_from_service():
    machine = InServiceMachineFactory(uid="RT-2", notes="poprzednia notatka")
    retire_machine(machine, reason="silnik uszkodzony")
    machine.refresh_from_db()
    assert machine.status == Machine.Status.WYCOFANA
    assert "[WYCOFANA] silnik uszkodzony" in machine.notes
    assert "poprzednia notatka" in machine.notes


@pytest.mark.django_db
def test_retire_machine_is_idempotent():
    """Drugie wywołanie retire_machine nie zmienia stanu maszyny."""
    machine = MachineFactory(uid="RT-3", status=Machine.Status.W_MAGAZYNIE)
    retire_machine(machine, reason="pierwsza próba")
    machine.refresh_from_db()
    notes_after_first = machine.notes

    retire_machine(machine, reason="druga próba")
    machine.refresh_from_db()
    assert machine.status == Machine.Status.WYCOFANA
    assert machine.notes == notes_after_first  # nie dopisano drugiej notatki


# =============================================================================
# Wave 12 — coverage gap-filling
# =============================================================================


@pytest.mark.django_db
def test_create_machine_with_image_assigns_attribute():
    """create_machine z image= ustawia .image przed save (line 79)."""
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image as PILImage

    buf = BytesIO()
    PILImage.new("RGB", (1, 1), color="red").save(buf, format="JPEG")
    img_file = SimpleUploadedFile("test.jpg", buf.getvalue(), content_type="image/jpeg")

    machine = create_machine(uid="IMG-1", name="Z obrazkiem", image=img_file)
    assert machine.image  # truthy (ImageFieldFile)


@pytest.mark.django_db
def test_set_machine_to_service_already_in_service_raises():
    """set_service na maszynie już w serwisie → ValidationError (guard)."""
    machine = InServiceMachineFactory(uid="ALREADY-SVC-X")
    with pytest.raises(ValidationError):
        set_machine_to_service(machine)


@pytest.mark.django_db
def test_close_repair_when_not_in_service_raises():
    """close_repair na maszynie nie-W_SERWISIE → ValidationError."""
    machine = MachineFactory(uid="NOT-SVC", status=Machine.Status.W_MAGAZYNIE)
    with pytest.raises(ValidationError):
        close_repair(machine)
