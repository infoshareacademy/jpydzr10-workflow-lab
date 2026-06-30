"""Testy powiadomień e-mail po potwierdzeniu rezerwacji.

KRYTYCZNE: callback ``transaction.on_commit`` NIE odpala się pod
``@pytest.mark.django_db`` bez ``django_capture_on_commit_callbacks(execute=True)``
— bez tego ``mailoutbox`` zostaje pusty (artefakt harnessu, nie błąd kodu).
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from machines.models import Machine
from reservations import emails
from reservations.factories import ConstructionSiteFactory
from reservations.models import Reservation
from reservations.services import (
    confirm_reservation,
    create_batch_reservation,
    create_reservation,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


def _creator(username="autor", email="autor@demo.test"):
    return User.objects.create_user(username=username, password="x", email=email)


def _machine(uid):
    return Machine.objects.create(
        uid=uid,
        name=f"Maszyna {uid}",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


def _pending(machine, creator, *, person="Jan Kowalski"):
    start = date.today() + timedelta(days=5)
    end = date.today() + timedelta(days=10)
    return create_reservation(
        machine_id=machine.pk,
        site_id=None,
        start_date=start,
        end_date=end,
        person=person,
        created_by=creator,
    )


def test_single_confirm_sends_one_email(django_capture_on_commit_callbacks, mailoutbox, machine):
    creator = _creator()
    res = _pending(machine, creator)
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert msg.to == ["autor@demo.test"]
    assert machine.uid in msg.subject
    # Subject jest realnym tekstem, nie lazy proxy (str() wymuszone w emails.py).
    assert isinstance(msg.subject, str)
    # Treść tekstowa faktycznie wyrenderowana (nie pusta) i zawiera klucze danych:
    # imię osoby rezerwującej + daty + nazwę maszyny — gdyby szablon się sypnął
    # po cichu, body byłoby puste i ten asercja by to złapała.
    assert msg.body.strip()
    assert "Jan Kowalski" in msg.body
    # Daty renderowane są w ludzkim formacie (np. "1 lipca 2026"), nie ISO —
    # asercja na rok potwierdza, że zakres terminu trafił do treści.
    assert str(res.start_date.year) in msg.body
    assert machine.name in msg.body
    # Powitanie używa nazwy adresata (created_by.get_username()).
    assert "autor" in msg.body
    # Alternatywa HTML została dołączona i jest niepusta.
    assert msg.alternatives
    html_body, mime = msg.alternatives[0]
    assert mime == "text/html"
    assert html_body.strip()
    assert machine.uid in html_body
    res.refresh_from_db()
    assert res.confirmation_email_queued_at is not None
    assert res.confirmation_email_sent_at is not None
    # Chronologia audytu: kolejkowanie nastąpiło przed (lub równo) wysyłką.
    assert res.confirmation_email_queued_at <= res.confirmation_email_sent_at


def test_confirm_sends_email_with_site(django_capture_on_commit_callbacks, mailoutbox, machine):
    """Rezerwacja z budową → szczegóły budowy (nr projektu + nazwa) w treści maila."""
    creator = _creator()
    site = ConstructionSiteFactory(project_number="BUD-2026-077", name="Budowa Testowa Centrum")
    start = date.today() + timedelta(days=5)
    res = create_reservation(
        machine_id=machine.pk,
        site_id=site.pk,
        start_date=start,
        end_date=start + timedelta(days=4),
        person="Jan Kowalski",
        created_by=creator,
    )
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    html_body = mailoutbox[0].alternatives[0][0]
    # Blok {% if site %} w szablonie musi wstrzyknąć dane budowy.
    assert site.project_number in body
    assert site.name in body
    assert site.project_number in html_body


def test_email_send_failure_leaves_sent_at_null_and_logs_error(
    django_capture_on_commit_callbacks, mailoutbox, machine, caplog
):
    """``send()`` zwraca 0 (awaria SMTP) → ``sent_at`` zostaje NULL + log ERROR.

    Krytyczna ścieżka: kolejkowanie (``queued_at``) musi pozostać, by retry był
    idempotentny, ale brak ``sent_at`` + log ERROR sygnalizują niedostarczenie
    (inaczej awaria jest całkowicie niewidoczna).
    """
    import logging

    creator = _creator()
    res = _pending(machine, creator)
    with (
        caplog.at_level(logging.ERROR, logger="reservations"),
        # Wysyłka idzie teraz przez core.mailing.send_bilingual_mail (fail-soft).
        mock.patch("core.mailing.EmailMultiAlternatives.send", return_value=0),
        django_capture_on_commit_callbacks(execute=True),
    ):
        confirm_reservation(res)
    res.refresh_from_db()
    # Kolejkowanie zaszło (guard idempotentny), ale dostarczenie nie.
    assert res.confirmation_email_queued_at is not None
    assert res.confirmation_email_sent_at is None
    # Awaria jest widoczna w logach jako ERROR z PK rezerwacji.
    assert any(
        record.levelno == logging.ERROR and str(res.pk) in record.getMessage()
        for record in caplog.records
    )


def test_confirmation_smtp_exception_is_failsoft_and_logs_bounce(
    django_capture_on_commit_callbacks, machine
):
    """Wyjątek SMTP przy potwierdzeniu NIE wywraca akcji i tworzy ``BounceLog``.

    Po przejściu maili transakcyjnych na ``core.mailing`` (fail-soft) błąd
    backendu jest łapany: rezerwacja zostaje potwierdzona, ``sent_at`` jest NULL,
    a odbicie trafia do dziennika ``BounceLog`` (admin widzi nieudaną wysyłkę).
    """
    from core.models import BounceLog
    from reservations.models import Reservation

    creator = _creator()
    res = _pending(machine, creator)
    with (
        mock.patch("core.mailing.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")),
        django_capture_on_commit_callbacks(execute=True),
    ):
        confirm_reservation(res)  # nie rzuca — fail-soft

    res.refresh_from_db()
    assert res.status == Reservation.Status.POTWIERDZONA  # akcja biznesowa OK
    assert res.confirmation_email_sent_at is None  # dostarczenie się nie udało
    assert BounceLog.objects.filter(recipient=creator.email).exists()  # odbicie zalogowane


def test_no_email_when_reservation_deleted(
    django_capture_on_commit_callbacks, mailoutbox, machine, caplog
):
    """Rezerwacja usunięta między on_commit a wykonaniem callbacku → 0 maili, brak wyjątku.

    Symulujemy wyścig: callback dostaje PK, ale wiersz już nie istnieje. Funkcja
    musi zwrócić wcześnie z logiem WARNING zamiast rzucać ``DoesNotExist``.
    """
    import logging

    deleted_pk = 9_999_999  # PK którego na pewno nie ma w bazie
    with caplog.at_level(logging.WARNING, logger="reservations"):
        emails.send_confirmation_email(deleted_pk)
    assert len(mailoutbox) == 0
    assert any(
        record.levelno == logging.WARNING and str(deleted_pk) in record.getMessage()
        for record in caplog.records
    )


def test_no_email_when_created_by_missing(django_capture_on_commit_callbacks, mailoutbox, machine):
    start = date.today() + timedelta(days=5)
    res = create_reservation(
        machine_id=machine.pk,
        site_id=None,
        start_date=start,
        end_date=start + timedelta(days=3),
        person="Jan Kowalski",
        created_by=None,
    )
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 0


def test_no_email_when_creator_has_no_email(
    django_capture_on_commit_callbacks, mailoutbox, machine
):
    creator = _creator(username="bezmaila", email="")
    res = _pending(machine, creator)
    with django_capture_on_commit_callbacks(execute=True):
        confirm_reservation(res)
    assert len(mailoutbox) == 0


def test_bulk_confirm_sends_one_email_per_reservation(
    django_capture_on_commit_callbacks, mailoutbox
):
    creator = _creator()
    machines = [_machine(f"BULK-{i}") for i in range(3)]
    start = date.today() + timedelta(days=5)
    result = create_batch_reservation(
        machine_ids=[m.pk for m in machines],
        site_id=None,
        start_date=start,
        end_date=start + timedelta(days=4),
        person="Jan Kowalski",
        created_by=creator,
    )
    from reservations.services import bulk_confirm_batch

    with django_capture_on_commit_callbacks(execute=True):
        outcome = bulk_confirm_batch(result["batch_id"])
    # Return dict potwierdza, że WSZYSTKIE 3 pozycje zostały potwierdzone — bez
    # tego len(mailoutbox)==3 mogłoby przejść przez przypadek (np. early-return).
    assert outcome["confirmed_count"] == 3
    assert outcome["skipped_count"] == 0
    assert outcome["errors"] == []
    assert len(mailoutbox) == 3
    # Każdy mail trafia do twórcy batcha (wspólny created_by) i dotyczy jednej
    # z maszyn grupy.
    machine_uids = {m.uid for m in machines}
    for msg in mailoutbox:
        assert msg.to == [creator.email]
        assert any(uid in msg.subject for uid in machine_uids)
    # Zbiór UID-ów w temacie pokrywa wszystkie maszyny (po jednym mailu na maszynę).
    subjects = " ".join(msg.subject for msg in mailoutbox)
    for uid in machine_uids:
        assert uid in subjects


def test_bulk_rollback_sends_zero_emails_on_conflict(
    django_capture_on_commit_callbacks, mailoutbox
):
    """3-elementowy batch; środkowa pozycja koliduje → rollback całości, 0 maili.

    Regresja atomowości: gdyby ktoś usunął zewnętrzny @transaction.atomic,
    pozycje 1 i 3 wysłałyby maile mimo błędu pozycji 2.
    """
    creator = _creator()
    machines = [_machine(f"CONF-{i}") for i in range(3)]
    start = date.today() + timedelta(days=5)
    end = start + timedelta(days=4)
    result = create_batch_reservation(
        machine_ids=[m.pk for m in machines],
        site_id=None,
        start_date=start,
        end_date=end,
        person="Jan Kowalski",
        created_by=creator,
    )
    # Wymuszamy konflikt na ŚRODKOWEJ maszynie: wstrzykujemy surowo (omijając
    # walidację serwisu) potwierdzoną, nakładającą się rezerwację. Przy
    # bulk-confirm pozycja batcha na tej maszynie wykryje konflikt pod lockiem.
    Reservation.objects.create(
        machine=machines[1],
        site=None,
        start_date=start,
        end_date=end,
        person="Konflikt",
        status=Reservation.Status.POTWIERDZONA,
        created_by=creator,
    )

    from reservations.services import bulk_confirm_batch

    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(ValidationError),
    ):
        bulk_confirm_batch(result["batch_id"])
    assert len(mailoutbox) == 0
    # Żadna z pozycji batcha nie została potwierdzona (rollback).
    statuses = set(
        Reservation.objects.filter(batch_id=result["batch_id"]).values_list("status", flat=True)
    )
    assert statuses == {Reservation.Status.OCZEKUJACA}


# =============================================================================
# Maile dwujęzyczne (PL + EN) — anulowanie + powiadomienie o wniosku
# =============================================================================


def test_cancellation_email_is_bilingual(mailoutbox):
    """Anulowanie → mail PL+EN do twórcy, temat dwujęzyczny."""
    machine = _machine("CANC-1")
    creator = _creator("canc", "canc@demo.test")
    res = _pending(machine, creator)
    res.cancellation_reason = "klient_zrezygnowal"
    res.save(update_fields=["cancellation_reason"])

    emails.send_cancellation_email(res.pk)

    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert "Anulowanie" in msg.subject
    assert "cancelled" in msg.subject
    assert msg.to == ["canc@demo.test"]
    html = next(c for c, t in msg.alternatives if t == "text/html")
    assert "została anulowana" in html  # sekcja PL
    assert "has been cancelled" in html  # sekcja EN


def test_request_notification_goes_to_approvers_only(mailoutbox):
    """Powiadomienie o wniosku trafia do userów z change_reservation + email."""
    from django.contrib.auth.models import Permission

    approver = User.objects.create_user("approver", password="x", email="approver@demo.test")
    approver.user_permissions.add(Permission.objects.get(codename="change_reservation"))
    # User bez uprawnienia — NIE powinien dostać maila.
    User.objects.create_user("nobody", password="x", email="nobody@demo.test")

    machine = _machine("REQ-1")
    creator = _creator("reqc", "reqc@demo.test")
    res = _pending(machine, creator)  # on_commit nie odpala w teście (django_db)

    emails.send_request_notification_email(res.pk)

    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert "approver@demo.test" in msg.to
    assert "nobody@demo.test" not in msg.to
    assert "Nowy wniosek" in msg.subject
    assert "request" in msg.subject
