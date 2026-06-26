"""Local conftest for the service test suite."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from machines.models import Machine


@pytest.fixture
def machine(db):
    """A single warehouse machine — receiver of service records in tests."""
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka demo",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def second_machine(db):
    """A second warehouse machine — for cross-machine list / bulk tests."""
    return Machine.objects.create(
        uid="KOP-002",
        name="Druga koparka",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def user(db):
    """A standard authenticated user — used by view tests.

    Otrzymuje uprawnienia ``add_servicerecord`` + ``delete_servicerecord``,
    bo widoki CreateView/DeleteView są chronione ``PermissionRequiredMixin``
    (fix F7-A). Bez tych uprawnień testy CREATE/DELETE dostałyby 403.
    """
    user_model = get_user_model()
    user_obj = user_model.objects.create_user(username="tester", password="secret-pw-123!")
    perms = Permission.objects.filter(
        content_type__app_label="service",
        codename__in=(
            "view_servicerecord",
            "add_servicerecord",
            "change_servicerecord",
            "delete_servicerecord",
        ),
    )
    user_obj.user_permissions.add(*perms)
    return user_obj


@pytest.fixture
def auth_client(client, user):
    """A Django ``Client`` already logged in as :func:`user`."""
    client.force_login(user)
    return client


@pytest.fixture
def regular_user(db):
    """Authenticated user BEZ żadnych service permissions.

    Używane w permission tests (Wave 4 E2 P1 #7) — weryfikuje że
    PermissionRequiredMixin daje 403 zamiast pozwolić zalogowanemu
    bez `service.add_servicerecord` na bulk inspection.
    """
    user_model = get_user_model()
    return user_model.objects.create_user(username="noperm", password="secret-pw-456!")
