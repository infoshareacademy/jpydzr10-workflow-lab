"""Tests for :mod:`core.utils` helpers.

These helpers are shared across apps (reservations timeline + HTMX endpoints
today, more callers may follow), so we exercise the edge cases explicitly:
empty, malformed, well-formed, and explicit fallback paths.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.utils import parse_iso_date


@pytest.mark.parametrize(
    ("raw", "fallback", "expected"),
    [
        # Well-formed ISO date.
        ("2026-05-17", None, date(2026, 5, 17)),
        ("2026-05-17", date(2000, 1, 1), date(2026, 5, 17)),
        # Malformed string → fallback.
        ("invalid", date(2026, 1, 1), date(2026, 1, 1)),
        ("invalid", None, None),
        ("2026-13-99", date(2026, 1, 1), date(2026, 1, 1)),
        # Empty / None → fallback (default None).
        (None, None, None),
        ("", date(2026, 1, 1), date(2026, 1, 1)),
        ("", None, None),
    ],
)
def test_parse_iso_date(raw, fallback, expected):
    """Round-trip tester covering happy path + 3 failure modes."""
    assert parse_iso_date(raw, fallback) == expected


def test_parse_iso_date_handles_non_string_types():
    """Robust to wrong types: e.g. raw=int from accidental request.GET.get coercion."""
    # ``date.fromisoformat`` raises TypeError dla non-string; helper catches it.
    assert parse_iso_date(20260517, date(2026, 1, 1)) == date(2026, 1, 1)  # type: ignore[arg-type]
