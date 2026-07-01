"""Generic utility helpers shared across apps.

These functions intentionally have **no Django dependency** beyond the
standard library — they are imported from views/services/tools across the
project and must not pull in app-specific models or settings.
"""

from __future__ import annotations

from datetime import date


def parse_iso_date(raw: str | None, fallback: date | None = None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` date string, returning ``fallback`` on error.

    Wave 4 E2 P1 #11 dedupe: previously :mod:`reservations.views` shipped two
    near-identical helpers (``_safe_iso_date`` and ``_parse_iso_date``) with
    subtly different fallback semantics. Centralising them here gives every
    caller one canonical helper with explicit fallback handling.

    Args:
        raw: Candidate ISO-date string (e.g. ``"2026-05-17"``). ``None`` or an
            empty string is treated as "missing".
        fallback: Value returned when ``raw`` is missing or malformed.
            Defaults to ``None`` so legacy callers that expect ``None`` on
            failure (the old ``_safe_iso_date`` shape) still work.

    Returns:
        Parsed :class:`datetime.date`, or ``fallback`` when parsing fails.
    """
    if not raw:
        return fallback
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return fallback
