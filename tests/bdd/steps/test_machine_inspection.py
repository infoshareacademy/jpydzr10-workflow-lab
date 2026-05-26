"""Step implementations for ``machine_inspection.feature``.

Każdy scenariusz najpierw ustawia ``today`` przez ``freezegun``, potem
tworzy maszynę z konkretną ``inspection_date`` i sprawdza wartość property
``Machine.inspection_status`` (``"ok" | "warning" | "overdue" | "unknown"``).

Wartość progowa "warning" to ``INSPECTION_WARNING_DAYS = 14`` (zob.
``machines.models``); scenariusze celowo używają dat z różnymi odstępami
żeby pokryć trzy bucket-y.
"""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from machines.models import Machine

scenarios("../features/machine_inspection.feature")


# ----------------------------------------------------------------------------
# GIVEN
# ----------------------------------------------------------------------------


@given(parsers.parse('zamrożoną datę "{today}"'), target_fixture="frozen_today")
def given_frozen_today(today: str):
    """Aktywuje ``freezegun`` na cały scenariusz.

    Yield kontekstu freeze'a — pytest-bdd handle'uje fixture lifecycle, więc
    freeze trwa do końca scenariusza (yield zostaje po then-ach).
    """
    freezer = freeze_time(today)
    freezer.start()
    yield date.fromisoformat(today)
    freezer.stop()


@given(
    parsers.parse('maszynę o UID "{uid}" z datą przeglądu "{inspection}"'),
    target_fixture="machine",
)
def given_machine_with_inspection(uid: str, inspection: str) -> Machine:
    return MachineFactory(uid=uid, inspection_date=date.fromisoformat(inspection))


# ----------------------------------------------------------------------------
# WHEN
# ----------------------------------------------------------------------------


@when(parsers.parse('odczytuję status przeglądu maszyny "{uid}"'))
def when_read_status(uid: str, context: dict) -> None:
    context["status"] = Machine.objects.get(uid=uid).inspection_status


# ----------------------------------------------------------------------------
# THEN
# ----------------------------------------------------------------------------


@then(parsers.parse('status przeglądu maszyny wynosi "{expected}"'))
def then_status_equals(expected: str, context: dict) -> None:
    assert context["status"] == expected, (
        f"Oczekiwano statusu '{expected}', otrzymano '{context['status']}'."
    )


pytestmark = [pytest.mark.integration, pytest.mark.django_db]
