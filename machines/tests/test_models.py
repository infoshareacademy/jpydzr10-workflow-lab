"""Model-level tests for :class:`machines.models.Machine`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from machines.factories import MachineFactory
from machines.models import INSPECTION_WARNING_DAYS, Machine


@pytest.mark.django_db
def test_machine_creation_sets_defaults():
    machine = MachineFactory(uid="KOP-100", name="Koparka testowa")
    assert machine.pk is not None
    assert machine.status == Machine.Status.W_MAGAZYNIE
    assert machine.location == "Magazyn"
    assert machine.created_at is not None
    assert machine.updated_at is not None


@pytest.mark.django_db
def test_uid_must_be_unique():
    MachineFactory(uid="DUP-001")
    duplicate = Machine(uid="DUP-001", name="Inna maszyna")
    with pytest.raises(ValidationError):
        duplicate.full_clean()


@pytest.mark.django_db
def test_status_choices_validated():
    machine = MachineFactory()
    machine.status = "Nielegalny status"
    with pytest.raises(ValidationError):
        machine.full_clean()


# -----------------------------------------------------------------------------
# UID_VALIDATOR — regex ``^[A-Z0-9_-]+$`` — odrzuca path-traversal-podobne UID-y
# -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("bad_uid", ["M..0001", "M.0001", "M 0001", "m-001", "M/001", "M@1", "Ę-1"])
def test_uid_validator_rejects_invalid_chars(bad_uid):
    """UID z kropkami/spacjami/lowercase/slashami/diakrytyką — odrzucony."""
    machine = Machine(uid=bad_uid, name="Test")
    with pytest.raises(ValidationError) as exc_info:
        machine.full_clean()
    assert "uid" in exc_info.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize("good_uid", ["KOP-001", "M-0001", "X_1", "ABC123", "A", "100"])
def test_uid_validator_accepts_valid(good_uid):
    """Wielkie litery + cyfry + ``_`` + ``-`` — akceptowane.

    ``full_clean()`` może rzucić ``ValidationError`` z powodu innych pól
    (np. wymaganych pól, których tu nie ustawiamy), ale ``uid`` validator
    powinien przejść — sprawdzamy że ``"uid"`` NIE jest w ``message_dict``.

    Wzorzec ``except`` (zamiast ``pytest.raises``) jest świadomy: walidacja
    jest "może rzucić, może nie" — zależy czy inne pola dają błąd. Plik
    używa ``# noqa: PT017`` żeby nie reformatować na ``pytest.raises``.
    """
    machine = Machine(uid=good_uid, name="Test")
    try:
        machine.full_clean()
    except ValidationError as exc:
        assert "uid" not in exc.message_dict, (  # noqa: PT017
            f"UID {good_uid!r} should be valid"
        )


@pytest.mark.django_db
def test_str_representation():
    machine = MachineFactory(uid="LOL-1", name="Wesoła koparka")
    assert str(machine) == "LOL-1 — Wesoła koparka"


@pytest.mark.django_db
def test_default_ordering_by_uid():
    MachineFactory(uid="B-002")
    MachineFactory(uid="A-001")
    MachineFactory(uid="C-003")
    uids = list(Machine.objects.values_list("uid", flat=True))
    assert uids == sorted(uids)


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_inspection_status_ok():
    machine = MachineFactory(inspection_date=date(2026, 6, 30))  # >14 days
    assert machine.inspection_status == "ok"
    assert machine.inspection_status_label == "Przegląd aktualny"
    assert machine.inspection_days_left == 45


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_inspection_status_warning_boundary():
    # exactly INSPECTION_WARNING_DAYS days away still counts as warning.
    machine = MachineFactory(
        inspection_date=date(2026, 5, 16) + timedelta(days=INSPECTION_WARNING_DAYS)
    )
    assert machine.inspection_status == "warning"
    assert machine.inspection_status_label == "Wkrótce przegląd"


@pytest.mark.django_db
@freeze_time("2026-05-16")
def test_inspection_status_overdue():
    machine = MachineFactory(inspection_date=date(2026, 1, 1))
    assert machine.inspection_status == "overdue"
    assert machine.inspection_status_label == "Przegląd przeterminowany"
    assert machine.inspection_days_left < 0


@pytest.mark.django_db
def test_inspection_status_unknown_when_no_date():
    machine = MachineFactory(inspection_date=None)
    assert machine.inspection_status == "unknown"
    assert machine.inspection_status_label == "Brak daty przeglądu"
    assert machine.inspection_days_left is None


@pytest.mark.django_db
def test_is_available_true_only_in_warehouse():
    in_warehouse = MachineFactory(status=Machine.Status.W_MAGAZYNIE)
    on_site = MachineFactory(uid="X-2", status=Machine.Status.NA_BUDOWIE)
    in_service = MachineFactory(uid="X-3", status=Machine.Status.W_SERWISIE)
    assert in_warehouse.is_available
    assert not on_site.is_available
    assert not in_service.is_available
