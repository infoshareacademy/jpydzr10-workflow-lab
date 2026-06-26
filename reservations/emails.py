"""Wysyłka powiadomień e-mail dla rezerwacji — DWUJĘZYCZNE (PL + EN).

Każdy mail zawiera sekcję polską i angielską w jednej wiadomości (rozwiązuje
problem języka interfejsu — odbiorca dostaje obie wersje). Treść składana jest
z fragmentu renderowanego dwukrotnie (``translation.override`` pl/en) w
``emails/base_email.html``.

Typy maili (cykl życia rezerwacji):

* :func:`send_confirmation_email` — po potwierdzeniu rezerwacji → do twórcy.
* :func:`send_cancellation_email` — po anulowaniu rezerwacji → do twórcy.
* :func:`send_request_notification_email` — po złożeniu wniosku (rezerwacja
  oczekująca) → do zatwierdzających (magazynier/admin), bo to oni zatwierdzają.

Wszystkie są fail-soft: brak adresata → log + ciche pominięcie (nie crashują
ścieżki biznesowej).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation

logger = logging.getLogger("reservations")

_LANGS = ("pl", "en")
_SEP = "—" * 22 + " ENGLISH " + "—" * 22


def _build_bilingual(body_basename: str, context: dict) -> tuple[str, str]:
    """Renderuje fragment treści w PL i EN, składa HTML (base_email) + tekst."""
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
    text_body = f"{text_frag['pl'].strip()}\n\n{_SEP}\n\n{text_frag['en'].strip()}\n"
    return html_body, text_body


def _send(subject: str, html_body: str, text_body: str, recipients: list[str]) -> int:
    """Wyślij EmailMultiAlternatives. Zwraca liczbę wysłanych (0 = brak/odmowa)."""
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


def send_confirmation_email(reservation_pk: int) -> None:
    """Mail potwierdzenia rezerwacji (dwujęzyczny) do twórcy rezerwacji."""
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
        logger.warning(
            "Confirmation email: rezerwacja pk=%s bez adresata (created_by/email puste) — pomijam.",
            reservation_pk,
        )
        return

    context = {
        "reservation": reservation,
        "machine": reservation.machine,
        "site": reservation.site,
        "recipient_name": creator.get_full_name() or creator.get_username(),
    }
    html_body, text_body = _build_bilingual("reservation_confirmed", context)
    uid = reservation.machine.uid
    subject = f"Potwierdzenie rezerwacji {uid} / Reservation {uid} confirmed"
    sent = _send(subject, html_body, text_body, [creator.email])

    if sent:
        Reservation.objects.filter(pk=reservation_pk).update(
            confirmation_email_sent_at=timezone.now()
        )
        logger.info("Confirmation email wysłany dla rezerwacji pk=%s.", reservation_pk)
    else:
        logger.error(
            "Confirmation email NIE został wysłany (send()=0) dla rezerwacji pk=%s.",
            reservation_pk,
        )


def send_cancellation_email(reservation_pk: int, reason_display: str = "") -> None:
    """Mail o anulowaniu rezerwacji (dwujęzyczny) do twórcy rezerwacji."""
    from .models import Reservation

    reservation = (
        Reservation.objects.select_related("machine", "site", "created_by")
        .filter(pk=reservation_pk)
        .first()
    )
    if reservation is None:
        logger.warning("Cancellation email: rezerwacja pk=%s nie istnieje.", reservation_pk)
        return

    creator = reservation.created_by
    if not (creator and creator.email):
        logger.info("Cancellation email: rezerwacja pk=%s bez adresata — pomijam.", reservation_pk)
        return

    context = {
        "reservation": reservation,
        "machine": reservation.machine,
        "site": reservation.site,
        "recipient_name": creator.get_full_name() or creator.get_username(),
        "reason_display": reason_display or reservation.get_cancellation_reason_display(),
    }
    html_body, text_body = _build_bilingual("reservation_cancelled", context)
    uid = reservation.machine.uid
    subject = f"Anulowanie rezerwacji {uid} / Reservation {uid} cancelled"
    if _send(subject, html_body, text_body, [creator.email]):
        logger.info("Cancellation email wysłany dla rezerwacji pk=%s.", reservation_pk)


def send_reservation_reminder_email(reservation_pk: int) -> int:
    """Mail-przypomnienie T-1 (dwujęzyczny) do twórcy rezerwacji startującej jutro.

    Zwraca liczbę wysłanych wiadomości (0 = brak adresata / nie wysłano) — komenda
    ``send_daily_reminders`` ustawia ``reminder_sent_at`` dopiero po skutecznej
    wysyłce, dzięki czemu nieudana próba zostanie ponowiona następnego dnia.
    """
    from core.mailing import build_bilingual_email, send_bilingual_mail

    from .models import Reservation

    reservation = (
        Reservation.objects.select_related("machine", "site", "created_by")
        .filter(pk=reservation_pk)
        .first()
    )
    if reservation is None:
        logger.warning("Reminder email: rezerwacja pk=%s nie istnieje.", reservation_pk)
        return 0

    creator = reservation.created_by
    if not (creator and creator.email):
        logger.info("Reminder email: rezerwacja pk=%s bez adresata — pomijam.", reservation_pk)
        return 0

    base = getattr(settings, "EMAIL_LINK_BASE_URL", "http://localhost:8002").rstrip("/")
    context = {
        "reservation": reservation,
        "machine": reservation.machine,
        "site": reservation.site,
        "recipient_name": creator.get_full_name() or creator.get_username(),
        "detail_url": f"{base}/rezerwacje/{reservation.pk}/",
    }
    html_body, text_body = build_bilingual_email("reservation_reminder", context)
    uid = reservation.machine.uid
    subject = f"Przypomnienie o rezerwacji {uid} / Reservation {uid} reminder"
    sent = send_bilingual_mail(subject, html_body, text_body, [creator.email])
    if sent:
        logger.info("Reminder email wysłany dla rezerwacji pk=%s.", reservation_pk)
    return sent


def send_request_notification_email(reservation_pk: int) -> None:
    """Mail do zatwierdzających (magazynier/admin) o nowym wniosku o rezerwację.

    Adresaci: aktywni użytkownicy z uprawnieniem ``change_reservation``
    (magazynier/admin) i ustawionym adresem e-mail — to oni zatwierdzają.
    """
    from django.contrib.auth import get_user_model

    from .models import Reservation

    reservation = (
        Reservation.objects.select_related("machine", "site").filter(pk=reservation_pk).first()
    )
    if reservation is None:
        return

    user_model = get_user_model()
    approvers = user_model.objects.filter(is_active=True).exclude(email="").distinct()
    recipients = sorted(
        {u.email for u in approvers if u.has_perm("reservations.change_reservation")}
    )
    if not recipients:
        logger.info(
            "Request notification: brak zatwierdzających z e-mailem dla rezerwacji pk=%s.",
            reservation_pk,
        )
        return

    detail_path = f"/rezerwacje/{reservation.pk}/"
    base = getattr(settings, "EMAIL_LINK_BASE_URL", "http://localhost:8002").rstrip("/")
    context = {
        "reservation": reservation,
        "machine": reservation.machine,
        "site": reservation.site,
        "detail_url": f"{base}{detail_path}",
    }
    html_body, text_body = _build_bilingual("reservation_request", context)
    uid = reservation.machine.uid
    subject = f"Nowy wniosek o rezerwację {uid} / New reservation request {uid}"
    if _send(subject, html_body, text_body, recipients):
        logger.info(
            "Request notification wysłany (%s odbiorców) dla rezerwacji pk=%s.",
            len(recipients),
            reservation_pk,
        )
