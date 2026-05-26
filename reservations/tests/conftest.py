"""Local conftest for the reservations test suite.

Provides reusable fixtures (a fresh machine + active site) so individual
tests do not have to re-create the same objects each time.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from machines.models import Machine
from reservations.factories import ConstructionSiteFactory


def _grant_reservation_perms(user) -> None:
    """Helper: nadaje userowi pełen zestaw perm na Reservation + ConstructionSite.

    Używane przez ``user`` fixture, żeby istniejące widok-testy (które
    używają ``client_logged``) nie wybuchały po dodaniu ``permission_required``
    do widoków zapisujących (C2-3 P0 SECURITY + Wave 4 P0 site CRUD).
    """
    perms = Permission.objects.filter(
        content_type__app_label="reservations",
        codename__in=(
            "add_reservation",
            "change_reservation",
            "delete_reservation",
            "add_constructionsite",
            "change_constructionsite",
            "delete_constructionsite",
        ),
    )
    user.user_permissions.add(*perms)


@pytest.fixture
def user(db):
    """A standard authenticated user — used by view tests.

    Posiada perm ``reservations.{add,change,delete}_reservation`` żeby
    istniejące testy widoków (create/update/confirm/cancel/complete)
    przeszły bez przepisywania na poziom group/RBAC.
    """
    user_model = get_user_model()
    user = user_model.objects.create_user(username="tester", password="secret-pw-123!")
    _grant_reservation_perms(user)
    return user


@pytest.fixture
def user_no_perms(db):
    """Authenticated user BEZ perm na rezerwacje — dla testów 403."""
    user_model = get_user_model()
    return user_model.objects.create_user(
        username="no-perms",
        password="secret-pw-123!",
    )


@pytest.fixture
def client_logged(client, user):
    """A Django ``Client`` already logged in as :func:`user`."""
    client.force_login(user)
    return client


@pytest.fixture
def client_no_perms(client, user_no_perms):
    """Logged-in client without reservation permissions — dla testów 403."""
    client.force_login(user_no_perms)
    return client


@pytest.fixture
def machine(db):
    """A single warehouse machine, ready for booking."""
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka demo",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def second_machine(db):
    """A second warehouse machine — for cross-machine conflict tests."""
    return Machine.objects.create(
        uid="KOP-002",
        name="Druga koparka",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def site(db):
    """A single active construction site (BUD-2026-001 by default)."""
    return ConstructionSiteFactory(project_number="BUD-2026-001")
