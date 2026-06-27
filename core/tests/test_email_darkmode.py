"""Testy wsparcia trybu ciemnego w opakowaniu maili (emails/base_email.html).

Klienty pocztowe obsługują tryb ciemny dwoma niezależnymi mechanizmami:
``prefers-color-scheme`` (Apple Mail / iOS) oraz inwersję kolorów Outlooka
oznaczaną atrybutami ``[data-ogsc]`` / ``[data-ogsb]``. Renderujemy bazowy
szablon i sprawdzamy, że oba mechanizmy są obecne — a jednocześnie że jasny
design (inline style) nie został usunięty.
"""

from __future__ import annotations

from django.template.loader import render_to_string


def _render_base() -> str:
    return render_to_string(
        "emails/base_email.html",
        {
            "body_pl": "<p>Treść PL</p>",
            "body_en": "<p>Body EN</p>",
            "unsubscribe_url": "https://example.test/unsubscribe",
        },
    )


def test_base_email_contains_darkmode_markers():
    html = _render_base()
    # Deklaracja schematu kolorów (head meta + :root).
    assert 'name="color-scheme"' in html
    assert "color-scheme: light dark" in html
    # Apple Mail / iOS — media query.
    assert "@media (prefers-color-scheme: dark)" in html
    # Outlook — selektory atrybutowe inwersji kolorów.
    assert "[data-ogsc]" in html
    assert "[data-ogsb]" in html


def test_base_email_keeps_light_design_and_structure():
    html = _render_base()
    # Inline style jasnego wyglądu zachowane (tryb ciemny tylko je uzupełnia).
    assert "background:#f1f5f9" in html
    assert "background:#2563eb" in html
    # Treść obu języków i link wypisu nadal renderowane.
    assert "Treść PL" in html
    assert "Body EN" in html
    assert "https://example.test/unsubscribe" in html
