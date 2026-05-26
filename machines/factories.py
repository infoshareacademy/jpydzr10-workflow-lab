"""factory_boy fixtures for :class:`machines.models.Machine`.

Used by the test suite and the ``seed_machines`` management command. All text
fields use Polish locale (``pl_PL``) so demo data looks realistic to the
operator persona during code reviews.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from .models import Machine


class MachineFactory(DjangoModelFactory):
    """Baseline factory — produces an *available* machine in the warehouse."""

    class Meta:
        model = Machine
        django_get_or_create = ("uid",)

    uid = factory.Sequence(lambda n: f"M-{n:04d}")
    name = factory.LazyAttribute(lambda o: f"{o.machine_type.title()} {o.uid}")
    machine_type = factory.Iterator(
        [
            Machine.Type.KOPARKA,
            Machine.Type.MINIKOPARKA,
            Machine.Type.PODNOSNIK_NOZYCOWY,
            Machine.Type.AGREGAT,
        ]
    )
    model = factory.Faker("bothify", text="Model ###-??", locale="pl_PL")
    capacity = factory.Faker("random_int", min=100, max=5000)
    inspection_date = factory.Faker("date_between", start_date="-180d", end_date="+180d")
    location = "Magazyn"
    status = Machine.Status.W_MAGAZYNIE
    manufacturer = factory.Faker("company", locale="pl_PL")
    serial_number = factory.Faker("bothify", text="SN-########")
    build_year = factory.Faker("random_int", min=2010, max=2025)
    notes = ""


class AvailableMachineFactory(MachineFactory):
    """Trait — machine ready to be reserved (warehouse)."""

    status = Machine.Status.W_MAGAZYNIE
    location = "Magazyn"


class OnSiteMachineFactory(MachineFactory):
    """Trait — machine currently deployed to a construction site."""

    status = Machine.Status.NA_BUDOWIE
    location = factory.Faker("street_address", locale="pl_PL")


class InServiceMachineFactory(MachineFactory):
    """Trait — machine taken offline for maintenance."""

    status = Machine.Status.W_SERWISIE
    location = "Serwis"


class OverdueInspectionMachineFactory(MachineFactory):
    """Trait — machine whose inspection date is in the past."""

    inspection_date = factory.Faker("date_between", start_date="-365d", end_date="-1d")
