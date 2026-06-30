"""Testy eksportu danych (RODO Art. 20) + anonimizacji obejmującej dziennik zdarzeń."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts.services import anonymize_employee
from core.models import AuditLogEntry
from machines.models import Machine
from reservations.models import Reservation

User = get_user_model()
pytestmark = pytest.mark.django_db


def _user(username="exp", email="exp@demo.test"):
    return User.objects.create_user(username, password="Planer2026!", email=email)


def test_export_requires_login():
    resp = Client().post(reverse("accounts:data_export"))
    assert resp.status_code == 302  # redirect do logowania


def test_export_rejects_get_for_authenticated(client):
    # Eksport jest POST-only (CSRF + brak prefetch na GET) — GET zalogowanego = 405.
    client.force_login(_user("getreject", "getreject@demo.test"))
    resp = client.get(reverse("accounts:data_export"))
    assert resp.status_code == 405


def test_export_returns_own_data_as_json_download(client):
    user = _user()
    machine = Machine.objects.create(
        uid="EXP-1",
        name="Koparka",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )
    Reservation.objects.create(
        machine=machine,
        site=None,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=2),
        person="Jan",
        status=Reservation.Status.OCZEKUJACA,
        created_by=user,
    )
    client.force_login(user)
    resp = client.post(reverse("accounts:data_export"))

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")
    assert "attachment" in resp["Content-Disposition"]
    assert f"moje-dane-{user.username}" in resp["Content-Disposition"]

    data = json.loads(resp.content)
    assert data["account"]["username"] == "exp"
    assert data["account"]["email"] == "exp@demo.test"
    assert len(data["reservations"]) == 1
    assert data["reservations"][0]["machine"] == "EXP-1"


def test_export_excludes_other_users_reservations(client):
    me = _user("me", "me@demo.test")
    other = _user("other", "other@demo.test")
    machine = Machine.objects.create(
        uid="EXP-2",
        name="K",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )
    Reservation.objects.create(
        machine=machine,
        site=None,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        person="X",
        status=Reservation.Status.OCZEKUJACA,
        created_by=other,
    )
    client.force_login(me)
    data = json.loads(client.post(reverse("accounts:data_export")).content)
    assert data["reservations"] == []  # cudza rezerwacja niewidoczna


def test_export_rate_limited_to_once_per_day(client):
    # Drugi eksport tego samego dnia jest zablokowany (rate-limit 1/d) —
    # pierwszy 200, drugi NIE 200 (ochrona przed nadużyciem wysyłki danych).
    user = _user("ratelimited", "rl@demo.test")
    client.force_login(user)
    first = client.post(reverse("accounts:data_export"))
    assert first.status_code == 200
    second = client.post(reverse("accounts:data_export"))
    assert second.status_code != 200


def test_anonymize_scrubs_audit_log_pii():
    user = _user("toanon", "toanon@demo.test")
    AuditLogEntry.objects.create(
        user=user,
        action="accounts:login",
        ip_address="203.0.113.5",
        user_agent="Mozilla/5.0 Test",
    )
    anonymize_employee(user.profile)

    entry = AuditLogEntry.objects.get(user=user)
    # Akcja zostaje (rozliczalność), ale dane osobowe (IP, klient) wymazane.
    assert entry.action == "accounts:login"
    assert entry.ip_address is None
    assert entry.user_agent == ""
