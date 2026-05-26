"""Custom :class:`~django.db.models.Manager` for the :class:`ServiceRecord` model.

Centralises queryset helpers so views and reports never re-implement the same
``filter(...)`` chains. The manager itself is intentionally model-agnostic
(``self.filter(...)``) — Django wires ``self.model`` automatically and we
avoid a circular import from :mod:`service.models`.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import models


class ServiceRecordManager(models.Manager):
    """Domain-aware queryset helpers for :class:`service.models.ServiceRecord`."""

    def recent(self, days: int = 30, today: date | None = None):
        """Records performed in the last ``days`` days (default 30)."""
        today = today or date.today()
        return self.filter(performed_date__gte=today - timedelta(days=days))

    def by_machine(self, machine_id: int):
        """All records for a single machine, newest first."""
        return self.filter(machine_id=machine_id)

    def by_type(self, record_type: str):
        """Filter by :class:`ServiceRecord.RecordType` value."""
        return self.filter(record_type=record_type)

    def expensive(self, threshold: Decimal | float | int = Decimal("1000")):
        """Records whose ``cost`` is strictly greater than ``threshold``.

        Used by the reports view sidebar (``Drogie naprawy``). ``threshold``
        is coerced to :class:`Decimal` so floats from the URL ``?threshold=``
        do not blow up the comparison.
        """
        return self.filter(cost__gt=Decimal(str(threshold)))

    def inspections(self):
        """All records that are inspections (``przegląd_*``) — excludes naprawy."""
        return self.exclude(record_type="naprawa")
