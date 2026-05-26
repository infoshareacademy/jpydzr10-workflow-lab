"""Step implementations for ``service_record.feature``.

Pokrywa kontrakt :func:`service.services.create_service_record`:

* przegląd kwartalny → ``inspection_date += 3 mo`` (przez relativedelta,
  nie 90 dni — różne miesiące mają różną liczbę dni),
* naprawa → ``inspection_date`` bez zmian,
* ``performed_date > today`` → ``ValidationError``.

Scenariusz z freezem ``today`` używa lokalnego ``freezegun.freeze_time``
przez fixture (ten sam pattern co w ``test_machine_inspection.py``).
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from freezegun import freeze_time
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from machines.models import Machine
from service.services import create_service_record

scenarios("../features/service_record.feature")


# ----------------------------------------------------------------------------
# GIVEN
# ----------------------------------------------------------------------------


@given(parsers.parse('zamrożoną datę "{today}"'), target_fixture="frozen_today")
def given_frozen_today(today: str):
    freezer = freeze_time(today)
    freezer.start()
    yield date.fromisoformat(today)
    freezer.stop()


@given(
    parsers.parse('maszynę o UID "{uid}" z datą przeglądu "{inspection}"'),
    target_fixture="machine",
)
def given_machine(uid: str, inspection: str) -> Machine:
    return MachineFactory(uid=uid, inspection_date=date.fromisoformat(inspection))


# ----------------------------------------------------------------------------
# WHEN
# ----------------------------------------------------------------------------


@when(
    parsers.parse(
        'serwisant rejestruje wpis "{record_type}" dla maszyny "{uid}" '
        'z datą wykonania "{performed}"'
    )
)
def when_create_record(record_type: str, uid: str, performed: str, context: dict) -> None:
    machine = Machine.objects.get(uid=uid)
    # Pinujemy ``today`` na 2026-12-31 (max performed_date w scenariuszach
    # success), żeby walidacja "future" nie odrzucała poprawnych wpisów.
    context["record"] = create_service_record(
        machine=machine,
        record_type=record_type,
        performed_date=date.fromisoformat(performed),
        today=date.fromisoformat("2026-12-31"),
    )
    context["error"] = None


@when(
    parsers.parse(
        'serwisant próbuje zarejestrować wpis "{record_type}" dla maszyny "{uid}" '
        'z datą wykonania "{performed}"'
    )
)
def when_try_create_record(record_type: str, uid: str, performed: str, context: dict) -> None:
    machine = Machine.objects.get(uid=uid)
    try:
        # NIE pinujemy today — pozwala freeze_time z @given działać.
        create_service_record(
            machine=machine,
            record_type=record_type,
            performed_date=date.fromisoformat(performed),
        )
        context["error"] = None
    except ValidationError as exc:
        context["error"] = exc


# ----------------------------------------------------------------------------
# THEN
# ----------------------------------------------------------------------------


@then(parsers.parse('maszyna "{uid}" ma datę przeglądu ustawioną na "{expected}"'))
def then_machine_inspection_date(uid: str, expected: str) -> None:
    machine = Machine.objects.get(uid=uid)
    assert machine.inspection_date == date.fromisoformat(expected), (
        f"Maszyna {uid}: oczekiwana data przeglądu {expected}, jest {machine.inspection_date}."
    )


@then(parsers.parse('próba kończy się błędem ValidationError zawierającym "{fragment}"'))
def then_validation_error(fragment: str, context: dict) -> None:
    assert context["error"] is not None, "Oczekiwano ValidationError."
    assert isinstance(context["error"], ValidationError)
    messages = " ".join(context["error"].messages) if hasattr(context["error"], "messages") else ""
    if not messages:
        # Czasem ValidationError wraz z message_dict — sklejamy z dictu.
        messages = " ".join(v for errs in context["error"].message_dict.values() for v in errs)
    assert fragment in messages, f"Komunikat błędu '{messages}' nie zawiera fragmentu '{fragment}'."


pytestmark = [pytest.mark.integration, pytest.mark.django_db]
