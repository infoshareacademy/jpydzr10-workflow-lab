"""Testy management commands aplikacji accounts.

Aktualnie pokryte:

* ``setup_groups`` — tworzy 3 grupy RBAC i przypisuje permissions zgodnie
  z :data:`FUNCTION_GROUP_MAP`. Montażyści (default function) nie dostaje
  grupy — read-only access przez login_required wystarczy.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command


@pytest.mark.django_db
class TestSetupGroupsCommand:
    """``setup_groups`` jest idempotent i tworzy 3 standardowe role."""

    def _run(self) -> str:
        out = StringIO()
        call_command("setup_groups", stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_creates_three_groups(self):
        # Grupy są tworzone już przez migrację RBAC, więc setup_groups działa
        # tu jako re-sync (idempotentny) — sprawdzamy obecność grup i to, że
        # komenda raportuje synchronizację uprawnień Magazynierów.
        output = self._run()
        names = set(Group.objects.values_list("name", flat=True))
        assert {"Magazynierzy", "Kierownicy", "Administratorzy"} <= names
        assert "Magazynierzy:" in output

    def test_magazynierzy_have_reservation_perms(self):
        self._run()
        magazynierzy = Group.objects.get(name="Magazynierzy")
        codes = set(magazynierzy.permissions.values_list("codename", flat=True))
        assert "add_reservation" in codes
        assert "change_reservation" in codes
        assert "delete_reservation" in codes
        assert "view_constructionsite" in codes

    def test_kierownicy_can_delete_sites(self):
        """Kierownicy mają delete_constructionsite (do anulowania projektów)."""
        self._run()
        kierownicy = Group.objects.get(name="Kierownicy")
        codes = set(kierownicy.permissions.values_list("codename", flat=True))
        assert "delete_constructionsite" in codes
        assert "add_reservation" in codes

    def test_administratorzy_have_everything_in_domain_apps(self):
        self._run()
        admini = Group.objects.get(name="Administratorzy")
        # Pełny zestaw permissions z 4 aplikacji domenowych.
        total = Permission.objects.filter(
            content_type__app_label__in=("machines", "reservations", "service", "accounts")
        ).count()
        assert admini.permissions.count() == total

    def test_idempotent(self):
        """Drugie wywołanie nie psuje istniejących grup."""
        self._run()
        first_count = Group.objects.count()
        self._run()
        assert Group.objects.count() == first_count
