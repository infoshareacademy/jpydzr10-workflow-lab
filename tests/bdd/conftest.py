"""Pytest fixtures współdzielone dla scenariuszy BDD (pytest-bdd).

Konwencja:

* ``magazynier`` — domyślny user "operator magazynu" do scenariuszy które
  wymagają zalogowanej sesji (timeline browsing, quick-reserve).
* ``authenticated_client`` — django.test.Client zalogowany jako magazynier.
* ``context`` — pusty słownik per-scenariusz; step impls trzymają w nim
  obiekty domenowe (machine, reservation, response) między given / when /
  then. Każdy scenariusz dostaje świeży dict (scope="function" — domyślny).

Wszystkie scenariusze BDD trzymamy w ``tests/bdd/features/`` (Polish Gherkin),
a step implementations w ``tests/bdd/steps/test_*.py``. ``pyproject.toml``
ustawia ``bdd_features_base_dir`` żeby ``scenarios("../features/X.feature")``
działało z dowolnego step modułu.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def context() -> dict:
    """Pusty pojemnik na obiekty współdzielone przez kroki scenariusza."""
    return {}


@pytest.fixture
def magazynier(db):
    """Domyślny user (operator magazynu) używany w scenariuszach z login."""
    user_model = get_user_model()
    return user_model.objects.create_user(
        username="magazynier",
        password="Tajne123!Pass",  # zgodne z MinLength=10 + uniknięcie HIBP w prod
        first_name="Jan",
        last_name="Kowalski",
    )


@pytest.fixture
def authenticated_client(client, magazynier):
    """Django test client zalogowany jako ``magazynier``."""
    client.force_login(magazynier)
    return client
