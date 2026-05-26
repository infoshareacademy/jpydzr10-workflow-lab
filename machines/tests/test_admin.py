"""Smoke tests for the django-admin (django-unfold) configuration."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.urls import reverse

from accounts.factories import AdminUserFactory
from machines.factories import MachineFactory
from machines.models import Machine


@pytest.mark.django_db
def test_machine_is_registered_with_admin():
    assert admin.site.is_registered(Machine)


@pytest.mark.django_db
def test_admin_list_view_renders(client):
    superuser = AdminUserFactory()
    MachineFactory(uid="ADM-1", name="Admin test")
    client.force_login(superuser)
    resp = client.get(reverse("admin:machines_machine_changelist"))
    assert resp.status_code == 200
    assert b"ADM-1" in resp.content


@pytest.mark.django_db
def test_admin_change_view_renders(client):
    superuser = AdminUserFactory()
    machine = MachineFactory(uid="ADM-2", name="Drugi")
    client.force_login(superuser)
    resp = client.get(reverse("admin:machines_machine_change", args=[machine.pk]))
    assert resp.status_code == 200
    assert b"ADM-2" in resp.content


@pytest.mark.django_db
def test_admin_history_view_renders(client):
    superuser = AdminUserFactory()
    machine = MachineFactory(uid="ADM-3", name="Trzeci")
    # touch -> trigger history record
    machine.name = "Trzeci nowy"
    machine.save()
    client.force_login(superuser)
    resp = client.get(reverse("admin:machines_machine_history", args=[machine.pk]))
    assert resp.status_code == 200
