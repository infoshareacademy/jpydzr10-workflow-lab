"""Deweloperski podgląd dwujęzycznych maili transakcyjnych w przeglądarce.

Widok ``email_preview`` renderuje gotowy HTML dowolnego maila (w PL lub EN) na
sztywno przygotowanym kontekście demonstracyjnym — pozwala obejrzeć branding,
układ i tłumaczenia bez wysyłania prawdziwej wiadomości.

Bezpieczeństwo:
  * tylko ``DEBUG`` (poza dev — :class:`~django.http.Http404`),
  * tylko personel (``@staff_member_required``),
  * nazwa szablonu walidowana względem ALLOWLISTY — żaden ciąg od użytkownika
    nie trafia do loadera szablonów (brak path traversal).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.html import escape

# ALLOWLISTA — jedyne nazwy bazowe, które wolno renderować. Klucz = wartość
# parametru ``template`` w URL; renderowane są ``emails/{klucz}_body.{html,txt}``.
ALLOWED_TEMPLATES = (
    "reservation_confirmed",
    "reservation_cancelled",
    "reservation_request",
    "reservation_reminder",
    "inspection_overdue",
    "inspection_upcoming",
    "password_reset",
)

_LANGS = ("pl", "en")

# Wspólne, lekkie obiekty-atrapy współdzielone przez warianty rezerwacji.
_SAMPLE_MACHINE = SimpleNamespace(uid="KOP-014", name="Koparka gąsienicowa")
_SAMPLE_RESERVATION = SimpleNamespace(
    start_date=date(2026, 7, 1),
    end_date=date(2026, 7, 14),
    person="Jan Kowalski",
    get_cancellation_reason_display=lambda: "Zmiana harmonogramu budowy",
)
_SAMPLE_SITE = SimpleNamespace(project_number="BUD-2026-007", name="Osiedle Słoneczne")
_SAMPLE_MACHINES = [
    SimpleNamespace(
        uid="KOP-014",
        name="Koparka gąsienicowa",
        inspection_date=date(2026, 6, 20),
        location="Magazyn główny",
    ),
    SimpleNamespace(
        uid="WAL-003",
        name="Walec drogowy",
        inspection_date=date(2026, 6, 22),
        location="Budowa BUD-2026-007",
    ),
]

_RESERVATION_CONTEXT = {
    "recipient_name": "Jan Kowalski",
    "machine": _SAMPLE_MACHINE,
    "reservation": _SAMPLE_RESERVATION,
    "site": _SAMPLE_SITE,
    "detail_url": "https://example.test/rezerwacje/42/",
}


def _sample_context(basename: str) -> dict:
    """Zwraca przykładowy kontekst dla danego (zwalidowanego) szablonu."""
    if basename in {"inspection_overdue", "inspection_upcoming"}:
        return {"machines": _SAMPLE_MACHINES}
    if basename == "password_reset":
        return {
            "recipient_name": "Jan Kowalski",
            "reset_url": "https://example.test/accounts/reset/abc123/",
            "valid_hours": 24,
        }
    # Warianty rezerwacji współdzielą ten sam zestaw pól.
    return dict(_RESERVATION_CONTEXT)


def _render_email(basename: str, lang: str) -> str:
    """Renderuje wybrany szablon w jednym języku, opakowany w base_email."""
    context = _sample_context(basename)
    with translation.override(lang):
        body = render_to_string(f"emails/{basename}_body.html", context)
        return render_to_string("emails/base_email.html", {"body_pl": body, "body_en": body})


def _index() -> HttpResponse:
    """Strona-spis: linki do każdego szablonu w obu językach."""
    rows = []
    for name in ALLOWED_TEMPLATES:
        links = " · ".join(
            f'<a href="?template={escape(name)}&amp;lang={lang}">{lang.upper()}</a>'
            for lang in _LANGS
        )
        rows.append(f"<li><code>{escape(name)}</code> — {links}</li>")
    html = (
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>"
        "<title>Podgląd maili</title></head><body style='font-family:Arial,sans-serif;"
        "max-width:640px;margin:40px auto;color:#0f172a;'>"
        "<h1 style='font-size:20px;'>Podgląd maili transakcyjnych</h1>"
        "<p style='color:#64748b;'>Widok deweloperski (DEBUG) — przykładowe dane.</p>"
        f"<ul style='line-height:1.9;'>{''.join(rows)}</ul>"
        "</body></html>"
    )
    return HttpResponse(html)


@staff_member_required
def email_preview(request) -> HttpResponse:
    """Podgląd HTML dwujęzycznych maili (dev-only, staff-only).

    ``GET /admin/preview-email/?template=<name>&lang=<pl|en>``. Bez parametru
    ``template`` zwraca spis dostępnych szablonów.
    """
    if not settings.DEBUG:
        raise Http404("Podgląd maili dostępny tylko w trybie DEBUG.")

    template = request.GET.get("template")
    if not template:
        return _index()

    if template not in ALLOWED_TEMPLATES:
        raise Http404(f"Nieznany szablon maila: {template!r}.")

    lang = request.GET.get("lang", "pl")
    if lang not in _LANGS:
        lang = "pl"

    return HttpResponse(_render_email(template, lang))
