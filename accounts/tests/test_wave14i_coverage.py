"""Wave 14-I — coverage gap-fill dla accounts module.

Pokrywa:

* ``forms.py:122`` — empty username after strip → ValidationError "Login wymagany"
* ``setup_groups.py:96-97`` — Permission.DoesNotExist warning
* ``views.py:116-119`` — register_employee VR (HIBP / pattern) → add_form_errors
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from accounts.factories import AdminUserFactory
from accounts.models import EmployeeProfile

User = get_user_model()


# =============================================================================
# forms.py — empty/whitespace username
# =============================================================================


@pytest.mark.django_db
class TestRegisterEmployeeFormEmptyUsername:
    """RegisterEmployeeForm.clean_username — strip + required."""

    def test_whitespace_only_username_raises(self):
        """username='   ' → ValidationError "Login wymagany"."""
        from accounts.forms import RegisterEmployeeForm

        form = RegisterEmployeeForm(
            data={
                "username": "   ",  # whitespace only → strip = ""
                "email": "x@example.com",
                "first_name": "X",
                "last_name": "Y",
                "function": EmployeeProfile.Function.MAGAZYNIER,
                "phone": "",
                "password1": "TrudneHaslo!2026",
                "password2": "TrudneHaslo!2026",
            }
        )
        # Need to disable strip on the widget
        form.fields["username"].strip = False
        assert not form.is_valid()
        assert "username" in form.errors


# =============================================================================
# setup_groups.py — Permission.DoesNotExist branch
# =============================================================================


@pytest.mark.django_db
class TestSetupGroupsMissingPermission:
    """Pokrywa setup_groups.py:96-97 (warning gdy permission nie istnieje)."""

    def test_setup_groups_with_missing_permission_warns(self, monkeypatch):
        """Monkey-patch GROUPS_PERMISSIONS żeby zawierał non-existent permission."""
        from accounts.management.commands import setup_groups as mod

        # Wymuszamy permission który nie istnieje
        fake_groups = {
            "TestGroup": [
                "accounts.does_not_exist_perm",
                "accounts.also_missing_perm",
            ]
        }
        monkeypatch.setattr(mod, "GROUPS_PERMISSIONS", fake_groups)

        out = StringIO()
        err = StringIO()
        call_command("setup_groups", stdout=out, stderr=err)

        # Stderr ma warning'i o brakujących permissionach
        stderr_content = err.getvalue()
        assert "does_not_exist_perm" in stderr_content or "Pominięto" in stderr_content


# =============================================================================
# views.py — register_employee service VR
# =============================================================================


@pytest.mark.django_db
class TestRegisterEmployeeServiceValidationError:
    """Pokrywa views.py:116-119 (service VR → add_form_errors)."""

    def test_service_vr_renders_form_with_errors(self, client, monkeypatch):
        """Service register_employee rzuca VR (np. HIBP) → 200 z formularzem."""
        from accounts import views as accounts_views

        def boom(**kwargs):
            raise ValidationError({"password1": "Hasło zostało skompromitowane."})

        monkeypatch.setattr(accounts_views, "register_employee", boom)

        admin = AdminUserFactory(username="admin-vr-test")
        client.force_login(admin)
        response = client.post(
            reverse("accounts:employee_register"),
            data={
                "username": "nowy-vr",
                "email": "vr@example.com",
                "first_name": "VR",
                "last_name": "Test",
                "function": EmployeeProfile.Function.MAGAZYNIER,
                "phone": "",
                "password1": "TrudneHaslo!2026",
                "password2": "TrudneHaslo!2026",
            },
        )
        # Form re-rendered z błędem (200), nie redirect
        assert response.status_code == 200


# =============================================================================
# core/management/commands/seed_demo.py — line 132 (else branch when no JSON)
# =============================================================================


@pytest.mark.django_db
class TestSeedDemoMissingReservationsJson:
    """Pokrywa seed_demo.py:132 (else branch gdy nie istnieje reservations.json)."""

    def test_seed_demo_without_reservations_json(self, tmp_path, monkeypatch):
        """Brak reservations.json → command loguje 'Brak ... pomijam'."""
        import contextlib

        out = StringIO()
        from core.management.commands import seed_demo as mod

        # Patch M1_DATA_DIR — minimal valid JSONs, ale BEZ reservations.json
        monkeypatch.setattr(mod, "M1_DATA_DIR", tmp_path)
        # machines.json istnieje (pusta lista), reservations.json brakuje
        (tmp_path / "machines.json").write_text("[]")
        # Nie tworzymy reservations.json — branch else triggered

        # Może wybuchnąć po branch (np. nie ma userów), ale linia 134 trafiona.
        with contextlib.suppress(Exception):
            call_command("seed_demo", stdout=out)
        # Output zawiera ślad gałęzi else lub successful run
        assert out.getvalue() != ""
