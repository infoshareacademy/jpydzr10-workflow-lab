"""get_machine_service_history — nowe narzędzie odczytu (historia serwisowa maszyny).

Odpowiada na pytania typu „kiedy był ostatni przegląd/serwis maszyny X" — dotąd
brakowało takiego narzędzia (bot mylił „ostatni" z datą NASTĘPNEGO przeglądu ze
statusu). Dane kosztowe → za uprawnieniem ``service.view_servicerecord``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from chatbot.tools import (
    READ_ACTION_PERMS,
    READ_ACTIONS,
    get_machine_service_history,
)
from machines.models import Machine
from service.models import ServiceRecord


@pytest.fixture
def machine_with_history(db):
    m = Machine.objects.create(
        uid="KOP-050",
        name="Koparka 50",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )
    ServiceRecord.objects.create(
        machine=m,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=date.today() - timedelta(days=30),
        cost=Decimal("150.00"),
        description="stara naprawa",
    )
    ServiceRecord.objects.create(
        machine=m,
        record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
        performed_date=date.today() - timedelta(days=5),
        cost=Decimal("80.00"),
        description="ostatni przegląd",
    )
    return m


@pytest.mark.django_db
class TestServiceHistory:
    def test_returns_recent_first(self, machine_with_history):
        res = get_machine_service_history("KOP-050")
        assert res.error is None
        assert res.found == 2
        # Najnowszy wpis pierwszy (ordering -performed_date).
        assert res.records[0].description == "ostatni przegląd"
        assert res.records[0].cost == 80.0
        assert "kwartalny" in res.records[0].record_type.lower()
        assert res.records[1].description == "stara naprawa"

    def test_limit_respected(self, machine_with_history):
        res = get_machine_service_history("KOP-050", limit=1)
        assert res.found == 1
        assert res.records[0].description == "ostatni przegląd"

    def test_unknown_machine_returns_error(self, db):
        res = get_machine_service_history("NIE-999")
        assert res.error is not None
        assert res.found == 0
        assert res.records == []

    def test_uid_normalized_case_insensitive(self, machine_with_history):
        res = get_machine_service_history("kop-050")
        assert res.error is None
        assert res.found == 2

    def test_registered_and_cost_gated(self):
        # Zarejestrowane jako read-action ORAZ za uprawnieniem (ujawnia koszty).
        assert "get_machine_service_history" in READ_ACTIONS
        assert READ_ACTION_PERMS["get_machine_service_history"] == ("service.view_servicerecord",)
