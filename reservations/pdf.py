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

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.pdf import font_name as _font_name
from core.pdf import register_pdf_fonts as _register_fonts
from reservations.models import Reservation

logger = logging.getLogger("reservations.pdf")


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

    # Bug 2026-05-29: pdfplumber extract_text() sklejał label+value bez spacji
    # ("rezerwującap:an" zamiast "rezerwująca: pan"). Wizualnie PDF OK
    # (table padding 12pt rozdzielał komórki), ale copy-paste z PDF dawał
    # zlepione tokeny. Dodanie leading non-breaking space ( ) do każdej
    # value cell zapewnia że extract zawsze ma separator, bez wpływu na wizual.
    def _val(s):
        return f" {s}"

    table_data = [
        ["Numer rezerwacji:", _val(str(reservation.pk))],
        ["Maszyna:", _val(f"{reservation.machine.uid} — {reservation.machine.name}")],
        ["Data od:", _val(reservation.start_date.strftime("%d.%m.%Y"))],
        ["Data do:", _val(reservation.end_date.strftime("%d.%m.%Y"))],
        ["Status:", _val(reservation.get_status_display())],
        ["Osoba rezerwująca:", _val(reservation.person or "—")],
        # Wave 14-A Bundle 4 + 8 -- responsible_person field (kierownik/brygadzista).
        ["Osoba na budowie:", _val(reservation.responsible_person or "—")],
        ["Adres dostawy:", _val(reservation.address or "—")],
        ["Budowa:", _val(str(reservation.site) if reservation.site else "—")],
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
