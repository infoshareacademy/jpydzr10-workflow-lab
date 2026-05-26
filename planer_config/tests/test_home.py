"""Testy widoku głównego dashboard.

Wcześniej home() był inline w ``planer_config.urls``, od Wave 4 P0
przeniesiony do ``core.views.home`` z ``@login_required`` (GDPR — wcześniej
anonymous miał wgląd w PII przez listę 5 ostatnich rezerwacji).

Pokrywa lukę z F5-1 / F7-B audytu — home() agreguje 3 zapytaniami KPI dla
maszyn / rezerwacji / budów + recent_reservations. Każdy test izoluje
osobne aspekty: redirect anon, empty stats, aggregated counts,
recent_reservations limit.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from machines.factories import MachineFactory
from machines.models import Machine
from reservations.factories import ConstructionSiteFactory, ReservationFactory
from reservations.models import Reservation


@pytest.fixture
def auth_client(client, db):
    """Client zalogowany jako vanilla user (bez specjalnych perms).

    Wave 4 P0: home wymaga ``@login_required``. Wszystkie testy KPI
    dashboardu muszą zalogować dowolnego usera przed wywołaniem.
    """
    user_model = get_user_model()
    user = user_model.objects.create_user(username="dashboard-test", password="pw-1234!Tajne")
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestHomeView:
    """Suite testów dla ``home()`` (dashboard KPI cards)."""

    def test_home_redirects_anonymous_to_login(self, client):
        """Wave 4 P0 (GDPR): anonymous → 302 redirect do login.

        Wcześniej home() renderował dla anonymous i wyświetlał recent
        reservations z polem ``person`` — wyciek PII.
        """
        resp = client.get(reverse("home"))
        assert resp.status_code == 302
        assert "/login/" in resp.url

    def test_home_renders_for_authenticated(self, auth_client):
        """Zalogowany user dostaje dashboard."""
        resp = auth_client.get(reverse("home"))
        assert resp.status_code == 200

    def test_home_uses_home_template(self, auth_client):
        """Sanity check — widok zwraca template ``home.html``."""
        resp = auth_client.get(reverse("home"))
        templates = [t.name for t in resp.templates if t.name]
        assert "home.html" in templates

    def test_home_empty_stats_when_no_data(self, auth_client):
        """Bez maszyn / rezerwacji / budów KPI dict ma zera wszędzie."""
        resp = auth_client.get(reverse("home"))
        kpi = resp.context["kpi"]
        assert kpi["machines_total"] == 0
        assert kpi["machines_available"] == 0
        assert kpi["machines_on_site"] == 0
        assert kpi["machines_in_service"] == 0
        assert kpi["inspections_overdue"] == 0
        assert kpi["inspections_upcoming"] == 0
        assert kpi["reservations_active"] == 0
        assert kpi["reservations_pending"] == 0
        assert kpi["sites_active"] == 0
        assert list(resp.context["recent_reservations"]) == []

    def test_home_aggregates_counts_correctly(self, auth_client):
        """KPI cards pokazują poprawne licznikim po seedzie 3 maszyny + statusy rezerwacji."""
        # 3 maszyny w magazynie (status default W_MAGAZYNIE).
        machines = [MachineFactory(uid=f"K-{i}") for i in range(3)]
        site = ConstructionSiteFactory(project_number="BUD-2026-501")
        # 2 oczekujące + 1 potwierdzona — wszystkie na różnych maszynach (żeby
        # uniknąć ewentualnych check'ów konfliktu w warstwie modelu).
        for m in machines[:2]:
            ReservationFactory(
                machine=m,
                site=site,
                status=Reservation.Status.OCZEKUJACA,
            )
        # 1 potwierdzona aktywna (start_date <= today, end_date >= today).
        today = date.today()
        ReservationFactory(
            machine=machines[2],
            site=site,
            status=Reservation.Status.POTWIERDZONA,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=2),
        )

        resp = auth_client.get(reverse("home"))
        kpi = resp.context["kpi"]
        assert kpi["machines_total"] == 3
        assert kpi["machines_available"] == 3  # wszystkie W_MAGAZYNIE
        assert kpi["reservations_pending"] == 2
        assert kpi["reservations_active"] == 1
        assert kpi["sites_active"] == 1

    def test_home_recent_reservations_slice_to_5(self, auth_client):
        """``recent_reservations`` zawsze limitowane do 5 — order by -created_at."""
        # 10 maszyn (unique uid) + 10 rezerwacji żeby uniknąć ConflictError.
        site = ConstructionSiteFactory(project_number="BUD-2026-700")
        for i in range(10):
            machine = MachineFactory(uid=f"R-{i:03d}")
            ReservationFactory(
                machine=machine,
                site=site,
                # rozsuwamy daty żeby uniknąć overlap conflict
                start_date=date.today() + timedelta(days=i * 20),
                end_date=date.today() + timedelta(days=i * 20 + 5),
            )

        resp = auth_client.get(reverse("home"))
        recent = list(resp.context["recent_reservations"])
        assert len(recent) == 5
        # check order by -created_at — pierwsza musi być świeższa od ostatniej
        assert recent[0].created_at >= recent[-1].created_at

    def test_home_inspection_overdue_counts_past_dates(self, auth_client):
        """``inspections_overdue`` liczy maszyny z inspection_date < today."""
        past = date.today() - timedelta(days=30)
        future = date.today() + timedelta(days=30)
        MachineFactory(uid="OVD-1", inspection_date=past)
        MachineFactory(uid="OVD-2", inspection_date=past)
        MachineFactory(uid="FUT-1", inspection_date=future)

        resp = auth_client.get(reverse("home"))
        kpi = resp.context["kpi"]
        assert kpi["inspections_overdue"] == 2
        assert kpi["machines_total"] == 3

    def test_home_machine_status_breakdown(self, auth_client):
        """KPI rozdziela maszyny po statusie (W_MAGAZYNIE / NA_BUDOWIE / W_SERWISIE)."""
        MachineFactory(uid="WH-1", status=Machine.Status.W_MAGAZYNIE)
        MachineFactory(uid="WH-2", status=Machine.Status.W_MAGAZYNIE)
        MachineFactory(uid="SI-1", status=Machine.Status.NA_BUDOWIE)
        MachineFactory(uid="SV-1", status=Machine.Status.W_SERWISIE)

        resp = auth_client.get(reverse("home"))
        kpi = resp.context["kpi"]
        assert kpi["machines_available"] == 2
        assert kpi["machines_on_site"] == 1
        assert kpi["machines_in_service"] == 1
