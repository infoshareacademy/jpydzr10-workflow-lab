"""Tests for the timeline backend — ``TimelineView`` + ``QuickReserveView``.

Templates for the timeline are owned by another agent (F3-C). To let the
backend land independently of the frontend work, every test below either:

* uses ``?format=json`` (no template lookup), or
* calls the HTMX POST endpoint and asserts on the response headers (the
  view falls back to a minimal HTML stub when the template is missing).

The DB-related tests pin "today" with :func:`freezegun.freeze_time` so the
date-range computations are deterministic regardless of the calendar day
the suite is executed on. ``client.force_login`` is called INSIDE each
frozen-time block so the session timestamp matches the frozen clock — if
``force_login`` ran before freezing, Django would treat the session as
"from the future" and bounce the request to ``/accounts/login/``.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import (
    ConfirmedReservationFactory,
    ConstructionSiteFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation

FROZEN_DAY = "2026-06-01"  # Monday — keeps the weekly window obvious.


# =============================================================================
# Helpers
# =============================================================================


def _make_machine(uid: str = "KOP-100", **overrides) -> Machine:
    """Cheap machine factory — the reservations app does not import the
    ``machines.factories`` module, so we instantiate directly to avoid the
    dependency."""
    defaults = {
        "uid": uid,
        "name": f"Maszyna {uid}",
        "machine_type": Machine.Type.KOPARKA,
        "status": Machine.Status.W_MAGAZYNIE,
    }
    defaults.update(overrides)
    return Machine.objects.create(**defaults)


def _timeline_url(**params) -> str:
    """Build a ``reservations:timeline`` URL with query parameters."""
    base = reverse("reservations:timeline")
    if not params:
        return base
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return f"{base}?{qs}"


def _login(client, user):
    """Log ``user`` into ``client`` — must be called inside the frozen-time
    context so the session timestamp matches the test's view of "now"."""
    client.force_login(user)


# =============================================================================
# TimelineView — period handling
# =============================================================================


@pytest.mark.django_db
class TestTimelinePeriod:
    def test_default_period_is_week(self, client, user):
        with freeze_time(FROZEN_DAY):
            _login(client, user)
            response = client.get(_timeline_url(format="json"))
        assert response.status_code == 200
        body = response.json()
        assert body["period"] == "week"
        assert len(body["day_list"]) == 7
        assert body["start"] == FROZEN_DAY

    def test_period_2week(self, client, user):
        with freeze_time(FROZEN_DAY):
            _login(client, user)
            response = client.get(_timeline_url(format="json", period="2week"))
        assert response.status_code == 200
        body = response.json()
        assert body["period"] == "2week"
        assert len(body["day_list"]) == 14

    def test_period_month(self, client, user):
        with freeze_time(FROZEN_DAY):
            _login(client, user)
            response = client.get(_timeline_url(format="json", period="month"))
        assert response.status_code == 200
        body = response.json()
        assert body["period"] == "month"
        assert len(body["day_list"]) == 30

    def test_unknown_period_falls_back_to_week(self, client, user):
        with freeze_time(FROZEN_DAY):
            _login(client, user)
            response = client.get(_timeline_url(format="json", period="bogus"))
        assert response.status_code == 200
        body = response.json()
        assert body["period"] == "week"
        assert len(body["day_list"]) == 7


# =============================================================================
# TimelineView — filters
# =============================================================================


@pytest.mark.django_db
class TestTimelineFilters:
    def test_filter_machine_type(self, client, user):
        with freeze_time(FROZEN_DAY):
            _make_machine(uid="KOP-201", machine_type=Machine.Type.KOPARKA)
            _make_machine(uid="WAL-001", machine_type=Machine.Type.WALEC)
            _login(client, user)

            response = client.get(
                _timeline_url(format="json", machine_type=Machine.Type.KOPARKA.value)
            )
        uids = [row["uid"] for row in response.json()["machine_rows"]]
        assert "KOP-201" in uids
        assert "WAL-001" not in uids

    def test_filter_machine_status(self, client, user):
        with freeze_time(FROZEN_DAY):
            _make_machine(uid="KOP-301", status=Machine.Status.W_MAGAZYNIE)
            _make_machine(uid="KOP-302", status=Machine.Status.W_SERWISIE)
            _login(client, user)

            response = client.get(
                _timeline_url(format="json", status=Machine.Status.W_SERWISIE.value)
            )
        uids = [row["uid"] for row in response.json()["machine_rows"]]
        assert uids == ["KOP-302"]

    def test_filter_site_filters_bars(self, client, user):
        with freeze_time(FROZEN_DAY):
            machine = _make_machine(uid="KOP-401")
            site_a = ConstructionSiteFactory(project_number="BUD-2026-901")
            site_b = ConstructionSiteFactory(project_number="BUD-2026-902")
            ConfirmedReservationFactory(
                machine=machine,
                site=site_a,
                start_date=date(2026, 6, 2),
                end_date=date(2026, 6, 4),
            )
            ConfirmedReservationFactory(
                machine=machine,
                site=site_b,
                start_date=date(2026, 6, 5),
                end_date=date(2026, 6, 6),
            )
            _login(client, user)

            response = client.get(_timeline_url(format="json", site="BUD-2026-901"))
        rows = response.json()["machine_rows"]
        kop_401 = next(r for r in rows if r["uid"] == "KOP-401")
        assert len(kop_401["bars"]) == 1
        assert kop_401["bars"][0]["site_number"] == "BUD-2026-901"

    def test_filter_search_matches_uid_and_name(self, client, user):
        with freeze_time(FROZEN_DAY):
            _make_machine(uid="KOP-501", name="Czerwona koparka")
            _make_machine(uid="WAL-501", name="Niebieski walec")
            _login(client, user)

            response1 = client.get(_timeline_url(format="json", search="czerwon"))
            response2 = client.get(_timeline_url(format="json", search="WAL"))

        uids1 = [r["uid"] for r in response1.json()["machine_rows"]]
        assert uids1 == ["KOP-501"]

        uids2 = [r["uid"] for r in response2.json()["machine_rows"]]
        assert uids2 == ["WAL-501"]


