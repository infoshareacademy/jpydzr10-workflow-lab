"""Factory-boy fixtures for the reservations app.

Used by the test suite and the ``seed_reservations`` management command.
All factories produce Polish-language data via the ``pl_PL`` Faker locale.

Conventions:

* ``ConstructionSiteFactory`` uses ``django_get_or_create=("project_number",)``
  so repeated calls with the same ``project_number`` return the existing
  row instead of crashing on the unique constraint.
* ``ReservationFactory`` requires a ``machine`` — there is no sane default
  (you need a Machine in the DB first); fixtures pass one explicitly.
* :class:`PendingReservationFactory` / :class:`ConfirmedReservationFactory`
  / :class:`CancelledReservationFactory` / :class:`CompletedReservationFactory`
  are status traits (subclasses) — pick the one you need rather than passing
  ``status=...`` manually.
"""

from __future__ import annotations

from datetime import date, timedelta
from random import randint

import factory
from factory.django import DjangoModelFactory
from factory.faker import Faker

from .models import ConstructionSite, Reservation

# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


class ConstructionSiteFactory(DjangoModelFactory):
    """Generates a :class:`ConstructionSite` with a unique BUD-RRRR-NNN id.

    The sequence starts at 1 and increments per test session — combined with
    ``django_get_or_create`` this means ``ConstructionSiteFactory()`` always
    returns a *new* row in tests (unless you explicitly pass a duplicate
    ``project_number``).
    """

    class Meta:
        model = ConstructionSite
        django_get_or_create = ("project_number",)

    project_number = factory.Sequence(lambda n: f"BUD-2026-{(n % 999) + 1:03d}")
    name = Faker("street_name", locale="pl_PL")
    client_name = Faker("company", locale="pl_PL")
    address = Faker("street_address", locale="pl_PL")
    city = Faker("city", locale="pl_PL")
    status = ConstructionSite.Status.AKTYWNA


class ActiveSiteFactory(ConstructionSiteFactory):
    """Alias for the default factory — explicit ``status=AKTYWNA``."""

    status = ConstructionSite.Status.AKTYWNA


class CompletedSiteFactory(ConstructionSiteFactory):
    status = ConstructionSite.Status.ZAKONCZONA


class CancelledSiteFactory(ConstructionSiteFactory):
    status = ConstructionSite.Status.ANULOWANA


# =============================================================================
# RESERVATION
# =============================================================================


def _random_future_start() -> date:
    """Random date 1..30 days in the future."""
    return date.today() + timedelta(days=randint(1, 30))


def _random_duration_days() -> int:
    """Random reservation length, 1..14 days."""
    return randint(1, 14)


class ReservationFactory(DjangoModelFactory):
    """Generates a :class:`Reservation`.

    The caller MUST pass ``machine=...`` — there is no SubFactory for the
    Machine because :class:`machines.factories.MachineFactory` lives in the
    machines app and we do not want a circular import here.
    """

    class Meta:
        model = Reservation

    # ``machine`` has no default — passed explicitly by the test/seed caller.
    site = factory.SubFactory(ConstructionSiteFactory)
    start_date = factory.LazyFunction(_random_future_start)
    end_date = factory.LazyAttribute(
        lambda o: o.start_date + timedelta(days=_random_duration_days())
    )
    person = Faker("name", locale="pl_PL")
    address = Faker("street_address", locale="pl_PL")
    # Wave 14-A Bundle 4 -- responsible_person (kierownik/brygadzista na budowie).
    # Default Faker name zeby existing tests nie wymagaly explicit passingu.
    responsible_person = Faker("name", locale="pl_PL")
    notes = ""
    status = Reservation.Status.OCZEKUJACA


class PendingReservationFactory(ReservationFactory):
    """A reservation in ``oczekująca`` (default)."""

    status = Reservation.Status.OCZEKUJACA


class ConfirmedReservationFactory(ReservationFactory):
    """A reservation in ``potwierdzona`` — ready for ``run_daily_sync``."""

    status = Reservation.Status.POTWIERDZONA


class CancelledReservationFactory(ReservationFactory):
    status = Reservation.Status.ANULOWANA


class CompletedReservationFactory(ReservationFactory):
    status = Reservation.Status.ZAKONCZONA
