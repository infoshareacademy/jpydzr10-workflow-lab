"""Pytest fixtures shared across the machines test suite."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from machines.factories import (
    AvailableMachineFactory,
    InServiceMachineFactory,
    MachineFactory,
    OnSiteMachineFactory,
    OverdueInspectionMachineFactory,
)


@pytest.fixture
def machine(db):
    """A single available machine in the warehouse."""
    return AvailableMachineFactory()


@pytest.fixture
def on_site_machine(db):
    """A machine deployed on a construction site."""
    return OnSiteMachineFactory()


@pytest.fixture
def in_service_machine(db):
    """A machine currently in service."""
    return InServiceMachineFactory()


@pytest.fixture
def overdue_machine(db):
    """A machine whose inspection date has passed."""
    return OverdueInspectionMachineFactory()


@pytest.fixture
def machine_factory(db):
    """Re-export ``MachineFactory`` so tests can build customised instances."""
    return MachineFactory


@pytest.fixture
def user(db):
    """A vanilla, no-permission user account."""
    User = get_user_model()  # noqa: N806 — Django convention for swappable user model
    return User.objects.create_user(username="tester", password="t3ster-pw")


@pytest.fixture
def staff_user(db):
    """A user with full machine CRUD permissions (incl. add/change/delete)."""
    User = get_user_model()  # noqa: N806 — Django convention for swappable user model
    staff = User.objects.create_user(username="operator", password="t3ster-pw", is_staff=True)
    perms = Permission.objects.filter(
        content_type__app_label="machines",
        codename__in=("add_machine", "change_machine", "delete_machine", "view_machine"),
    )
    staff.user_permissions.add(*perms)
    return staff


@pytest.fixture
def auth_client(client, user):
    """Django test client logged in as the vanilla user."""
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(client, staff_user):
    """Django test client logged in as the operator with all machine perms."""
    client.force_login(staff_user)
    return client
