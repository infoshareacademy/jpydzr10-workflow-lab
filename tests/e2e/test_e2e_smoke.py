"""Playwright end-to-end smoke scenarios (DoD 2.3.J).

Three browser scenarios exercising the critical happy paths against a live
dev server:

1. ``test_login_flow`` — log in and land on the dashboard.
2. ``test_reservation_create_form_renders`` — the reservation create form
   renders with its expected fields (machine / dates / person).
3. ``test_timeline_browse`` — the timeline grid renders with its
   period-navigation controls.

All three are marked ``e2e`` and SKIP cleanly when the server is down (the
``goto`` helper raises ``pytest.skip`` on a connection error). Selectors prefer
roles / labels / stable ``name`` attributes so they survive PL↔EN localisation
and markup tweaks.

Run them explicitly::

    make e2e
    # or, with a visible browser:
    uv run pytest tests/e2e/ -m e2e --headed
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import DEMO_PASSWORD, DEMO_USERNAME, goto, login

# ``pytest-playwright`` (and its ``page`` fixture + ``expect`` helper) is an
# optional install. If it is missing the whole module skips, so the suite still
# COLLECTS cleanly without the browser stack present.
expect = pytest.importorskip("playwright.sync_api").expect

if TYPE_CHECKING:  # pragma: no cover — typing only
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_login_flow(page: Page, base_url: str) -> None:
    """Logging in as ``seba2`` redirects to the authenticated dashboard."""
    login(page, base_url, DEMO_USERNAME, DEMO_PASSWORD)

    # We should no longer be on the login page (no password field in the DOM)
    # and the main application nav landmark should be present.
    expect(page.locator("input[name='password']")).to_have_count(0)
    expect(page.get_by_role("navigation").first).to_be_visible()

    # The dashboard greets the user with an <h1> heading ("Witaj" / "Welcome").
    expect(page.get_by_role("heading", level=1).first).to_be_visible()


def test_reservation_create_form_renders(page: Page, base_url: str) -> None:
    """The reservation create form exposes machine, date and person fields."""
    login(page, base_url, DEMO_USERNAME, DEMO_PASSWORD)
    goto(page, f"{base_url}/rezerwacje/dodaj/")

    # Scope to the form that actually owns the machine <select> — the page also
    # contains the search / logout / language forms from the base layout.
    form = page.locator("form:has(select[name='machine'])").first
    expect(form).to_be_visible()

    # Machine is a <select>; the two dates are date inputs; person is a text
    # input. Target by stable Django field ``name`` attributes (i18n-proof).
    expect(form.locator("select[name='machine']")).to_have_count(1)
    expect(form.locator("[name='start_date']")).to_have_count(1)
    expect(form.locator("[name='end_date']")).to_have_count(1)
    expect(form.locator("[name='person']")).to_have_count(1)

    # A submit control is present (we deliberately do NOT submit — that would
    # mutate data; asserting the form renders is the deliverable).
    expect(form.locator("button[type='submit'], input[type='submit']").first).to_be_visible()


def test_timeline_browse(page: Page, base_url: str) -> None:
    """The timeline view renders its grid and period-navigation controls."""
    login(page, base_url, DEMO_USERNAME, DEMO_PASSWORD)
    goto(page, f"{base_url}/rezerwacje/timeline/")

    # The page heading identifies the timeline.
    expect(page.get_by_role("heading", level=1).first).to_be_visible()

    # The timeline grid renders (stable id + ARIA grid role, i18n-proof).
    expect(page.locator("#timeline-grid")).to_have_count(1)
    expect(page.get_by_role("grid").first).to_be_visible()

    # Period-navigation controls: the controls bar holds two labelled groups
    # ("Wybór okresu" + "Nawigacja w czasie"). Assert the bar, its period
    # label, and that at least two control groups are present.
    expect(page.locator("#tl-controls")).to_be_visible()
    expect(page.locator("#tl-period-label")).to_be_visible()
    expect(page.locator("#tl-controls [role='group']")).to_have_count(2)
