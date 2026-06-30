"""Testy alertów przeglądowych (inspection_overdue / inspection_upcoming) + komendy."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from accounts.models import EmployeeProfile
from machines import emails
from machines.models import Machine

User = get_user_model()
pytestmark = pytest.mark.django_db


def _admin(username="adm", email="admin@demo.test"):
    user = User.objects.create_user(username, password="x", email=email)
    user.profile.function = EmployeeProfile.Function.ADMIN
    user.profile.save()  # signal → grupa "Administratorzy"
    return user


def _machine(uid, *, inspection_date):
    return Machine.objects.create(
        uid=uid,
        name=f"Maszyna {uid}",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
        inspection_date=inspection_date,
    )


def test_overdue_email_lists_machines_to_admins(mailoutbox):
    _admin()
    _machine("OVD-1", inspection_date=date.today() - timedelta(days=3))
    sent = emails.send_inspection_overdue_email(list(Machine.objects.all()))
    assert sent == 1
    msg = mailoutbox[0]
    assert msg.to == ["admin@demo.test"]
    assert "OVD-1" in msg.body
    assert "Przeterminowane" in msg.subject
    assert "Overdue" in msg.subject


def test_inspection_email_skipped_without_admins(mailoutbox):
    m = _machine("OVD-2", inspection_date=date.today() - timedelta(days=1))
    assert emails.send_inspection_overdue_email([m]) == 0
    assert len(mailoutbox) == 0


def test_inspection_email_skips_opted_out_admin(mailoutbox):
    """Administrator wypisany z alertów przeglądowych nie dostaje maila."""
    from core.email_optout import EmailCategory

    admin = _admin()
    admin.profile.email_opt_outs = [EmailCategory.INSPECTIONS]
    admin.profile.save(update_fields=["email_opt_outs"])
    m = _machine("OVD-3", inspection_date=date.today() - timedelta(days=1))
    assert emails.send_inspection_overdue_email([m]) == 0
    assert len(mailoutbox) == 0


def test_inspection_email_has_unsubscribe_link(mailoutbox):
    _admin()
    m = _machine("OVD-4", inspection_date=date.today() - timedelta(days=1))
    emails.send_inspection_overdue_email([m])
    html = next(c for c, t in mailoutbox[0].alternatives if t == "text/html")
    assert reverse("accounts:email_preferences") in html


def test_command_sends_overdue_and_upcoming(mailoutbox):
    _admin()
    _machine("OVD-3", inspection_date=date.today() - timedelta(days=5))
    _machine("UPC-1", inspection_date=date.today() + timedelta(days=7))
    # Daleka przyszłość — nie powinna trafić do żadnego alertu.
    _machine("OK-1", inspection_date=date.today() + timedelta(days=90))

    call_command("send_inspection_alerts")

    # Dwa maile: overdue + upcoming.
    assert len(mailoutbox) == 2
    bodies = "\n".join(m.body for m in mailoutbox)
    assert "OVD-3" in bodies
    assert "UPC-1" in bodies
    assert "OK-1" not in bodies


def test_upcoming_idempotent_overdue_repeats(mailoutbox):
    _admin()
    _machine("OVD-4", inspection_date=date.today() - timedelta(days=2))
    upc = _machine("UPC-2", inspection_date=date.today() + timedelta(days=5))

    call_command("send_inspection_alerts")  # overdue + upcoming
    call_command("send_inspection_alerts")  # overdue znów, upcoming NIE

    subjects = [m.subject for m in mailoutbox]
    overdue_count = sum("Przeterminowane" in s for s in subjects)
    upcoming_count = sum("Zbliżające" in s for s in subjects)
    assert overdue_count == 2  # zaległość natrętna — przy każdym uruchomieniu
    assert upcoming_count == 1  # zbliżający się — jeden alert na okno
    upc.refresh_from_db()
    assert upc.inspection_warning_sent_at is not None


def test_upcoming_flag_resets_when_inspection_done(mailoutbox):
    _admin()
    upc = _machine("UPC-3", inspection_date=date.today() + timedelta(days=5))

    call_command("send_inspection_alerts")  # wysyła upcoming, ustawia flagę
    upc.refresh_from_db()
    assert upc.inspection_warning_sent_at is not None

    # Przegląd wykonany → data daleko w przyszłość (maszyna wychodzi z okna).
    upc.inspection_date = date.today() + timedelta(days=120)
    upc.save(update_fields=["inspection_date"])
    call_command("send_inspection_alerts")  # reset flagi

    upc.refresh_from_db()
    assert upc.inspection_warning_sent_at is None
