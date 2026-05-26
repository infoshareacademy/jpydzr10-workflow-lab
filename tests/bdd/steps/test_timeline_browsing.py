"""Step implementations for ``timeline_browsing.feature``.

Trzy scenariusze HTTP-level:

1. GET /rezerwacje/timeline/ dla zalogowanego usera → 200.
2. ?period=2week → JSON response z 14 dniami w ``day_list``.
3. ?machine_type=koparka → JSON ``machine_rows`` zawiera tylko maszyny
   tego typu (filtr po kolumnie ``Machine.machine_type``).

Używamy ``?format=json`` w scenariuszach 2 i 3 żeby pominąć templates
(timeline.html może wymagać F3-C frontendu — JSON response jest stabilny).
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from machines.models import Machine

scenarios("../features/timeline_browsing.feature")


# ----------------------------------------------------------------------------
# GIVEN
# ----------------------------------------------------------------------------


@given("zalogowanego magazyniera", target_fixture="logged_client")
def given_logged_client(authenticated_client: Client) -> Client:
    return authenticated_client


@given(parsers.parse('maszynę o UID "{uid}" ze statusem "{status}"'))
def given_machine(uid: str, status: str) -> Machine:
    return MachineFactory(uid=uid, status=status)


@given(parsers.parse('maszynę o UID "{uid}" typu "{machine_type}"'))
def given_machine_of_type(uid: str, machine_type: str) -> Machine:
    return MachineFactory(uid=uid, machine_type=machine_type)


# ----------------------------------------------------------------------------
# WHEN
# ----------------------------------------------------------------------------


@when(parsers.parse('magazynier wchodzi na adres "{url}"'))
def when_get_url(url: str, logged_client: Client, context: dict) -> None:
    context["response"] = logged_client.get(url)


# ----------------------------------------------------------------------------
# THEN
# ----------------------------------------------------------------------------


@then(parsers.parse("odpowiedź ma status HTTP {status:d}"))
def then_status_code(status: int, context: dict) -> None:
    actual = context["response"].status_code
    assert actual == status, f"Oczekiwano HTTP {status}, otrzymano {actual}."


@then(parsers.parse("odpowiedź zawiera {count:d} dni w polu day_list"))
def then_day_list_length(count: int, context: dict) -> None:
    payload = json.loads(context["response"].content)
    assert len(payload["day_list"]) == count, (
        f"Oczekiwano {count} dni w day_list, jest {len(payload['day_list'])}."
    )


@then(parsers.parse('odpowiedź zawiera maszynę "{uid}" w machine_rows'))
def then_machine_in_rows(uid: str, context: dict) -> None:
    payload = json.loads(context["response"].content)
    uids = [row["uid"] for row in payload["machine_rows"]]
    assert uid in uids, f"Maszyna {uid} nie znaleziona w machine_rows={uids}."


@then(parsers.parse('odpowiedź nie zawiera maszyny "{uid}" w machine_rows'))
def then_machine_not_in_rows(uid: str, context: dict) -> None:
    payload = json.loads(context["response"].content)
    uids = [row["uid"] for row in payload["machine_rows"]]
    assert uid not in uids, (
        f"Maszyna {uid} została znaleziona w machine_rows={uids}, choć filtr powinien ją wykluczyć."
    )


pytestmark = [pytest.mark.integration, pytest.mark.django_db]
