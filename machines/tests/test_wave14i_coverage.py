"""Wave 14-I — coverage gap-fill dla machines module.

Pokrywa pozostałe missed branches:

* ``views.py`` line 119 — _apply_inspection_filter default return (fallthrough
  na unknown bucket) — defensive code, testowane bezpośrednim wywołaniem.
"""

from __future__ import annotations

from datetime import date

import pytest

from machines.models import Machine
from machines.views import _apply_inspection_filter


@pytest.mark.django_db
class TestApplyInspectionFilterDefault:
    """``_apply_inspection_filter`` — defensive default fallthrough."""

    def test_unknown_bucket_returns_unchanged_queryset(self):
        """Bucket 'foo' (nieznany) → return queryset bez zmian."""
        Machine.objects.create(
            uid="DEF-001",
            name="Default test",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
            inspection_date=date(2027, 1, 1),
        )
        Machine.objects.create(
            uid="DEF-002",
            name="Default test 2",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
            inspection_date=None,
        )
        qs = Machine.objects.all()
        result = _apply_inspection_filter(qs, "non-existent-bucket")
        # Bez zmian → wszystkie maszyny widoczne
        assert result.count() == 2

    def test_empty_bucket_returns_unchanged_queryset(self):
        """Bucket '' (empty) → return queryset bez zmian."""
        Machine.objects.create(
            uid="EMP-001",
            name="Empty bucket",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        qs = Machine.objects.all()
        result = _apply_inspection_filter(qs, "")
        assert result.count() == 1
