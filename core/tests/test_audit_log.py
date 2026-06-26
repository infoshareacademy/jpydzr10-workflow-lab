"""Testy dziennika zdarzeń (custom audit log — Task 2.1).

Sprawdzają realne zachowanie warstwy AKCJI (``AuditLogEntry`` +
``AuditLogMiddleware``), a nie tautologie:

* mutująca akcja na śledzonym modelu tworzy wpis z poprawnym ``action`` i diffem,
* anonimowy POST → ``user=None``,
* GET i ścieżki wykluczone (``/i18n/``) nie są logowane,
* IP czytane z ``X-Forwarded-For``,
* eksport CSV ma BOM i nie psuje polskich znaków,
* ``prune_audit_log`` usuwa wpisy starsze niż N dni,
* admin jest read-only.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.test import Client, RequestFactory
from django.urls import reverse
from freezegun import freeze_time

from accounts.factories import AdminUserFactory
from core.admin import AuditLogEntryAdmin
from core.models import AuditLogEntry
from machines.factories import AvailableMachineFactory
from reservations.factories import PendingReservationFactory
from reservations.models import Reservation

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    return AdminUserFactory()


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


def _pending_reservation():
    return PendingReservationFactory(machine=AvailableMachineFactory())


def test_confirm_reservation_creates_entry(admin_client, admin_user):
    reservation = _pending_reservation()
    resp = admin_client.post(reverse("reservations:confirm", args=[reservation.pk]))
    assert resp.status_code in (204, 302)

    entry = AuditLogEntry.objects.get(
        action="reservations:confirm", object_type="reservations.Reservation"
    )
    assert entry.object_id == str(reservation.pk)
    assert entry.user == admin_user
    # confirm zmienia status OCZEKUJACA -> POTWIERDZONA, więc diff to odnotowuje.
    assert "status" in entry.changes
    old, new = entry.changes["status"]
    assert old == Reservation.Status.OCZEKUJACA
    assert new == Reservation.Status.POTWIERDZONA


def test_cancel_reservation_records_reason_in_changes(admin_client):
    reservation = _pending_reservation()
    resp = admin_client.post(
        reverse("reservations:cancel", args=[reservation.pk]),
        {"cancellation_reason": Reservation.CancellationReason.AWARIA},
    )
    assert resp.status_code in (204, 302)

    entry = AuditLogEntry.objects.get(
        action="reservations:cancel", object_type="reservations.Reservation"
    )
    assert "cancellation_reason" in entry.changes
    _old, new = entry.changes["cancellation_reason"]
    assert new == Reservation.CancellationReason.AWARIA


def test_anonymous_user_logged_as_none():
    """Anonimowy POST → login_required zwraca 302; wpis ma user=None."""
    reservation = _pending_reservation()
    resp = Client().post(
        reverse("reservations:cancel", args=[reservation.pk]),
        {"cancellation_reason": Reservation.CancellationReason.INNE},
    )
    assert resp.status_code == 302  # redirect do logowania

    entry = AuditLogEntry.objects.latest("timestamp")
    assert entry.user is None
    assert entry.action == "reservations:cancel"
    # Nic się nie zapisało (redirect przed widokiem) → wpis-akcja bez obiektu.
    assert entry.object_type == ""


def test_get_request_not_logged(admin_client):
    admin_client.get(reverse("reservations:list"))
    assert AuditLogEntry.objects.count() == 0


def test_setlang_path_excluded(admin_client):
    """POST /i18n/setlang/ jest wykluczony — mimo 302 nie tworzy wpisu."""
    resp = admin_client.post(reverse("set_language"), {"language": "en", "next": "/"})
    assert resp.status_code in (302, 204)
    assert AuditLogEntry.objects.count() == 0


def test_ip_capture_from_x_forwarded_for(admin_client):
    reservation = _pending_reservation()
    admin_client.post(
        reverse("reservations:cancel", args=[reservation.pk]),
        {"cancellation_reason": Reservation.CancellationReason.INNE},
        HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1",
    )
    entry = AuditLogEntry.objects.filter(action="reservations:cancel").first()
    assert entry is not None
    assert entry.ip_address == "203.0.113.5"


def test_prune_removes_old_entries():
    with freeze_time("2026-01-01"):
        AuditLogEntry.objects.create(action="stary")
    AuditLogEntry.objects.create(action="swiezy")  # timestamp = teraz

    call_command("prune_audit_log", "--older-than", "90")

    assert not AuditLogEntry.objects.filter(action="stary").exists()
    assert AuditLogEntry.objects.filter(action="swiezy").exists()


def test_prune_dry_run_keeps_entries():
    with freeze_time("2026-01-01"):
        AuditLogEntry.objects.create(action="stary")
    call_command("prune_audit_log", "--older-than", "90", "--dry-run")
    assert AuditLogEntry.objects.filter(action="stary").exists()


def test_csv_export_has_bom_and_polish_chars(admin_user):
    AuditLogEntry.objects.create(
        action="reservations:cancel",
        object_repr="Rezerwacja — łąka, żółć ąęó",
        user=admin_user,
        ip_address="203.0.113.5",
    )
    admin_obj = AuditLogEntryAdmin(AuditLogEntry, AdminSite())
    request = RequestFactory().get("/admin/core/auditlogentry/")
    response = admin_obj.export_as_csv(request, AuditLogEntry.objects.all())

    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM UTF-8
    assert "łąka, żółć ąęó".encode() in response.content
    assert response["Content-Disposition"].startswith("attachment; filename=")


def test_admin_is_read_only():
    admin_obj = AuditLogEntryAdmin(AuditLogEntry, AdminSite())
    request = RequestFactory().get("/")
    assert admin_obj.has_add_permission(request) is False
    assert admin_obj.has_change_permission(request) is False
    assert admin_obj.has_delete_permission(request) is False


def test_timestamp_uses_auto_now_add():
    """Sanity: timestamp ustawiany automatycznie (auto_now_add) przy utworzeniu."""
    with freeze_time(datetime(2026, 3, 15, 10, 0, tzinfo=UTC)):
        entry = AuditLogEntry.objects.create(action="test")
    assert entry.timestamp.year == 2026
    assert entry.timestamp.month == 3
