"""Lokalne fixtury pytest dla aplikacji chatbot.

Konwencja zgodna z innymi appkami: ``user`` (zalogowany standardowy user)
+ ``client_logged`` (Django Client już zalogowany).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from machines.models import Machine


@pytest.fixture
def user(db):
    """Standardowy zalogowany user — używany przez testy widoków + services."""
    user_model = get_user_model()
    return user_model.objects.create_user(username="tester-chat", password="secret-pw-321!")


@pytest.fixture
def client_logged(client, user):
    """Django ``Client`` już zalogowany jako :func:`user`."""
    client.force_login(user)
    return client


@pytest.fixture
def machine(db):
    """Jedna maszyna magazynowa z UID ``KOP-001``."""
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka chatbot test",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )
