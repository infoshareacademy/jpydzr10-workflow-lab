"""Alerty przeglądowe e-mail (dwujęzyczne PL+EN) do administratorów floty.

Dwa scenariusze, wysyłane przez komendę ``send_inspection_alerts`` (cron):

* :func:`send_inspection_overdue_email` — maszyny z przeterminowanym przeglądem
  (wysyłane przy każdym uruchomieniu — zaległość ma być natrętna).
* :func:`send_inspection_upcoming_email` — maszyny ze zbliżającym się przeglądem
  (idempotentne przez ``Machine.inspection_warning_sent_at`` — jeden alert na okno).

Adresaci: aktywni użytkownicy z grupy „Administratorzy" (zob.
:func:`core.mailing.fleet_admin_recipients`).
"""

from __future__ import annotations

import logging

from core.email_optout import EmailCategory, is_opted_out, preferences_url
from core.mailing import build_bilingual_email, fleet_admin_users, send_bilingual_mail

logger = logging.getLogger("machines")


def _send_inspection_email(machines: list, *, basename: str, subject: str) -> int:
    """Składa i wysyła jeden zbiorczy mail z listą maszyn do administratorów floty.

    Alerty przeglądowe są nieobowiązkowe — administratorzy wypisani z kategorii
    ``inspections`` są pomijani. Link „wypisz się" prowadzi do strony preferencji
    (bez tokenu, bo mail jest zbiorczy — adresat zarządza po zalogowaniu).
    """
    if not machines:
        return 0
    recipients = [
        u.email
        for u in fleet_admin_users()
        if u.email and not is_opted_out(u, EmailCategory.INSPECTIONS)
    ]
    if not recipients:
        logger.info("Inspection alert (%s): brak administratorów z e-mailem — pomijam.", basename)
        return 0
    html_body, text_body = build_bilingual_email(
        basename, {"machines": machines}, unsubscribe_url=preferences_url()
    )
    sent = send_bilingual_mail(subject, html_body, text_body, sorted(recipients))
    if sent:
        logger.info(
            "Inspection alert (%s) wysłany do %s administratorów (%s maszyn).",
            basename,
            len(recipients),
            len(machines),
        )
    return sent


def send_inspection_overdue_email(machines: list) -> int:
    """Alert o maszynach z przeterminowanym przeglądem."""
    return _send_inspection_email(
        machines,
        basename="inspection_overdue",
        subject="Przeterminowane przeglądy maszyn / Overdue machine inspections",
    )


def send_inspection_upcoming_email(machines: list) -> int:
    """Alert o maszynach ze zbliżającym się przeglądem."""
    return _send_inspection_email(
        machines,
        basename="inspection_upcoming",
        subject="Zbliżające się przeglądy maszyn / Upcoming machine inspections",
    )
