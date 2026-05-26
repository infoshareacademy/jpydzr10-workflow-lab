"""Testy admina (django-unfold) dla EmployeeProfile.

Pokrywają bulk actions ``action_terminate`` i ``action_anonymize`` —
sprawdzają, że wywołanie z ModelAdmin faktycznie zmienia stan profili
za pomocą serwisów (terminate_employee / anonymize_employee).
"""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage

from accounts.admin import EmployeeProfileAdmin
from accounts.models import EmployeeProfile
from accounts.services import register_employee

User = get_user_model()


def _request_with_messages(rf, user):
    """Utility: zbuduj request z włączonym messages framework (FallbackStorage)."""
    request = rf.post("/admin/accounts/employeeprofile/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_employee_profile_is_registered_with_admin():
    assert site.is_registered(EmployeeProfile)


@pytest.mark.django_db
def test_action_terminate_calls_service(rf):
    """Bulk action ``action_terminate`` deaktywuje wybrane aktywne profile."""
    superuser = User.objects.create_superuser(username="adm1", password="x", email="a@x.pl")
    p1 = register_employee(username="emp1", email="emp1@x.pl", password="StrongP@ss!1")
    p2 = register_employee(username="emp2", email="emp2@x.pl", password="StrongP@ss!2")

    request = _request_with_messages(rf, superuser)
    admin = EmployeeProfileAdmin(EmployeeProfile, site)
    queryset = EmployeeProfile.objects.filter(pk__in=[p1.pk, p2.pk])
    admin.action_terminate(request, queryset)

    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.is_active_employee is False
    assert p2.is_active_employee is False
    assert p1.termination_date is not None


@pytest.mark.django_db
def test_action_anonymize_calls_service(rf):
    """Bulk action ``action_anonymize`` scrambluje PII wybranych profili."""
    superuser = User.objects.create_superuser(username="adm2", password="x", email="a2@x.pl")
    profile = register_employee(username="orig", email="orig@x.pl", password="StrongP@ss!3")
    original_username = profile.user.username

    request = _request_with_messages(rf, superuser)
    admin = EmployeeProfileAdmin(EmployeeProfile, site)
    queryset = EmployeeProfile.objects.filter(pk=profile.pk)
    admin.action_anonymize(request, queryset)

    profile.refresh_from_db()
    profile.user.refresh_from_db()
    assert profile.is_anonymized is True
    assert profile.user.username != original_username
    assert profile.user.username.startswith("anon-")


@pytest.mark.django_db
def test_action_terminate_skips_already_anonymized(rf):
    """Już zanonimizowane profile są pomijane (filter w action)."""
    from accounts.services import anonymize_employee

    superuser = User.objects.create_superuser(username="adm3", password="x", email="a3@x.pl")
    profile = register_employee(username="emp3", email="emp3@x.pl", password="StrongP@ss!4")
    anonymize_employee(profile)
    profile.refresh_from_db()
    anonymized_at_before = profile.anonymized_at

    request = _request_with_messages(rf, superuser)
    admin = EmployeeProfileAdmin(EmployeeProfile, site)
    queryset = EmployeeProfile.objects.filter(pk=profile.pk)
    # Nie powinno rzucić (filter is_anonymized=False odsiewa).
    admin.action_terminate(request, queryset)

    profile.refresh_from_db()
    assert profile.anonymized_at == anonymized_at_before
