"""Wspólne funkcje narzędziowe używane przez różne moduły."""

import uuid
from datetime import date, datetime


def parse_date(date_str: str) -> date:
    """Konwertuje string RRRR-MM-DD na obiekt date."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def generate_id(prefix: str) -> str:
    """Generuje unikalny identyfikator z prefiksem (np. RES-, SRV-)."""
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


def generate_unique_id(
    prefix: str,
    existing_ids: set[str] | list[str],
    max_attempts: int = 1000,
) -> str:
    """Generuje unikalny ID, sprawdzając czy nie istnieje już na liście.

    Args:
        prefix: Prefiks identyfikatora (np. 'RES-', 'SRV-')
        existing_ids: Zbiór (set) lub lista istniejących ID-ków
        max_attempts: Maksymalna liczba prób (zabezpieczenie przed nieskończoną pętlą)

    Returns:
        Unikalny identyfikator z prefiksem

    Raises:
        RuntimeError: Gdy nie uda się wygenerować unikalnego ID w limicie prób
    """
    for _ in range(max_attempts):
        new_id = generate_id(prefix)
        if new_id not in existing_ids:
            return new_id
    raise RuntimeError(
        f"Nie udało się wygenerować unikalnego ID z prefiksem '{prefix}' "
        f"po {max_attempts} próbach"
    )
