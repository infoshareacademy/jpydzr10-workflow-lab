"""Testy sygnałów aplikacji accounts (sync grup RBAC po zmianach EmployeeProfile).

Sygnał ``sync_groups_on_employee_save`` mapuje ``EmployeeProfile.function``
na członkostwo w :class:`django.contrib.auth.models.Group` za pomocą
:data:`accounts.services.FUNCTION_GROUP_MAP`. Anonimizacja i deaktywacja
pracownika czyszczą wszystkie zarządzane grupy (defence-in-depth dla RBAC).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()


@pytest.mark.django_db
def test_signal_adds_group_for_magazynier():
    """Nowy profil z function="magazynier" → user dostaje grupę "Magazynierzy"."""
    user = User.objects.create_user(username="mag1", password="x")
    profile = user.profile
    profile.function = "magazynier"
    profile.save()
    group_names = set(user.groups.values_list("name", flat=True))
    assert "Magazynierzy" in group_names


@pytest.mark.django_db
def test_signal_adds_group_for_admin():
    """Profil z function="admin" → user dostaje grupę "Administratorzy"."""
    user = User.objects.create_user(username="adm1", password="x")
    profile = user.profile
    profile.function = "admin"
    profile.save()
    assert user.groups.filter(name="Administratorzy").exists()


@pytest.mark.django_db
def test_signal_admin_function_transition():
    """Pełna macierz przejść z udziałem ADMIN: admin → magazynier → admin.

    Sygnał musi sprzątać grupę Administratorzy przy zejściu z funkcji ADMIN
    i ponownie ją nadać przy powrocie — bez pozostawiania osieroconej grupy.
    """
    user = User.objects.create_user(username="admswap", password="x")
    profile = user.profile

    profile.function = "admin"
    profile.save()
    assert set(user.groups.values_list("name", flat=True)) == {"Administratorzy"}

    profile.function = "magazynier"
    profile.save()
    names = set(user.groups.values_list("name", flat=True))
    assert "Administratorzy" not in names
    assert names == {"Magazynierzy"}

    profile.function = "admin"
    profile.save()
    assert set(user.groups.values_list("name", flat=True)) == {"Administratorzy"}


@pytest.mark.django_db
def test_signal_swaps_groups_on_function_change():
    """Zmiana z "magazynier" → "kierownik" usuwa starą grupę, dodaje nową."""
    user = User.objects.create_user(username="swap1", password="x")
    profile = user.profile
    profile.function = "magazynier"
    profile.save()
    assert "Magazynierzy" in set(user.groups.values_list("name", flat=True))

    profile.function = "kierownik"
    profile.save()
    group_names = set(user.groups.values_list("name", flat=True))
    assert "Magazynierzy" not in group_names
    assert "Kierownicy" in group_names


@pytest.mark.django_db
def test_signal_clears_groups_when_inactive():
    """Deaktywacja pracownika (is_active_employee=False) czyści wszystkie grupy."""
    user = User.objects.create_user(username="inact1", password="x")
    profile = user.profile
    profile.function = "admin"
    profile.save()
    assert "Administratorzy" in set(user.groups.values_list("name", flat=True))

    profile.is_active_employee = False
    profile.save()
    assert user.groups.count() == 0


@pytest.mark.django_db
def test_signal_clears_groups_when_anonymized():
    """Anonimizacja profilu (is_anonymized=True) czyści wszystkie grupy."""
    user = User.objects.create_user(username="anon1", password="x")
    profile = user.profile
    profile.function = "magazynier"
    profile.save()
    assert user.groups.count() > 0

    profile.is_anonymized = True
    profile.save()
    assert user.groups.count() == 0


@pytest.mark.django_db
def test_signal_preserves_unmanaged_groups():
    """Grupy spoza FUNCTION_GROUP_MAP (np. ad-hoc "Audytorzy") nie są usuwane."""
    user = User.objects.create_user(username="aud1", password="x")
    ad_hoc = Group.objects.create(name="Audytorzy")
    user.groups.add(ad_hoc)
    profile = user.profile
    profile.function = "magazynier"
    profile.save()
    group_names = set(user.groups.values_list("name", flat=True))
    assert "Audytorzy" in group_names
    assert "Magazynierzy" in group_names
