"""PDF generation dla rezerwacji — A4 print do przyklejenia na maszynie.

Layout zoptymalizowany pod czytelność z dystansu (czcionki 14-24pt), tabela
z głównymi danymi rezerwacji + sekcja notatek. Generuje bytes w pamięci
(io.BytesIO), bez zapisu do filesystemu — caller decyduje co z tym zrobić
(typowo: HttpResponse z Content-Disposition=attachment).

reportlab >= 4.0 (zadeklarowane w pyproject.toml).

Wave 14-A Bundle 8 — Sebastian walkthrough 17 maja 2026: domyslny font
``Helvetica`` w reportlab obsluguje TYLKO Latin-1 (no ą,ę,ł,ó,ś,ż,ź,ć,ń).
PDF wyswietlal "Pyry" zamiast "Prądotwórczy", "oczekucza" zamiast
"oczekująca", "ucię" zamiast "kończy się" itp. Naprawione przez
zarejestrowanie bundled DejaVu Sans z ``static/fonts/`` (757 KB Regular +
705 KB Bold). DejaVu wspiera pelny Latin Extended-A (Unicode U+0100-
U+017F) + Latin Extended Additional, czyli wszystkie znaki polskie,
czeskie, slowackie etc.
"""

from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from reservations.models import Reservation

logger = logging.getLogger("reservations.pdf")

# Wave 14-A Bundle 8 — DejaVu Sans fonts bundled w static/fonts/. Aliasy
# 'PlanerSans' / 'PlanerSans-Bold' uzywane w stylach ParagraphStyle ponizej.
# Rejestracja idempotent: idziemy w try/except bo pdfmetrics rzuca jesli
# font o tej nazwie juz zostal zarejestrowany.
_FONT_NAME_REGULAR = "PlanerSans"
_FONT_NAME_BOLD = "PlanerSans-Bold"
_FONTS_REGISTERED = False


def _register_fonts() -> None:
    """Rejestruje DejaVu Sans z bundled static/fonts/ jako PlanerSans/Bold.

    Idempotent -- safe call multiple times. Jesli pliki TTF nie istnieja
    (np. environment bez static/fonts/), loguje warning + uzywa fallbacku
    Helvetica (PDF wtedy nie pokaze polskich znakow ale przynajmniej nie
    crashnie -- defensive degradation, lepsze od 500).
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    # Pliki TTF leza w static/fonts/ -- BASE_DIR jest root projektu.
    fonts_dir = Path(settings.BASE_DIR) / "static" / "fonts"
    regular_path = fonts_dir / "DejaVuSans.ttf"
    bold_path = fonts_dir / "DejaVuSans-Bold.ttf"

    if not regular_path.exists():
        logger.warning(
            "DejaVuSans.ttf nie znaleziony w %s -- PDF bedzie uzywal Helvetica "
            "(polskie znaki nie zostana zrenderowane poprawnie).",
            regular_path,
        )
        return

    try:
        pdfmetrics.registerFont(TTFont(_FONT_NAME_REGULAR, str(regular_path)))
        if bold_path.exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME_BOLD, str(bold_path)))
        else:
            # Bold fallback -- alias na Regular (lepiej niz crash).
            pdfmetrics.registerFont(TTFont(_FONT_NAME_BOLD, str(regular_path)))
        _FONTS_REGISTERED = True
        logger.debug("Fonts DejaVu zarejestrowane: %s + %s", regular_path, bold_path)
    except Exception as exc:
        logger.warning("Nie udalo sie zarejestrowac fontow DejaVu: %s", exc)


def _font_name(weight: str = "regular") -> str:
    """Zwraca nazwe zarejestrowanego fontu (PlanerSans) lub fallback (Helvetica).

    `weight` = 'regular' | 'bold'. Jesli rejestracja sie nie udala (brak TTF),
    zwracamy Helvetica zeby reportlab nie crashnal na unknown font.
    """
    if not _FONTS_REGISTERED:
        return "Helvetica-Bold" if weight == "bold" else "Helvetica"
    return _FONT_NAME_BOLD if weight == "bold" else _FONT_NAME_REGULAR


def generate_reservation_pdf(reservation: Reservation) -> bytes:
    """Generuje PDF rezerwacji A4 do druku.

    Layout: nagłówek (tytuł), tabela z głównymi danymi (numer, maszyna,
    daty, status, osoba, budowa), sekcja notatek (jeśli istnieją) + footer
    z datą wydruku.

    Wave 14-A Bundle 8: wszystkie ParagraphStyle + TableStyle uzywaja teraz
    DejaVu Sans (PlanerSans alias) zamiast Helvetica, dzieki czemu polskie
    znaki (ąęłóśżźćń) renderuja sie poprawnie.

    Returns:
        bytes — surowa zawartość PDF (do zapisania w HttpResponse / pliku).
    """
    # Lazy register fontow przy pierwszym wywolaniu. Bez tego pierwsza
    # rezerwacja PDF zwracalaby Helvetica (po imporcie modulu fonty jeszcze
    # nie sa zarejestrowane).
    _register_fonts()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        title=f"Rezerwacja {reservation.pk}",
        author="Planer Maszyn Budowlanych",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "PlanerH1",
        parent=styles["Heading1"],
        fontName=_font_name("bold"),
        fontSize=24,
        alignment=1,
        spaceAfter=20,
    )
    h2 = ParagraphStyle(
        "PlanerH2",
        parent=styles["Heading2"],
        fontName=_font_name("bold"),
        fontSize=18,
        spaceAfter=12,
    )
    body = ParagraphStyle(
        "PlanerBody",
        parent=styles["Normal"],
        fontName=_font_name("regular"),
        fontSize=14,
        leading=20,
    )

    story: list = []
    story.append(Paragraph("Rezerwacja maszyny", h1))
    story.append(Spacer(1, 12))

    table_data = [
        ["Numer rezerwacji:", str(reservation.pk)],
        ["Maszyna:", f"{reservation.machine.uid} — {reservation.machine.name}"],
        ["Data od:", reservation.start_date.strftime("%d.%m.%Y")],
        ["Data do:", reservation.end_date.strftime("%d.%m.%Y")],
        ["Status:", reservation.get_status_display()],
        ["Osoba rezerwująca:", reservation.person or "—"],
        # Wave 14-A Bundle 4 + 8 -- responsible_person field (kierownik/brygadzista).
        ["Osoba na budowie:", reservation.responsible_person or "—"],
        ["Adres dostawy:", reservation.address or "—"],
        ["Budowa:", str(reservation.site) if reservation.site else "—"],
    ]
    table = Table(table_data, colWidths=[5 * cm, 11 * cm])
    table.setStyle(
        TableStyle(
            [
                # Wave 14-A Bundle 8 -- FONTNAME forcownie DejaVu na cala tabele,
                # inaczej reportlab uzywal Helvetica i polskie znaki sie psuly.
                ("FONTNAME", (0, 0), (-1, -1), _font_name("regular")),
                ("FONTSIZE", (0, 0), (-1, -1), 14),
                # Pierwsza kolumna (etykiety) -- bold dla lepszej czytelnosci.
                ("FONTNAME", (0, 0), (0, -1), _font_name("bold")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#dbeafe")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#3b82f6")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 20))

    if reservation.notes:
        story.append(Paragraph("Notatki:", h2))
        story.append(Paragraph(reservation.notes, body))

    story.append(Spacer(1, 30))
    story.append(Paragraph(f"Wydruk: {date.today().strftime('%d.%m.%Y')}", body))

    doc.build(story)
    return buffer.getvalue()
