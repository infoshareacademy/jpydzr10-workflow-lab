"""Testy callback'a `core.unfold_dashboard.callback` — KPI cards w unfold admin.

Wave 12 coverage: callback budujący `context['kpi']` z 4 metryk.
"""

from __future__ import annotations

import pytest

from core.unfold_dashboard import callback


@pytest.mark.django_db
def test_callback_returns_context_with_kpi_list():
    """Callback zwraca context z 'kpi' list (4 metryk)."""
    ctx = callback(request=None, context={})
    assert "kpi" in ctx
    assert len(ctx["kpi"]) == 4
    titles = [k["title"] for k in ctx["kpi"]]
    assert "Dostępne maszyny" in titles
    assert "Aktywne rezerwacje" in titles
    assert "Przeglądy przeterminowane" in titles
    assert "Aktywne budowy" in titles


@pytest.mark.django_db
def test_callback_with_data(machine_factory):
    """Wstawiamy maszynę → metric count rośnie."""
    machine_factory(uid="DASH-1")
    ctx = callback(request=None, context={})
    machines_card = next(k for k in ctx["kpi"] if k["title"] == "Dostępne maszyny")
    # Metric to "X / Y" — Y >= 1
    assert "/" in machines_card["metric"]


@pytest.fixture
def machine_factory(db):
    from machines.factories import MachineFactory

    return MachineFactory


def test_callback_handles_db_failure(monkeypatch):
    """Try/except fallback gdy modele rzucają (np. brak migracji)."""
    import core.unfold_dashboard as dash_mod
    from machines.models import Machine

    class BrokenQS:
        def filter(self, *a, **kw):
            raise RuntimeError("DB nie istnieje yet.")

        def count(self):
            raise RuntimeError("Nope")

    # Monkey patch Machine.objects
    monkeypatch.setattr(Machine, "objects", BrokenQS())

    ctx = dash_mod.callback(request=None, context={})
    assert "kpi" in ctx
    # Fallback metryk 0
    machines_card = next(k for k in ctx["kpi"] if k["title"] == "Dostępne maszyny")
    assert "0 / 0" in machines_card["metric"]


def test_callback_handles_reverse_url_failure(monkeypatch):
    """Try/except fallback gdy reverse() rzuca (np. URL nie zarejestrowany)."""
    import core.unfold_dashboard as dash_mod

    def broken_reverse(name, **kwargs):
        from django.urls import NoReverseMatch

        raise NoReverseMatch(f"No URL for {name}")

    monkeypatch.setattr(dash_mod, "reverse", broken_reverse)

    ctx = dash_mod.callback(request=None, context={})
    # Fallback URLs to /admin/
    for card in ctx["kpi"]:
        assert "/admin/" in card["url"]
