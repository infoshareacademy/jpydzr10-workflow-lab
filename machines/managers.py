"""Custom :class:`~django.db.models.Manager` for the ``Machine`` model.

Centralising these filters keeps views and services thin and prevents the
"every caller writes their own ``filter(status=...)`` query" anti-pattern.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import models


class MachineManager(models.Manager):
    """Domain-aware queryset helpers for :class:`machines.models.Machine`.

    Defined in its own module so that ``models.py`` can reference it without a
    circular import (the manager itself does not import the model — Django
    wires :attr:`MachineManager.model` automatically).
    """

    def available(self):
        """Machines currently in the warehouse and free to reserve."""
        return self.filter(status="W magazynie")

    def overdue_inspection(self, today: date | None = None):
        """Machines whose ``inspection_date`` is strictly in the past."""
        today = today or date.today()
        return self.filter(inspection_date__lt=today)

    def upcoming_inspection(self, days: int = 14, today: date | None = None):
        """Machines with an inspection scheduled in the next ``days`` days.

        Includes both "due today" and "due in N days" — useful for the
        sidebar reminder widget on the home dashboard.
        """
        today = today or date.today()
        return self.filter(
            inspection_date__gte=today,
            inspection_date__lte=today + timedelta(days=days),
        )

    def by_type(self, machine_type: str):
        """Filter by the :class:`Machine.Type` value (Polish string)."""
        return self.filter(machine_type=machine_type)
