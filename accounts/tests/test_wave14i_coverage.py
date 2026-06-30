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

        # Stderr nazywa KONKRETNE brakujące permission (nie samo generyczne
        # słowo "Pominięto" — to przeszłoby też dla pominięcia z innego powodu).
        stderr_content = err.getvalue()
        assert "does_not_exist_perm" in stderr_content
        assert "also_missing_perm" in stderr_content


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
        # Form re-rendered z błędem (200), nie redirect — ORAZ błąd z warstwy
        # serwisu (VR) faktycznie wylądował na polu password1 (add_form_errors).
        # Bez tej asercji widok mógłby renderować pusty formularz, a test by przeszedł.
        assert response.status_code == 200
        form = response.context["form"]
        assert form.errors.get("password1"), "VR powinien trafić na pole password1"
        assert any("skompromitowane" in msg for msg in form.errors["password1"])


# =============================================================================
# core/management/commands/seed_demo.py — line 132 (else branch when no JSON)
# =============================================================================


@pytest.mark.django_db
class TestSeedDemoMissingReservationsJson:
    """Pokrywa gałąź else w ``_import_from_m1`` (brak reservations.json)."""

    def test_seed_demo_import_m1_without_reservations_json_skips(self, tmp_path, monkeypatch):
        """``--import-m1`` z machines.json, ale BEZ reservations.json → gałąź
        else loguje konkretne 'pomijam' i komenda NIE wywraca się.

        Wcześniejsza wersja wołała ``seed_demo`` bez ``--import-m1`` (więc
        ``_import_from_m1`` w ogóle się nie wykonywało!), suppress(Exception)
        łykał błędy, a asercja ``out != ""`` przechodziła dla DOWOLNEGO wyjścia
        — czysty teatr. Teraz realnie wchodzimy w testowaną gałąź i asertujemy
        jej konkretny ślad."""
        out = StringIO()
        from core.management.commands import seed_demo as mod

        monkeypatch.setattr(mod, "M1_DATA_DIR", tmp_path)
        (tmp_path / "machines.json").write_text("[]")
        # reservations.json celowo NIE istnieje → gałąź else.

        call_command("seed_demo", import_m1=True, stdout=out)

        output = out.getvalue()
        assert "reservations.json" in output
        assert "pomijam" in output
