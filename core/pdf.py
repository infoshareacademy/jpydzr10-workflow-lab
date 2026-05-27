"""PDF font helpers współdzielone przez ``reservations`` i ``service`` apps.

reportlab domyślnie obsługuje ``Helvetica`` z kodowaniem Latin-1 — nie ma w nim
polskich znaków diakrytycznych (ą, ę, ł, ó, ś, ż, ź, ć, ń → renderowane jako `?`
lub pominięte). Aplikacja wgrywa pakowany font **DejaVu Sans** (`static/fonts/`)
i rejestruje go pod aliasem ``PlanerSans`` / ``PlanerSans-Bold``.

Użycie::

    from core.pdf import register_pdf_fonts, font_name

    register_pdf_fonts()                # idempotent
    style.fontName = font_name()        # 'PlanerSans' (fallback 'Helvetica')
    bold = font_name("bold")            # 'PlanerSans-Bold'

Jeśli pliki TTF nie znajdują się w ``static/fonts/`` (np. minimalny obraz
testowy), helper loguje warning i zwraca Helveticę — PDF dalej się generuje
(no crash), ale polskie znaki nie wyświetlą się poprawnie.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger("core.pdf")

FONT_NAME_REGULAR = "PlanerSans"
FONT_NAME_BOLD = "PlanerSans-Bold"

_FONTS_REGISTERED = False


def register_pdf_fonts() -> None:
    """Rejestruje DejaVu Sans z bundled ``static/fonts/`` jako aliasy PlanerSans.

    Idempotent — drugie wywołanie nie robi nic. Bezpieczne do wywołania na
    początku każdej funkcji generującej PDF.

    Fallback: jeśli pliki TTF nie istnieją, loguje warning i pozostaje przy
    Helvetica (defensive degradation — PDF się generuje bez polskich znaków
    zamiast crashować z 500).
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    fonts_dir = Path(settings.BASE_DIR) / "static" / "fonts"
    regular_path = fonts_dir / "DejaVuSans.ttf"
    bold_path = fonts_dir / "DejaVuSans-Bold.ttf"

    if not regular_path.exists():
        logger.warning(
            "DejaVuSans.ttf nie znaleziony w %s — PDF będzie używał Helvetica "
            "(polskie znaki nie zostaną zrenderowane poprawnie).",
            regular_path,
        )
        return

    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME_REGULAR, str(regular_path)))
        if bold_path.exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, str(bold_path)))
        else:
            # Bold fallback — alias na Regular (lepiej niż crash na unknown font).
            pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, str(regular_path)))
        _FONTS_REGISTERED = True
        logger.debug("Fonts DejaVu zarejestrowane: %s + %s", regular_path, bold_path)
    except Exception as exc:
        logger.warning("Nie udało się zarejestrować fontów DejaVu: %s", exc)


def font_name(weight: str = "regular") -> str:
    """Zwraca nazwę zarejestrowanego fontu lub fallback Helvetica.

    Args:
        weight: ``"regular"`` lub ``"bold"``.
    """
    if not _FONTS_REGISTERED:
        return "Helvetica-Bold" if weight == "bold" else "Helvetica"
    return FONT_NAME_BOLD if weight == "bold" else FONT_NAME_REGULAR
