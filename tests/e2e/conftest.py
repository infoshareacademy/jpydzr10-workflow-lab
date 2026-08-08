"""Fixtures shared by the Playwright end-to-end smoke tests.

The E2E suite talks to a *running* development server (``make run`` →
http://localhost:8002). Because that server is not part of the in-process
pytest fixtures, every test must degrade gracefully when it is down: the
``goto`` helper turns a connection error into a clear ``pytest.skip`` rather
than a hard failure. This keeps ``make test`` / CI green even though the e2e
marker is collected by default (the global pytest config does not filter it).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

# Playwright (provided by the ``pytest-playwright`` plugin) is only needed when
# the E2E suite actually runs. Import it lazily so the suite still COLLECTS
# cleanly on machines / CI runners where the browser stack is not installed —
# in that case the tests skip rather than erroring at import time.
try:
    from playwright.sync_api import Error as PlaywrightError
except ModuleNotFoundError:  # pragma: no cover — depends on optional install
    PlaywrightError = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:  # pragma: no cover — typing only
    from playwright.sync_api import Page

DEFAULT_BASE_URL = "http://localhost:8002"

# Demo credentials seeded by ``manage.py seed_demo`` (password shared across the
# four demo roles in the dev environment). ``mag`` is the warehouse keeper —
# enough privilege to reach the dashboard, timeline and reservation form.
DEMO_USERNAME = "mag"
DEMO_PASSWORD = "Planer2026!"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Root URL of the running dev server.

    Defaults to :data:`DEFAULT_BASE_URL`; override with the ``E2E_BASE_URL``
    environment variable (e.g. to point at a staging instance or a different
    local port).
    """
    return os.environ.get("E2E_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def goto(page: Page, url: str) -> None:
    """Navigate to ``url``, skipping the test if the server is unreachable.

    Playwright raises :class:`~playwright.sync_api.Error` (``ERR_CONNECTION_REFUSED``
    and friends) when nothing is listening. We translate that into a skip so the
    suite is safe to collect/run without a live server.
    """
    # ``PlaywrightError`` is the precise connection-error type; fall back to
    # ``Exception`` if Playwright was not importable (the module would already
    # be skipped in that case, so this branch is purely defensive).
    nav_error = PlaywrightError if PlaywrightError is not None else Exception
    try:
        page.goto(url, wait_until="domcontentloaded")
    except nav_error as exc:  # pragma: no cover — only hit when server down
        message = str(exc).lower()
        if any(
            token in message
            for token in ("connection refused", "err_connection", "econnrefused", "timeout")
        ):
            pytest.skip(f"dev server not running at {url} — start it with `make run`")
        raise


def login(page: Page, base_url: str, username: str, password: str) -> None:
    """Log in through the real login form and land on the dashboard.

    Targets inputs by their stable Django ``name`` attributes (``username`` /
    ``password``) so the helper is resilient to PL/EN UI localisation.
    """
    goto(page, f"{base_url}/accounts/login/")
    form = page.locator("form:has(input[name='password'])").first
    form.locator("input[name='username']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
