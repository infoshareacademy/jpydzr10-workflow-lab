"""RBAC dla wrażliwych odczytów (koszty serwisowe) + self-guard zwolnień/anonimizacji.

Domyka dwie luki wykryte w audycie:
- ``get_service_costs`` był dostępny przez agenta KAŻDEMU (także montażyście/gościowi),
  choć w UI koszty są za ``service.view_servicerecord`` — chatbot obchodził blokadę.
- ``_execute_terminate_employee`` / ``_execute_anonymize_employee`` nie chroniły przed
  zakończeniem/anonimizacją WŁASNEGO konta ani administratora przez agenta.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from chatbot.tools import (
    _execute_anonymize_employee,
    _execute_terminate_employee,
    execute_read_action,
    read_action_denied,
)

User = get_user_model()


@pytest.fixture
def cost_viewer(db):
    u = User.objects.create_user(username="viewer-costs", password="x")
    u.user_permissions.add(
        Permission.objects.get(content_type__app_label="service", codename="view_servicerecord")
    )
    return User.objects.get(pk=u.pk)


@pytest.fixture
def no_perm_user(db):
    return User.objects.create_user(username="monter-noperm", password="x")


@pytest.mark.django_db
class TestReadCostPermissions:
    def test_guest_denied_costs(self):
        out = read_action_denied("get_service_costs", None)
        assert out is not None
        assert "error" in json.loads(out)

    def test_monter_denied_costs(self, no_perm_user):
        out = read_action_denied("get_service_costs", no_perm_user)
        assert out is not None
        assert "uprawnień" in json.loads(out)["error"]

    def test_viewer_allowed_costs(self, cost_viewer):
        assert read_action_denied("get_service_costs", cost_viewer) is None

    def test_non_sensitive_read_open_to_all(self, no_perm_user):
        # Status/dostępność/przeglądy — dostępne wszystkim, także gościom.
        assert read_action_denied("get_machine_status", no_perm_user) is None
        assert read_action_denied("get_machine_status", None) is None

    def test_execute_read_costs_blocked_for_monter(self, no_perm_user):
        out = execute_read_action("get_service_costs", {"days": 30}, no_perm_user)
        data = json.loads(out)
        assert "error" in data
        assert "total_cost" not in data  # nie ujawniono danych kosztowych

    def test_execute_read_costs_ok_for_viewer(self, cost_viewer):
        out = execute_read_action("get_service_costs", {"days": 30}, cost_viewer)
        data = json.loads(out)
        assert "total_cost" in data  # realne dane, nie odmowa


@pytest.mark.django_db
class TestEmployeeSelfGuard:
    def test_cannot_terminate_self(self):
        admin = User.objects.create_superuser(username="boss1", password="x", email="b1@x.pl")
        out = _execute_terminate_employee({"username": "boss1", "reason": "x"}, admin)
        assert "własnego konta" in out
        admin.refresh_from_db()
        assert admin.is_active  # nietknięty

    def test_cannot_terminate_superuser(self):
        actor = User.objects.create_superuser(username="boss2", password="x", email="b2@x.pl")
        target = User.objects.create_superuser(username="boss3", password="x", email="b3@x.pl")
        out = _execute_terminate_employee({"username": "boss3", "reason": "x"}, actor)
        assert "administratora" in out
        target.refresh_from_db()
        assert target.is_active

    def test_cannot_anonymize_self(self):
        admin = User.objects.create_superuser(username="boss4", password="x", email="b4@x.pl")
        out = _execute_anonymize_employee({"username": "boss4"}, admin)
        assert "własnego konta" in out
        admin.refresh_from_db()
        assert not admin.profile.is_anonymized
