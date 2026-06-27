"""Testy bazodanowych CHECK-constraintów na polach statusu/typu.

Django ``choices`` waliduje tylko w ``full_clean`` — które omijają zapisy
``update_fields`` i surowe importy. CHECK-constrainty czynią nieprawidłową
wartość strukturalnie niemożliwą (Postgres odrzuca INSERT/UPDATE). Te testy
pełnią też rolę strażnika DRYFU: jeśli ktoś doda wartość do ``choices``, ale
nie do constraintu, pętla „wszystkie poprawne akceptowane" padnie.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from machines.factories import MachineFactory
from machines.models import Machine
from reservations.factories import ConstructionSiteFactory, ReservationFactory
from reservations.models import ConstructionSite, Reservation
from service.factories import ServiceRecordFactory
from service.models import ServiceRecord

# ``transaction=True`` — te testy celowo wywołują IntegrityError (naruszenie
# CHECK). Pod współbieżnym xdist savepoint-rollback w współdzielonej transakcji
# potrafił zostawić „aborted transaction" przeciekający do kolejnego testu na
# tym samym workerze. Realne transakcje (flush per test) izolują to pewnie.
pytestmark = pytest.mark.django_db(transaction=True)


def _rejects(model, pk, **bad):
    """Update z nieprawidłową wartością MUSI rzucić IntegrityError (CHECK)."""
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.filter(pk=pk).update(**bad)


def test_reservation_status_constraint():
    res = ReservationFactory(machine=MachineFactory())
    for value in Reservation.Status.values:  # drift guard — wszystkie choices OK
        assert Reservation.objects.filter(pk=res.pk).update(status=value) == 1
    _rejects(Reservation, res.pk, status="OCZEKUJACA")  # wielkie litery = nielegalne
    _rejects(Reservation, res.pk, status="cokolwiek")


def test_constructionsite_status_constraint():
    site = ConstructionSiteFactory()
    for value in ConstructionSite.Status.values:
        assert ConstructionSite.objects.filter(pk=site.pk).update(status=value) == 1
    _rejects(ConstructionSite, site.pk, status="AKTYWNA")


def test_machine_status_constraint():
    machine = MachineFactory()
    for value in Machine.Status.values:
        assert Machine.objects.filter(pk=machine.pk).update(status=value) == 1
    _rejects(Machine, machine.pk, status="w magazynie")  # zła wielkość liter


def test_servicerecord_type_constraint():
    record = ServiceRecordFactory(machine=MachineFactory())
    for value in ServiceRecord.RecordType.values:
        assert ServiceRecord.objects.filter(pk=record.pk).update(record_type=value) == 1
    _rejects(ServiceRecord, record.pk, record_type="przeglad")  # bez ogonka = nielegalne
