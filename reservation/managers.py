"""Custom :class:`~django.db.models.Manager` for the ``Reservation`` model.

Centralises queryset helpers so views and services do not have to spell out
the same ``filter(status__in=(...))`` over and over again. Matches the
``machines.MachineManager`` convention.
"""

from __future__ import annotations

from datetime import date

from django.db import models
from django.db.models import Q


class ReservationManager(models.Manager):
    """Domain-aware queryset helpers for :class:`reservations.models.Reservation`.

    The manager does not import the model directly to avoid a circular import
    — Django wires :attr:`ReservationManager.model` automatically. String
    literals (``"oczekująca"`` / ``"potwierdzona"`` / …) are used instead of
    ``Reservation.Status.X`` for that same reason; they are kept in sync with
    the ``TextChoices`` on the model (covered by tests).
    """

    # ------------------------------------------------------------------
    # Lifecycle filters
    # ------------------------------------------------------------------

    def active(self):
        """Reservations that still affect machine availability."""
        return self.filter(status__in=("oczekująca", "potwierdzona"))

    def pending(self):
        """Pending reservations waiting for approval."""
        return self.filter(status="oczekująca")

    def confirmed(self):
        """Confirmed reservations (counted by ``run_daily_sync``)."""
        return self.filter(status="potwierdzona")

    def cancelled(self):
        """Cancelled reservations (kept for audit but not for planning)."""
        return self.filter(status="anulowana")

    def completed(self):
        """Finished reservations (machine already returned)."""
        return self.filter(status="zakończona")

    # ------------------------------------------------------------------
    # Date-range filters
    # ------------------------------------------------------------------

    def for_period(self, start: date, end: date):
        """Reservations overlapping the inclusive ``[start, end]`` interval.

        Touching dates (``end_a == start_b``) count as overlap — same rule
        as :func:`reservations.services.has_conflict`. Używane przez
        ``TimelineView`` i conflict detection (jedna metoda — bez aliasów,
        aby uniknąć pułapki "która jest kanoniczna").
        """
        return self.filter(start_date__lte=end, end_date__gte=start)

    def active_in_period(self, start: date, end: date):
        """:meth:`active` ∩ :meth:`for_period` — handy shortcut."""
        return self.active().filter(start_date__lte=end, end_date__gte=start)

    def conflicts_for(
        self,
        machine_id: int,
        start: date,
        end: date,
        exclude_pk: int | None = None,
    ):
        """Open reservations on ``machine_id`` that overlap ``[start, end]``.

        Used by :func:`reservations.services.has_conflict` and the
        ``CheckConflictView`` HTMX endpoint.
        """
        qs = self.active_in_period(start, end).filter(machine_id=machine_id)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def overdue(self, today: date | None = None):
        """Confirmed reservations whose ``end_date`` is in the past.

        These are the rows that ``run_daily_sync`` extends under the
        "Hard Return Policy" (the machine has not been returned on time).
        """
        today = today or date.today()
        return self.confirmed().filter(end_date__lt=today)

    def upcoming(self, today: date | None = None):
        """Confirmed reservations starting today or later."""
        today = today or date.today()
        return self.confirmed().filter(start_date__gte=today)

    def active_today(self, today: date | None = None):
        """Confirmed reservations whose period covers ``today``."""
        today = today or date.today()
        return self.confirmed().filter(start_date__lte=today, end_date__gte=today)

    def for_machine(self, machine_id: int):
        """All reservations for a single machine (any status)."""
        return self.filter(machine_id=machine_id)

    def for_site(self, site_id: int):
        """All reservations attached to a single site."""
        return self.filter(site_id=site_id)

    def search(self, query: str):
        """Free-text search over person / address / notes / site name."""
        if not query:
            return self.all()
        return self.filter(
            Q(person__icontains=query)
            | Q(address__icontains=query)
            | Q(notes__icontains=query)
            | Q(site__name__icontains=query)
            | Q(site__project_number__icontains=query)
        )
