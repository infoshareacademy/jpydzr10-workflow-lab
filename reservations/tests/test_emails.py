"""Testy powiadomień e-mail po potwierdzeniu rezerwacji.

KRYTYCZNE: callback ``transaction.on_commit`` NIE odpala się pod
``@pytest.mark.django_db`` bez ``django_capture_on_commit_callbacks(execute=True)``
— bez tego ``mailoutbox`` zostaje pusty (artefakt harnessu, nie błąd kodu).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from machines.models import Machine
from reservations.models import Reservation
from reservations.services import (
    confirm_reservation,
    create_batch_reservation,
    create_reservation,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


def _creator(username="autor", email="autor@demo.test"):
    return User.objects.create_user(username=username, password="x", email=email)


def _machine(uid):
    return Machine.objects.create(
        uid=uid,
        name=f"Maszyna {uid}",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


def _pending(machine, creator, *, person="Jan Kowalski"):
    start = date.today() + timedelta(days=5)
    end = date.today() + timedelta(days=10)
    return create_reservation(
        machine_id=machine.pk,
        site_id=None,
        start_date=start,
        end_date=end,
        person=person,
        created_by=creator,
    )


def test_single_confirm_sends_one_email(django_capture_on_commit_callbacks, mailoutbox, machine):
    creator = _creator()
    res = _pending(machine, creator)
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert msg.to == ["autor@demo.test"]
    assert machine.uid in msg.subject
    res.refresh_from_db()
    assert res.confirmation_email_queued_at is not None
    assert res.confirmation_email_sent_at is not None


def test_no_email_when_created_by_missing(django_capture_on_commit_callbacks, mailoutbox, machine):
    start = date.today() + timedelta(days=5)
    res = create_reservation(
        machine_id=machine.pk,
        site_id=None,
        start_date=start,
        end_date=start + timedelta(days=3),
        person="Jan Kowalski",
        created_by=None,
    )
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 0


def test_no_email_when_creator_has_no_email(
    django_capture_on_commit_callbacks, mailoutbox, machine
):
    creator = _creator(username="bezmaila", email="")
    res = _pending(machine, creator)
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 0


def test_bulk_confirm_sends_one_email_per_reservation(
    django_capture_on_commit_callbacks, mailoutbox
):
    creator = _creator()
    machines = [_machine(f"BULK-{i}") for i in range(3)]
    start = date.today() + timedelta(days=5)
    result = create_batch_reservation(
        machine_ids=[m.pk for m in machines],
        site_id=None,
        start_date=start,
        end_date=start + timedelta(days=4),
        person="Jan Kowalski",
        created_by=creator,
    )
    from reservations.services import bulk_confirm_batch

    with django_capture_on_commit_callbacks(execute=True):
        bulk_confirm_batch(result["batch_id"])
    assert len(mailoutbox) == 3


def test_bulk_rollback_sends_zero_emails_on_conflict(
    django_capture_on_commit_callbacks, mailoutbox
):
    """3-elementowy batch; środkowa pozycja koliduje → rollback całości, 0 maili.

    Regresja atomowości: gdyby ktoś usunął zewnętrzny @transaction.atomic,
    pozycje 1 i 3 wysłałyby maile mimo błędu pozycji 2.
    """
    creator = _creator()
    machines = [_machine(f"CONF-{i}") for i in range(3)]
    start = date.today() + timedelta(days=5)
    end = start + timedelta(days=4)
    result = create_batch_reservation(
        machine_ids=[m.pk for m in machines],
        site_id=None,
        start_date=start,
        end_date=end,
        person="Jan Kowalski",
        created_by=creator,
    )
    # Wymuszamy konflikt na ŚRODKOWEJ maszynie: wstrzykujemy surowo (omijając
    # walidację serwisu) potwierdzoną, nakładającą się rezerwację. Przy
    # bulk-confirm pozycja batcha na tej maszynie wykryje konflikt pod lockiem.
    Reservation.objects.create(
        machine=machines[1],
        site=None,
        start_date=start,
        end_date=end,
        person="Konflikt",
        status=Reservation.Status.POTWIERDZONA,
        created_by=creator,
    )

    from reservations.services import bulk_confirm_batch

    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(ValidationError),
    ):
        bulk_confirm_batch(result["batch_id"])
    assert len(mailoutbox) == 0
    # Żadna z pozycji batcha nie została potwierdzona (rollback).
    statuses = set(
        Reservation.objects.filter(batch_id=result["batch_id"]).values_list("status", flat=True)
    )
    assert statuses == {Reservation.Status.OCZEKUJACA}
