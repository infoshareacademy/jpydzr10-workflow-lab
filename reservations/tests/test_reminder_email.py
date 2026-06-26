"""Testy przypomnienia T-1 (reservation_reminder) + komendy send_daily_reminders."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from machines.models import Machine
from reservations import emails
from reservations.models import Reservation

User = get_user_model()
pytestmark = pytest.mark.django_db


def _creator(email="autor@demo.test"):
    return User.objects.create_user("autor", password="x", email=email)


def _machine(uid="REM-1"):
    return Machine.objects.create(
        uid=uid,
        name=f"Maszyna {uid}",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


def _confirmed(machine, creator, *, start):
    return Reservation.objects.create(
        machine=machine,
        site=None,
        start_date=start,
        end_date=start + timedelta(days=3),
        person="Jan Kowalski",
        status=Reservation.Status.POTWIERDZONA,
        created_by=creator,
    )


def test_reminder_email_is_bilingual_with_link(mailoutbox):
    creator = _creator()
    res = _confirmed(_machine(), creator, start=date.today() + timedelta(days=1))
    sent = emails.send_reservation_reminder_email(res.pk)
    assert sent == 1
    msg = mailoutbox[0]
    assert msg.to == ["autor@demo.test"]
    assert "Przypomnienie" in msg.subject
    assert "reminder" in msg.subject
    html = next(c for c, t in msg.alternatives if t == "text/html")
    assert "rozpoczyna się jutro" in html  # PL
    assert f"/rezerwacje/{res.pk}/" in html  # klikalny link do detalu
    assert "Jan Kowalski" in msg.body


def test_reminder_skipped_when_creator_has_no_email(mailoutbox):
    creator = _creator(email="")
    res = _confirmed(_machine(), creator, start=date.today() + timedelta(days=1))
    assert emails.send_reservation_reminder_email(res.pk) == 0
    assert len(mailoutbox) == 0


def test_command_sends_for_tomorrow_only(mailoutbox):
    creator = _creator()
    _confirmed(_machine("REM-A"), creator, start=date.today() + timedelta(days=1))
    # Startuje za 2 dni — NIE powinno dostać przypomnienia dziś.
    _confirmed(_machine("REM-B"), creator, start=date.today() + timedelta(days=2))

    call_command("send_daily_reminders")
    assert len(mailoutbox) == 1
    assert "REM-A" in mailoutbox[0].subject


def test_command_skips_unconfirmed(mailoutbox):
    creator = _creator()
    res = Reservation.objects.create(
        machine=_machine("REM-C"),
        site=None,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        person="X",
        status=Reservation.Status.OCZEKUJACA,
        created_by=creator,
    )
    call_command("send_daily_reminders")
    assert len(mailoutbox) == 0
    res.refresh_from_db()
    assert res.reminder_sent_at is None


def test_command_is_idempotent(mailoutbox):
    creator = _creator()
    res = _confirmed(_machine("REM-D"), creator, start=date.today() + timedelta(days=1))

    call_command("send_daily_reminders")
    call_command("send_daily_reminders")
    call_command("send_daily_reminders")

    # Trzy uruchomienia → dokładnie jeden mail (flaga reminder_sent_at chroni).
    assert len(mailoutbox) == 1
    res.refresh_from_db()
    assert res.reminder_sent_at is not None
