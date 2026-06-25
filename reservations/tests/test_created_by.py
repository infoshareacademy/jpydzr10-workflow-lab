"""Testy łańcucha ``created_by`` — kto utworzył rezerwację.

``created_by`` jest stemplowane przez 5 niezależnych ścieżek (formularz UI,
quick-reserve, batch UI oraz executor chatbota). Pominięcie którejkolwiek daje
``created_by=NULL`` = brak e-maila potwierdzającego (F2) przy zielonych testach,
więc każda ścieżka ma tu jawną asercję.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse

from chatbot.tools import execute_confirmed_action
from reservations.models import Reservation
from reservations.services import create_batch_reservation


@pytest.mark.django_db
def test_ui_form_stamps_created_by(client_logged, user, machine, site):
    """POST formularza tworzenia → reservation.created_by == zalogowany user."""
    start = date.today() + timedelta(days=3)
    end = date.today() + timedelta(days=6)
    response = client_logged.post(
        reverse("reservations:create"),
        data={
            "machine": machine.pk,
            "site": site.pk,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "person": "Jan Kowalski",
            "address": "ul. Polna 5, Kraków",
            "responsible_person": "Anna Nowak",
            "notes": "",
        },
    )
    assert response.status_code in (204, 302)
    reservation = Reservation.objects.latest("pk")
    assert reservation.created_by == user


@pytest.mark.django_db
def test_quick_reserve_stamps_created_by(client_logged, user, machine):
    """Quick-reserve (HTMX) → reservation.created_by == zalogowany user."""
    start = date.today() + timedelta(days=3)
    end = date.today() + timedelta(days=6)
    response = client_logged.post(
        reverse("reservations:quick_reserve"),
        data={
            "machine_uid": machine.uid,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert response.status_code == 200
    reservation = Reservation.objects.latest("pk")
    assert reservation.created_by == user


@pytest.mark.django_db
def test_chatbot_executor_stamps_created_by(user, machine, site):
    """execute_confirmed_action(create_reservation, …, user) → created_by == user."""
    start = date.today() + timedelta(days=3)
    end = date.today() + timedelta(days=6)
    params = {
        "machine_uid": machine.uid,
        "site_project_number": site.project_number,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "person": "Jan Kowalski",
        "address": "ul. Polna 5, Kraków",
        "responsible_person": "Anna Nowak",
    }
    result = execute_confirmed_action("create_reservation", params, user)
    assert "utworzona" in result.lower()
    reservation = Reservation.objects.latest("pk")
    assert reservation.created_by == user


@pytest.mark.django_db
def test_batch_create_stamps_created_by(user, machine, second_machine, site):
    """Batch (B-7) → KAŻDA rezerwacja grupy ma ``created_by`` == przekazany user.

    Ścieżka batch tworzy N rezerwacji w pętli; pominięcie ``created_by`` na
    którejkolwiek pozycji daje ``NULL`` = brak maila potwierdzającego (F2) przy
    zielonych testach pozostałych ścieżek.
    """
    start = date.today() + timedelta(days=3)
    end = date.today() + timedelta(days=6)
    result = create_batch_reservation(
        machine_ids=[machine.pk, second_machine.pk],
        site_id=site.pk,
        start_date=start,
        end_date=end,
        person="Jan Kowalski",
        created_by=user,
    )
    assert result["created_count"] == 2
    batch_reservations = Reservation.objects.filter(batch_id=result["batch_id"])
    assert batch_reservations.count() == 2
    assert all(res.created_by == user for res in batch_reservations)
