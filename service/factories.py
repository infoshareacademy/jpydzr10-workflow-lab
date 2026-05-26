"""factory_boy fixtures for :class:`service.models.ServiceRecord`.

Used by the test suite and the ``seed_service`` management command. The
``machine`` is intentionally required — there is no ``SubFactory`` for
:class:`machines.factories.MachineFactory` to avoid a circular import and
because in real test code we always want to pin the machine explicitly.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from .models import ServiceRecord


class ServiceRecordFactory(DjangoModelFactory):
    """Baseline factory — produces a record for the *given* machine.

    Caller MUST pass ``machine=...`` (see module docstring). Picks an
    arbitrary :class:`ServiceRecord.RecordType` via ``Iterator``; subclasses
    pin the type to a single value.
    """

    class Meta:
        model = ServiceRecord

    # ``machine`` has no default — callers pass it explicitly.
    record_type = factory.Iterator([t.value for t in ServiceRecord.RecordType])
    performed_date = factory.Faker("date_between", start_date="-365d", end_date="today")
    performed_by = factory.Faker("name", locale="pl_PL")
    description = factory.Faker("sentence", nb_words=8, locale="pl_PL")
    cost = factory.Faker("pydecimal", left_digits=4, right_digits=2, positive=True)


class InspectionFactory(ServiceRecordFactory):
    """Trait — quarterly inspection (``przegląd_kwartalny``)."""

    record_type = ServiceRecord.RecordType.PRZEGLAD_KWARTALNY


class HalfYearInspectionFactory(ServiceRecordFactory):
    """Trait — half-year inspection (``przegląd_polroczny``)."""

    record_type = ServiceRecord.RecordType.PRZEGLAD_POLROCZNY


class AnnualInspectionFactory(ServiceRecordFactory):
    """Trait — annual inspection (``przegląd_roczny``)."""

    record_type = ServiceRecord.RecordType.PRZEGLAD_ROCZNY


class RepairFactory(ServiceRecordFactory):
    """Trait — repair (``naprawa``), no ``next_inspection``."""

    record_type = ServiceRecord.RecordType.NAPRAWA
