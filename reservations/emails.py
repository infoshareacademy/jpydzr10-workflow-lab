"""Wysyłka powiadomień e-mail dla rezerwacji.

:func:`send_confirmation_email` jest wołana przez ``transaction.on_commit`` po
potwierdzeniu rezerwacji — dzięki temu mail wychodzi dopiero gdy transakcja się
zatwierdzi (rollback = zero maili). Adresatem jest twórca rezerwacji
(``created_by.email``); brak twórcy lub adresu = ciche pominięcie (log).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

logger = logging.getLogger("reservations")


def send_confirmation_email(reservation_pk: int) -> None:
    """Wysyła e-mail potwierdzający rezerwację o danym PK (idempotentnie po wysyłce)."""
    from .models import Reservation

    reservation = (
        Reservation.objects.select_related("machine", "site", "created_by")
        .filter(pk=reservation_pk)
        .first()
    )
    if reservation is None:
        logger.warning("Confirmation email: rezerwacja pk=%s nie istnieje.", reservation_pk)
        return

    creator = reservation.created_by
    if not (creator and creator.email):
        logger.info(
            "Confirmation email: rezerwacja pk=%s bez adresata (created_by/email puste) — pomijam.",
            reservation_pk,
        )
        return

    # Adresatem jest pracownik — domyślny język interfejsu (PL). EN wejdzie wraz
    # z pełną lokalizacją treści; subject wymuszamy na str (lazy proxy → tekst).
    recipient_lang = settings.LANGUAGE_CODE
    context = {
        "reservation": reservation,
        "machine": reservation.machine,
        "site": reservation.site,
        "recipient_name": creator.get_full_name() or creator.get_username(),
    }
    with translation.override(recipient_lang):
        subject = str(_("Potwierdzenie rezerwacji %(uid)s") % {"uid": reservation.machine.uid})
        text_body = render_to_string("reservations/email/confirmation.txt", context)
        html_body = render_to_string("reservations/email/confirmation.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[creator.email],
    )
    message.attach_alternative(html_body, "text/html")
    sent = message.send()

    if sent:
        # Osobny, krótki update (omija save()/historię) — to wyłącznie pole audytowe.
        Reservation.objects.filter(pk=reservation_pk).update(
            confirmation_email_sent_at=timezone.now()
        )
        logger.info("Confirmation email wysłany dla rezerwacji pk=%s.", reservation_pk)
