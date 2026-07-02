"""Tests dla home view (dashboard).

Wave 4 P0: home view przeniesiony z ``planer_config/urls.py`` do
``core.views.home`` z ``@login_required`` — wcześniej anonymous miał
wgląd w listę 5 ostatnich rezerwacji z polem ``person`` (PII / GDPR breach).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
class TestHomeViewAuth:
    """Anonymous → redirect do login; logged user → 200."""

    def test_anonymous_redirects_to_login(self, client):
        """Wave 4 P0 (GDPR): anonymous nie widzi PII person field."""
        response = client.get(reverse("home"))
        assert response.status_code == 302
        # Django auth domyślnie redirectuje na /accounts/login/
        assert "/login/" in response.url

    def test_logged_user_gets_200(self, client):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="dashtest", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200
        # Dashboard zawiera KPI cards / brand frazy.
        assert b"<html" in response.content.lower() or b"<body" in response.content.lower()


@pytest.mark.django_db
class TestHomeViewContext:
    """KPI cards + recent_reservations są obliczone poprawnie."""

    def test_kpi_dict_present(self, client):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="kpitest", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200
        # KPI dict istnieje w context.
        ctx = response.context
        assert "kpi" in ctx
        kpi = ctx["kpi"]
        assert "machines_total" in kpi
        assert "reservations_active" in kpi
        assert "sites_active" in kpi

    def test_kpi_reservations_overdue_counts_late_returns(self, client):
        """F-6: KPI ``reservations_overdue`` liczy potwierdzona + end_date < today."""
        from datetime import date, timedelta

        from machines.models import Machine
        from reservations.factories import (
            ConfirmedReservationFactory,
            PendingReservationFactory,
        )

        user_model = get_user_model()
        user = user_model.objects.create_user(username="overduetest", password="pw-1234!Tajne")
        client.force_login(user)

        machine = Machine.objects.create(
            uid="OVD-001",
            name="Test machine",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.NA_BUDOWIE,
        )
        today = date.today()
        # 2 overdue (potwierdzona, end_date < today) → policzone.
        ConfirmedReservationFactory(
            machine=machine,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=2),
        )
        ConfirmedReservationFactory(
            machine=machine,
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=1),
        )
        # Aktywna (end_date >= today) → NIE policzona.
        ConfirmedReservationFactory(
            machine=machine, start_date=today, end_date=today + timedelta(days=3)
        )
        # Pending (status != potwierdzona) → NIE policzona.
        PendingReservationFactory(
            machine=machine,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=2),
        )

        response = client.get(reverse("home"))
        assert response.status_code == 200
        assert response.context["kpi"]["reservations_overdue"] == 2
        # KPI card rendered (Polish text + count).
        assert b"Maszyny do zwrotu" in response.content

    def test_kpi_reservations_overdue_card_hidden_when_zero(self, client):
        """F-6: brak overdue → karta KPI ukryta (warning conditional)."""
        user_model = get_user_model()
        user = user_model.objects.create_user(username="cleantest", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200
        assert response.context["kpi"]["reservations_overdue"] == 0
        # Bez overdue, conditional sekcja nie powinna się renderować.
        assert b"Maszyny do zwrotu" not in response.content


@pytest.mark.django_db
class TestHomeMorningChecklistUX1:
    """Wave 14-F UX-1 — morning checklist (3-column dziś w magazynie).

    Sebastian walkthrough 17 maja 2026: liczby same w sobie (KPI) nie wystarczą
    gdy operator chce zadzwonić do osoby która dziś ma odbierać maszynę.
    Test ekspozycji 3 querysets (starting_today / ending_today / active_today)
    w context home view.
    """

    def test_context_has_morning_checklist_keys(self, client):
        """Empty DB → wszystkie 3 querysets puste, ale klucze present."""
        user_model = get_user_model()
        user = user_model.objects.create_user(username="checklist-empty", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200
        ctx = response.context
        assert "starting_today" in ctx
        assert "ending_today" in ctx
        assert "active_today" in ctx
        # Empty (brak rezerwacji potwierdzonych dziś).
        assert len(list(ctx["starting_today"])) == 0
        assert len(list(ctx["ending_today"])) == 0
        assert len(list(ctx["active_today"])) == 0
        # Empty-state polish text — sprawdzamy że template wyrenderował
        # placeholdery zamiast pominąć sekcję.
        assert b"Dzi\xc5\x9b w magazynie" in response.content

    def test_starting_today_includes_today_start(self, client):
        """Rezerwacja POTWIERDZONA ze start_date=dziś → w starting_today."""
        from datetime import date

        from machines.factories import AvailableMachineFactory
        from reservations.factories import ConfirmedReservationFactory

        user_model = get_user_model()
        user = user_model.objects.create_user(username="checklist-start", password="pw-1234!Tajne")
        client.force_login(user)

        today = date.today()
        machine = AvailableMachineFactory(uid="START-001", name="Test Wyjazd")
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=today,
            end_date=today,
            person="Jan Wyjeżdża",
        )

        response = client.get(reverse("home"))
        assert response.status_code == 200
        starting_pks = [r.pk for r in response.context["starting_today"]]
        assert res.pk in starting_pks
        # Render template — UID i imię osoby widoczne na liście.
        assert b"START-001" in response.content
        # Renderuje sekcję "Wyjeżdżają dziś" (header).
        assert b"Wyje\xc5\xbcd\xc5\xbcaj\xc4\x85 dzi\xc5\x9b" in response.content

    def test_ending_today_includes_today_end(self, client):
        """Rezerwacja POTWIERDZONA z end_date=dziś → w ending_today."""
        from datetime import date, timedelta

        from machines.factories import AvailableMachineFactory
        from reservations.factories import ConfirmedReservationFactory

        user_model = get_user_model()
        user = user_model.objects.create_user(username="checklist-end", password="pw-1234!Tajne")
        client.force_login(user)

        today = date.today()
        machine = AvailableMachineFactory(uid="END-001", name="Test Powrót")
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=today - timedelta(days=5),
            end_date=today,
            person="Anna Wraca",
        )

        response = client.get(reverse("home"))
        ending_pks = [r.pk for r in response.context["ending_today"]]
        assert res.pk in ending_pks
        assert b"END-001" in response.content
        # "Wracają dziś" header rendered.
        assert b"Wracaj\xc4\x85 dzi\xc5\x9b" in response.content

    def test_active_today_includes_in_progress(self, client):
        """Rezerwacja POTWIERDZONA z start<=dziś<=end → w active_today."""
        from datetime import date, timedelta

        from machines.factories import AvailableMachineFactory
        from reservations.factories import ConfirmedReservationFactory

        user_model = get_user_model()
        user = user_model.objects.create_user(username="checklist-active", password="pw-1234!Tajne")
        client.force_login(user)

        today = date.today()
        machine = AvailableMachineFactory(uid="ACT-001", name="Test W Trasie")
        # Start wczoraj, koniec za 5 dni → aktywna dziś (ale NIE starting/ending today).
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=5),
            person="Marek W Trasie",
        )

        response = client.get(reverse("home"))
        active_pks = [r.pk for r in response.context["active_today"]]
        assert res.pk in active_pks
        assert b"ACT-001" in response.content
        assert b"Dzi\xc5\x9b w trasie" in response.content

    def test_morning_checklist_limit_max_5_per_column(self, client):
        """Limit [:5] — gdy >5 rezerwacji, w context jest dokladnie 5."""
        from datetime import date, timedelta

        from machines.factories import AvailableMachineFactory
        from reservations.factories import ConfirmedReservationFactory

        user_model = get_user_model()
        user = user_model.objects.create_user(username="checklist-limit", password="pw-1234!Tajne")
        client.force_login(user)

        today = date.today()
        for i in range(7):
            machine = AvailableMachineFactory(uid=f"LIM-{i:03d}")
            ConfirmedReservationFactory(
                machine=machine,
                start_date=today,
                end_date=today + timedelta(days=i + 1),
            )

        response = client.get(reverse("home"))
        # Wszystkie 7 startują dziś, ale context limit'uje do 5.
        assert len(list(response.context["starting_today"])) == 5


@pytest.mark.django_db
def test_favicon_ico_redirects_to_svg(client):
    """Przeglądarki żądają /favicon.ico z roota mimo <link rel="icon"> na SVG —
    redirect usuwa jedyny 404 w konsoli (dostępny bez logowania)."""
    response = client.get("/favicon.ico")
    assert response.status_code == 301
    assert response.url == "/static/favicon.svg"
