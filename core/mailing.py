"""Wspólne narzędzia wysyłki dwujęzycznych (PL+EN) maili transakcyjnych.

Każdy mail składa się z fragmentu treści renderowanego dwukrotnie
(``translation.override`` pl/en) i opakowanego w ``emails/base_email.html``
(branded header + footer + placeholder „wypisz się"). Tekstowy fallback skleja
obie wersje rozdzielone separatorem.

Funkcje są fail-soft względem listy odbiorców (pusta lista → 0 wysłanych) —
sama wysyłka SMTP może rzucić wyjątek, który woła wyższej warstwy obsługuje.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import translation

_LANGS = ("pl", "en")
_TEXT_SEPARATOR = "—" * 22 + " ENGLISH " + "—" * 22


def build_bilingual_email(body_basename: str, context: dict) -> tuple[str, str]:
    """Renderuje fragment ``emails/{basename}_body.{html,txt}`` w PL i EN.

    Zwraca krotkę ``(html_body, text_body)`` gotową do
    :class:`~django.core.mail.EmailMultiAlternatives`.
    """
    html_frag: dict[str, str] = {}
    text_frag: dict[str, str] = {}
    for lang in _LANGS:
        with translation.override(lang):
            html_frag[lang] = render_to_string(f"emails/{body_basename}_body.html", context)
            text_frag[lang] = render_to_string(f"emails/{body_basename}_body.txt", context)
    html_body = render_to_string(
        "emails/base_email.html",
        {"body_pl": html_frag["pl"], "body_en": html_frag["en"]},
    )
    text_body = f"{text_frag['pl'].strip()}\n\n{_TEXT_SEPARATOR}\n\n{text_frag['en'].strip()}\n"
    return html_body, text_body


def send_bilingual_mail(subject: str, html_body: str, text_body: str, recipients: list[str]) -> int:
    """Wyślij ``EmailMultiAlternatives`` (HTML + plaintext). Zwraca liczbę wysłanych."""
    recipients = [r for r in recipients if r]
    if not recipients:
        return 0
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send()


def fleet_admin_recipients() -> list[str]:
    """Adresy e-mail administratorów floty (grupa „Administratorzy", aktywni).

    Adresaci alertów przeglądowych (overdue/upcoming) — to oni zarządzają
    flotą i reagują na zaległe przeglądy.
    """
    user_model = get_user_model()
    admins = (
        user_model.objects.filter(is_active=True, groups__name="Administratorzy")
        .exclude(email="")
        .distinct()
    )
    return sorted({u.email for u in admins})