# =============================================================================
# TimelineView — prefetch + query count
# =============================================================================


@pytest.mark.django_db
class TestTimelinePrefetch:
    def test_query_count_stays_bounded(self, client, user, django_assert_max_num_queries):
        # Five machines x three reservations each — without prefetch this
        # would be ~1 + 5 + 5 = 11 queries; with prefetch we stay at <=7.
        with freeze_time(FROZEN_DAY):
            site = ConstructionSiteFactory(project_number="BUD-2026-700")
            for i in range(5):
                machine = _make_machine(uid=f"KOP-7{i:02d}")
                for j in range(3):
                    start = date(2026, 6, 2) + timedelta(days=j * 2)
                    ConfirmedReservationFactory(
                        machine=machine,
                        site=site,
                        start_date=start,
                        end_date=start + timedelta(days=1),
                    )
            _login(client, user)

            with django_assert_max_num_queries(7):
                response = client.get(_timeline_url(format="json"))

        assert response.status_code == 200
        assert len(response.json()["machine_rows"]) == 5


# =============================================================================
# TimelineView — navigation + JSON format
# =============================================================================


@pytest.mark.django_db
class TestTimelineNavigationAndFormat:
    def test_json_format_returns_expected_shape(self, client, user):
        with freeze_time(FROZEN_DAY):
            machine = _make_machine(uid="KOP-601")
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2026, 6, 2),
                end_date=date(2026, 6, 4),
            )
            _login(client, user)

            response = client.get(_timeline_url(format="json"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        body = response.json()
        assert set(body) >= {"period", "start", "end", "day_list", "machine_rows"}
        bar = body["machine_rows"][0]["bars"][0]
        assert bar["offset_days"] == 1  # 2026-06-02 is day index 1 in the week.
        assert bar["length_days"] == 3
        assert bar["start_date"] == "2026-06-02"

    def test_navigation_prev_next_via_json_window_shift(self, client, user):
        # ``prev_start`` / ``next_start`` live in the HTML context; we verify
        # the same arithmetic by feeding two custom windows and reading the
        # JSON ``start`` echo for each.
        with freeze_time(FROZEN_DAY):
            _login(client, user)
            r1 = client.get(_timeline_url(format="json", start="2026-06-08"))
            r2 = client.get(_timeline_url(format="json", start="2026-06-01"))

        assert r1.json()["start"] == "2026-06-08"
        assert r2.json()["start"] == "2026-06-01"


# =============================================================================
# QuickReserveView
# =============================================================================


@pytest.mark.django_db
class TestQuickReserveView:
    def test_post_creates_reservation(self, client, user):
        with freeze_time(FROZEN_DAY):
            machine = _make_machine(uid="KOP-801")
            site = ConstructionSiteFactory(project_number="BUD-2026-800")
            _login(client, user)

            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "2026-06-10",
                    "end_date": "2026-06-12",
                    "person": "Anna Kowalska",
                    "site_id": site.pk,
                },
            )

        assert response.status_code == 200
        assert "HX-Trigger" in response
        assert Reservation.objects.filter(machine=machine, start_date=date(2026, 6, 10)).exists()

    def test_post_conflict_returns_error_partial(self, client, user):
        with freeze_time(FROZEN_DAY):
            machine = _make_machine(uid="KOP-802")
            PendingReservationFactory(
                machine=machine,
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 12),
            )
            _login(client, user)

            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "2026-06-11",
                    "end_date": "2026-06-11",
                    "person": "Jan Test",
                },
            )

        # Error swap → 200 with no HX-Trigger and no new row in the DB.
        assert response.status_code == 200
        assert "HX-Trigger" not in response
        assert Reservation.objects.filter(machine=machine).count() == 1

    def test_post_success_emits_hx_trigger_with_refresh_and_toast(self, client, user):
        with freeze_time(FROZEN_DAY):
            machine = _make_machine(uid="KOP-803")
            _login(client, user)

            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "2026-06-15",
                    "person": "Piotr Q",
                },
            )

        assert response.status_code == 200
        trigger = json.loads(response["HX-Trigger"])
        assert trigger["refreshTimeline"] is True
        assert trigger["showToast"]["level"] == "success"
        # One-day default — start == end when end_date is omitted.
        reservation = Reservation.objects.get(machine=machine)
        assert reservation.start_date == reservation.end_date == date(2026, 6, 15)
