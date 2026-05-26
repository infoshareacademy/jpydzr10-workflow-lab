"""Testy widoku ``employee_register_view`` (Wave 14-F O-1).

Pokrywają:

* GET — renderuje formularz dla zalogowanego usera z permission,
* POST happy-path — tworzy User + EmployeeProfile + redirect do admina,
* POST błąd walidacji — niezgodne hasła, słabe hasło, duplicate username,
* Permission gate — non-admin user dostaje 403,
* Anonymous — redirect na login (LoginRequiredMixin via decorator).

Konwencja: używamy ``UserFactory`` / ``AdminUserFactory`` dla deterministycznych
fixtures (zgodnie z ``accounts/tests/test_views.py``).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from accounts.factories import AdminUserFactory, UserFactory
from accounts.models import EmployeeProfile

User = get_user_model()


# Hasło które przechodzi HIBP + min_length=10 + nie podobne do username.
# „ComplexPass!2026" pojawia się w istniejących testach test_services.py
# (test_register_employee_creates_user_and_profile) — wiemy że HIBP je
# akceptuje, więc bezpieczny re-use.
STRONG_PASSWORD = "ComplexPass!2026"


@pytest.mark.django_db
def test_get_requires_login(client):
    """GET /accounts/pracownicy/dodaj/ bez logowania → redirect na login."""
    resp = client.get(reverse("accounts:employee_register"))
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


@pytest.mark.django_db
def test_get_requires_permission(client):
    """Zalogowany user bez ``add_employeeprofile`` → 403."""
    user = UserFactory(username="brak-permission")
    client.force_login(user)
    resp = client.get(reverse("accounts:employee_register"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_get_renders_form_for_admin(client):
    """Admin (superuser ma all permissions) → 200 + RegisterEmployeeForm w kontekście."""
    admin = AdminUserFactory(username="admin-rejestracji")
    client.force_login(admin)
    resp = client.get(reverse("accounts:employee_register"))
    assert resp.status_code == 200
    assert "form" in resp.context
    # Form ma wszystkie wymagane pola (smoke check).
    form = resp.context["form"]
    assert "username" in form.fields
    assert "email" in form.fields
    assert "first_name" in form.fields
    assert "last_name" in form.fields
    assert "function" in form.fields
    assert "phone" in form.fields
    assert "password1" in form.fields
    assert "password2" in form.fields


@pytest.mark.django_db
def test_post_creates_user_and_redirects(client):
    """POST z poprawnymi danymi → tworzy User + Profile + redirect na admin user change."""
    admin = AdminUserFactory(username="admin-create-ok")
    client.force_login(admin)
    resp = client.post(
        reverse("accounts:employee_register"),
        data={
            "username": "nowy.pracownik",
            "first_name": "Jan",
            "last_name": "Kowalski",
            "email": "jan.kowalski@firma.pl",
            "function": EmployeeProfile.Function.MAGAZYNIER,
            "phone": "+48 600 100 200",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD,
        },
    )
    # Redirect 302 → /admin/auth/user/{id}/change/
    assert resp.status_code == 302
    assert "/admin/auth/user/" in resp["Location"]

    # User został utworzony z poprawnymi danymi.
    user = User.objects.get(username="nowy.pracownik")
    assert user.first_name == "Jan"
    assert user.last_name == "Kowalski"
    assert user.email == "jan.kowalski@firma.pl"
    assert user.is_active is True
    assert user.check_password(STRONG_PASSWORD)

    # Profile podpięty przez signal + zaktualizowany przez service.
    profile = user.profile
    assert profile.function == EmployeeProfile.Function.MAGAZYNIER
    assert profile.phone == "+48 600 100 200"


@pytest.mark.django_db
def test_post_password_mismatch(client):
    """Niezgodne hasła → form błąd przy password2, brak utworzenia usera."""
    admin = AdminUserFactory(username="admin-mismatch")
    client.force_login(admin)
    user_count_before = User.objects.count()
    resp = client.post(
        reverse("accounts:employee_register"),
        data={
            "username": "mismatch-user",
            "first_name": "Anna",
            "last_name": "Nowak",
            "email": "anna.nowak@firma.pl",
            "function": EmployeeProfile.Function.MONTAZYSTA,
            "phone": "",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD + "-different",
        },
    )
    # Brak redirectu → 200 z formularzem.
    assert resp.status_code == 200
    form = resp.context["form"]
    assert form.errors  # są błędy
    assert "password2" in form.errors
    # User NIE został utworzony.
    assert User.objects.count() == user_count_before
    assert not User.objects.filter(username="mismatch-user").exists()


@pytest.mark.django_db
def test_post_duplicate_username(client):
    """Username który już istnieje → form błąd przy username."""
    admin = AdminUserFactory(username="admin-duplicate")
    # Najpierw utwórz usera o nazwie którą zaraz zgłosimy.
    UserFactory(username="zajety")
    client.force_login(admin)
    resp = client.post(
        reverse("accounts:employee_register"),
        data={
            "username": "zajety",
            "first_name": "Piotr",
            "last_name": "Wiśniewski",
            "email": "piotr@firma.pl",
            "function": EmployeeProfile.Function.MONTAZYSTA,
            "phone": "",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD,
        },
    )
    assert resp.status_code == 200
    form = resp.context["form"]
    assert "username" in form.errors


@pytest.mark.django_db
def test_post_invalid_email(client):
    """Nieprawidłowy email → form błąd przy email."""
    admin = AdminUserFactory(username="admin-bad-email")
    client.force_login(admin)
    resp = client.post(
        reverse("accounts:employee_register"),
        data={
            "username": "niepoprawny-email",
            "first_name": "Test",
            "last_name": "Test",
            "email": "not-an-email",
            "function": EmployeeProfile.Function.MONTAZYSTA,
            "phone": "",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD,
        },
    )
    assert resp.status_code == 200
    form = resp.context["form"]
    assert "email" in form.errors


@pytest.mark.django_db
def test_post_short_password(client):
    """Hasło krótsze niż 10 znaków → form błąd (min_length validation)."""
    admin = AdminUserFactory(username="admin-short-pwd")
    client.force_login(admin)
    resp = client.post(
        reverse("accounts:employee_register"),
        data={
            "username": "krotkie-haslo",
            "first_name": "Test",
            "last_name": "Test",
            "email": "test@example.com",
            "function": EmployeeProfile.Function.MONTAZYSTA,
            "phone": "",
            "password1": "abc123",
            "password2": "abc123",
        },
    )
    assert resp.status_code == 200
    form = resp.context["form"]
    assert "password1" in form.errors or "password2" in form.errors


@pytest.mark.django_db
def test_post_with_explicit_permission_not_superuser(client):
    """User z dokładnie ``add_employeeprofile`` (NIE superuser) → 200 GET."""
    user = UserFactory(username="kierownik-permission")
    perm = Permission.objects.get(codename="add_employeeprofile")
    user.user_permissions.add(perm)
    client.force_login(user)
    resp = client.get(reverse("accounts:employee_register"))
    assert resp.status_code == 200
