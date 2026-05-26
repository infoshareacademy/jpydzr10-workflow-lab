"""Step implementations for ``reservation_creation.feature``.

Mapuje kroki Gherkin (Polish) na operacje na bazie testowej.

Konwencja:

* ``@given`` ze stringiem dokładnie odpowiadającym tekstowi z ``.feature``
  (parsers.parse zostawia placeholders w cudzysłowach jako parametry),
* ``target_fixture`` używamy tam gdzie krok produkuje obiekt domenowy
  potrzebny innym krokom (np. ``machine``, ``site``); reszta korzysta z
  ``context`` (dict per scenariusz, zob. ``tests/bdd/conftest.py``).
"""

from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from machines.models import Machine
from reservations.factories import ConstructionSiteFactory
from reservations.models import Reservation
from reservations.services import create_reservation

scenarios("../features/reservation_creation.feature")


# ----------------------------------------------------------------------------
# GIVEN — seed
# ----------------------------------------------------------------------------


@given(
    parsers.parse('maszynę o UID "{uid}" ze statusem "{status}"'),
    target_fixture="machine",
)
def given_machine(uid: str, status: str) -> Machine:
    return MachineFactory(uid=uid, status=status)


@given(
    parsers.parse('budowę o numerze "{project_number}" o nazwie "{name}"'),
    target_fixture="site",
)
def given_site(project_number: str, name: str):
    return ConstructionSiteFactory(project_number=project_number, name=name)


# ----------------------------------------------------------------------------
# WHEN — action
# ----------------------------------------------------------------------------


@when(
    parsers.parse(
        'magazynier tworzy rezerwację maszyny "{uid}" od "{start}" do "{end}" dla osoby "{person}"'
    )
)
def when_create_reservation(
    uid: str,
    start: str,
    end: str,
    person: str,
    machine,
    site,
    context: dict,
) -> None:
    db_machine = Machine.objects.get(uid=uid)
    context["reservation"] = create_reservation(
        machine_id=db_machine.pk,
        site_id=site.pk,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        person=person,
        today=date.fromisoformat("2026-05-30"),  # < start to ominąć past check
    )


# ----------------------------------------------------------------------------
# THEN — assertion
# ----------------------------------------------------------------------------


@then(parsers.parse('rezerwacja jest utworzona ze statusem "{status}"'))
def then_reservation_status(status: str, context: dict) -> None:
    assert context["reservation"].pk is not None
    assert context["reservation"].status == status


@then(parsers.parse("w bazie jest dokładnie {count:d} rezerwacja"))
@then(parsers.parse("w bazie są dokładnie {count:d} rezerwacje"))
@then(parsers.parse("w bazie jest dokładnie {count:d} rezerwacji"))
def then_reservation_count(count: int) -> None:
    assert Reservation.objects.count() == count


# Auto-mark all generated tests jako ``integration`` + ``django_db`` (DB-touching).
pytestmark = [pytest.mark.integration, pytest.mark.django_db]
