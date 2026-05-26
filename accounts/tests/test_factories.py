"""Smoke testy dla accounts.factories — sanity check ``UserFactory`` &co.

Sprawdza tylko że factory tworzą validne obiekty + minimalne defaults. Logikę
biznesową (signal create_profile, sync_groups) pokrywają ``test_signals.py``
i ``test_services.py``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from accounts.factories import AdminUserFactory, EmployeeProfileFactory, UserFactory
from accounts.models import EmployeeProfile

User = get_user_model()


@pytest.mark.django_db
def test_user_factory_creates_active_user():
    """``UserFactory()`` produkuje aktywnego, non-staff usera z polskim imieniem."""
    user = UserFactory()
    assert user.pk is not None
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.first_name  # Polish Faker — nie pusty


@pytest.mark.django_db
def test_user_factory_signal_creates_profile():
    """Sygnał post_save tworzy profil automatycznie dla usera z factory."""
    user = UserFactory()
    assert hasattr(user, "profile")
    assert isinstance(user.profile, EmployeeProfile)


@pytest.mark.django_db
def test_user_factory_username_sequence_unique():
    """Kolejne wywołania dają unique username (sequence)."""
    u1 = UserFactory()
    u2 = UserFactory()
    assert u1.username != u2.username


@pytest.mark.django_db
def test_user_factory_email_derived_from_username():
    """``email`` powinien być spójny z ``username`` (LazyAttribute)."""
    user = UserFactory(username="testowy")
    assert user.email == "testowy@example.pl"


@pytest.mark.django_db
def test_admin_user_factory_creates_superuser():
    """``AdminUserFactory`` daje is_staff + is_superuser."""
    admin = AdminUserFactory()
    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.username.startswith("admin")


@pytest.mark.django_db
def test_employee_profile_factory_creates_profile_with_function():
    """``EmployeeProfileFactory`` ustawia function=MAGAZYNIER (override default)."""
    # signal już tworzy profil — używamy istniejącego usera + update via SubFactory
    profile = EmployeeProfileFactory.build()
    assert profile.function == EmployeeProfile.Function.MAGAZYNIER
    assert profile.is_active_employee is True
