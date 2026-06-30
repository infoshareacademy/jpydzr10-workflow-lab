#!/usr/bin/env python
"""Renderuje instrukcje użytkownika (Markdown) do plików PDF.

Buduje dwa dokumenty PDF z manuali w katalogu ``docs/``:

* ``docs/instrukcja-administratora.md`` -> ``docs/instrukcja-administratora.pdf``
* ``docs/instrukcja-magazyniera.md``    -> ``docs/instrukcja-magazyniera.pdf``

Wykorzystuje wyłącznie ``reportlab`` (już obecny w zależnościach projektu) oraz
czcionkę DejaVu Sans z ``static/fonts/`` — dzięki temu polskie znaki diakrytyczne
(ą, ć, ę, ł, ó, ż, ...) renderują się poprawnie.

Uruchomienie (z katalogu głównego projektu):

    uv run python scripts/generate_manuals.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
FONTS_DIR = PROJECT_ROOT / "static" / "fonts"

# Pary plików źródłowych (Markdown) i docelowych (PDF).
MANUALS = [
    ("instrukcja-administratora.md", "instrukcja-administratora.pdf"),
    ("instrukcja-magazyniera.md", "instrukcja-magazyniera.pdf"),
]

BRAND = HexColor("#2563eb")
INK = HexColor("#0f172a")
MUTED = HexColor("#475569")
RULE = HexColor("#cbd5e1")


def _register_fonts() -> tuple[str, str]:
    """Rejestruje czcionkę DejaVu Sans (regular + bold) obsługującą polskie znaki.

    Zwraca nazwy zarejestrowanych rodzin czcionek (regular, bold). Gdy plików TTF
    nie ma, awaryjnie używa wbudowanej Helvetica (Latin-2 też obsługuje większość
    polskich znaków, lecz DejaVu jest pewniejsza).
    """
    regular = FONTS_DIR / "DejaVuSans.ttf"
    bold = FONTS_DIR / "DejaVuSans-Bold.ttf"
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
        return "DejaVuSans", "DejaVuSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _inline_markdown(text: str) -> str:
    """Zamienia prosty inline-Markdown na znaczniki obsługiwane przez Platypus.

    Obsługuje **pogrubienie**, *kursywę* oraz `kod`. Reszta tekstu jest
    bezpiecznie escapowana do HTML, żeby znaki <, >, & nie psuły renderowania.
    """
    # Najpierw wytnij fragmenty kodu, żeby nie były przetwarzane jak markdown.
    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        code_spans.append(match.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _stash_code, text)
    text = html.escape(text)

    # Pogrubienie i kursywa (po escape, więc operujemy na czystym tekście).
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Przywróć fragmenty kodu w monospace.
    def _restore_code(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return f'<font face="Courier">{html.escape(code_spans[idx])}</font>'

    text = re.sub(r"\x00CODE(\d+)\x00", _restore_code, text)
    return text


def _build_styles(font: str, font_bold: str) -> dict[str, ParagraphStyle]:
    """Tworzy zestaw stylów akapitów dla nagłówków, treści i list."""
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["Title"] = ParagraphStyle(
        "ManualTitle",
        parent=base["Title"],
        fontName=font_bold,
        fontSize=22,
        leading=27,
        textColor=BRAND,
        spaceAfter=4,
    )
    styles["Subtitle"] = ParagraphStyle(
        "ManualSubtitle",
        fontName=font,
        fontSize=10.5,
        leading=15,
        textColor=MUTED,
        spaceAfter=10,
    )
    styles["H1"] = ParagraphStyle(
        "ManualH1",
        fontName=font_bold,
        fontSize=15,
        leading=19,
        textColor=INK,
        spaceBefore=16,
        spaceAfter=6,
        keepWithNext=True,
    )
    styles["H2"] = ParagraphStyle(
        "ManualH2",
        fontName=font_bold,
        fontSize=12,
        leading=16,
        textColor=BRAND,
        spaceBefore=11,
        spaceAfter=4,
        keepWithNext=True,
    )
    styles["H3"] = ParagraphStyle(
        "ManualH3",
        fontName=font_bold,
        fontSize=10.5,
        leading=14,
        textColor=INK,
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True,
    )
    styles["Body"] = ParagraphStyle(
        "ManualBody",
        fontName=font,
        fontSize=10,
        leading=15,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    styles["Bullet"] = ParagraphStyle(
        "ManualBullet",
        fontName=font,
        fontSize=10,
        leading=14.5,
        textColor=INK,
        spaceAfter=2,
    )
    styles["Quote"] = ParagraphStyle(
        "ManualQuote",
        fontName=font,
        fontSize=9.5,
        leading=14,
        textColor=MUTED,
        leftIndent=8,
        borderPadding=(4, 4, 4, 8),
        spaceBefore=2,
        spaceAfter=8,
    )
    return styles


def _flush_list(items: list[ListItem], ordered: bool, story: list, styles) -> None:
    """Dodaje zebraną listę (punktowaną lub numerowaną) do dokumentu."""
    if not items:
        return
    bullet_type = "1" if ordered else "bullet"
    start = 1 if ordered else None
    # Przekazujemy KOPIĘ — ``items.clear()`` poniżej opróżnia oryginalną listę,
    # a ``ListFlowable`` czyta zawartość leniwie dopiero przy ``doc.build()``.
    story.append(
        ListFlowable(
            list(items),
            bulletType=bullet_type,
            start=start,
            bulletFontName=styles["Bullet"].fontName,
            bulletColor=BRAND if not ordered else INK,
            leftIndent=14,
            bulletFontSize=9,
            spaceBefore=2,
            spaceAfter=8,
        )
    )
    items.clear()


def _parse_markdown(md_text: str, styles) -> list:
    """Zamienia uproszczony Markdown na listę flowable'i reportlab (Platypus).

    Obsługiwane konstrukcje: nagłówki #/##/###, akapity, listy punktowane (-)
    i numerowane (1.), cytaty (>) oraz poziome linie (---).
    """
    story: list = []
    pending_items: list[ListItem] = []
    pending_ordered = False

    lines = md_text.splitlines()
    title_done = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        ordered_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)

        # Wykryj zmianę kontekstu listy — domknij poprzednią, gdy trzeba.
        is_list_item = bool(ordered_match or bullet_match)
        if pending_items and (
            not is_list_item
            or (ordered_match and not pending_ordered)
            or (bullet_match and pending_ordered)
        ):
            _flush_list(pending_items, pending_ordered, story, styles)

        if not stripped:
            continue

        if stripped.startswith("# "):
            # Tytuł dokumentu (pierwszy H1) renderujemy w stylu Title.
            text = _inline_markdown(stripped[2:].strip())
            if not title_done:
                story.append(Paragraph(text, styles["Title"]))
                title_done = True
            else:
                story.append(Paragraph(text, styles["H1"]))
            continue

        if stripped.startswith("## "):
            story.append(Paragraph(_inline_markdown(stripped[3:].strip()), styles["H1"]))
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(_inline_markdown(stripped[4:].strip()), styles["H2"]))
            continue

        if stripped.startswith("#### "):
            story.append(Paragraph(_inline_markdown(stripped[5:].strip()), styles["H3"]))
            continue

        if stripped.startswith("---"):
            story.append(Spacer(1, 2))
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE))
            story.append(Spacer(1, 2))
            continue

        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            story.append(Paragraph(_inline_markdown(text), styles["Quote"]))
            continue

        if ordered_match:
            pending_ordered = True
            pending_items.append(
                ListItem(
                    Paragraph(_inline_markdown(ordered_match.group(2)), styles["Bullet"]),
                    value=int(ordered_match.group(1)),
                )
            )
            continue

        if bullet_match:
            pending_ordered = False
            pending_items.append(
                ListItem(Paragraph(_inline_markdown(bullet_match.group(1)), styles["Bullet"]))
            )
            continue

        # Zwykły akapit (drugi wiersz to podtytuł pod tytułem dokumentu).
        para_style = styles["Subtitle"] if (title_done and len(story) == 1) else styles["Body"]
        story.append(Paragraph(_inline_markdown(stripped), para_style))

    _flush_list(pending_items, pending_ordered, story, styles)
    return story


def _render_pdf(md_path: Path, pdf_path: Path, styles) -> None:
    """Renderuje pojedynczy plik Markdown do PDF."""
    md_text = md_path.read_text(encoding="utf-8")
    story = _parse_markdown(md_text, styles)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=md_path.stem.replace("-", " ").capitalize(),
    )
    doc.build(story)


def main() -> None:
    font, font_bold = _register_fonts()
    styles = _build_styles(font, font_bold)

    for md_name, pdf_name in MANUALS:
        md_path = DOCS_DIR / md_name
        pdf_path = DOCS_DIR / pdf_name
        if not md_path.exists():
            raise SystemExit(f"Brak pliku źródłowego: {md_path}")
        _render_pdf(md_path, pdf_path, styles)
        size = pdf_path.stat().st_size
        print(f"Wygenerowano: {pdf_path}  ({size} B)")


if __name__ == "__main__":
    main()
