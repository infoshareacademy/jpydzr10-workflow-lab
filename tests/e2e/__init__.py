"""End-to-end (Playwright) tests run against a LIVE dev server.

These tests are guarded so that if the development server is not running at
``base_url`` they SKIP cleanly instead of failing — see the connection-error
guard in :mod:`tests.e2e.conftest` and :mod:`tests.e2e.test_e2e_smoke`.
"""
