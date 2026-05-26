"""Step implementations for ``reservation_conflict.feature``.

Trzy scenariusze:

1. Overlap dwóch potwierdzonych rezerwacji → ValidationError.
2. Stykające się daty (``end_a == start_b``) — traktowane jako konflikt
   (M1 rule, kept for M2 — patrz ``reservations.services.has_conflict``).
3. Anulowana rezerwacja jest ignorowana przy detekcji konfliktów.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    ConfirmedReservationFactory,
    ConstructionSiteFactory,
)
from reservations.models import Reservation
from reservations.services import create_reservation

scenarios("../features/reservation_conflict.feature")


# ----------------------------------------------------------------------------
# GIVEN
# ----------------------------------------------------------------------------


@given(
    parsers.parse('maszynę o UID "{uid}" ze statusem "{status}"'),
    target_fixture="machine",
)
def given_machine(uid: str, status: str) -> Machine:
    return MachineFactory(uid=uid, status=status)


@given(
    parsers.parse(
        'istniejącą rezerwację maszyny "{uid}" od "{start}" do "{end}" ze statusem "{status}"'
    )
)
def given_existing_reservation(uid: str, start: str, end: str, status: str, machine) -> None:
    db_machine = Machine.objects.get(uid=uid)
    site = ConstructionSiteFactory()
    factory_class = (
        CancelledReservationFactory if status == "anulowana" else ConfirmedReservationFactory
    )
    factory_class(
        machine=db_machine,
        site=site,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        status=status,
    )


# ----------------------------------------------------------------------------
# WHEN
# ----------------------------------------------------------------------------


@when(parsers.parse('próbuję utworzyć rezerwację maszyny "{uid}" od "{start}" do "{end}"'))
def when_try_create_conflict(uid: str, start: str, end: str, context: dict) -> None:
    db_machine = Machine.objects.get(uid=uid)
    try:
        create_reservation(
            machine_id=db_machine.pk,
            site_id=None,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
            person="Anna Testowa",
            today=date.fromisoformat("2026-06-01"),
        )
        context["error"] = None
    except ValidationError as exc:
        context["error"] = exc


@when(
    parsers.parse(
        'magazynier tworzy nową rezerwację maszyny "{uid}" od "{start}" '
        'do "{end}" dla osoby "{person}"'
    )
)
def when_create_after_cancelled(uid: str, start: str, end: str, person: str, context: dict) -> None:
    db_machine = Machine.objects.get(uid=uid)
    context["reservation"] = create_reservation(
        machine_id=db_machine.pk,
        site_id=None,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        person=person,
        today=date.fromisoformat("2026-08-15"),
    )


# ----------------------------------------------------------------------------
# THEN
# ----------------------------------------------------------------------------


@then(parsers.parse('próba kończy się błędem ValidationError zawierającym "{fragment}"'))
def then_validation_error_contains(fragment: str, context: dict) -> None:
    assert context["error"] is not None, "Oczekiwano ValidationError, ale wywołanie się powiodło."
    assert isinstance(context["error"], ValidationError)
    messages = " ".join(context["error"].messages)
    assert fragment in messages, (
        f"Komunikat błędu '{messages}' nie zawiera oczekiwanego fragmentu '{fragment}'."
    )


@then("rezerwacja jest poprawnie utworzona")
def then_reservation_created(context: dict) -> None:
    assert context["reservation"].pk is not None
    assert context["reservation"].status == Reservation.Status.OCZEKUJACA


@then(parsers.parse("w bazie są dokładnie {count:d} rezerwacje"))
@then(parsers.parse("w bazie jest dokładnie {count:d} rezerwacji"))
@then(parsers.parse("w bazie jest dokładnie {count:d} rezerwacja"))
def then_reservation_count(count: int) -> None:
    assert Reservation.objects.count() == count


pytestmark = [pytest.mark.integration, pytest.mark.django_db]
