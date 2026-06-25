"""Models for the service app — periodic inspections and repairs of machines.

The :class:`ServiceRecord` model evolves the Milestone 1 console
``ServiceRecord`` (see ``archive/milestone-1/console/models.py``) into a
relational Django model:

* the free-form ``record_type`` string (``"przegląd" | "naprawa"``) becomes
  the four-valued :class:`ServiceRecord.RecordType` ``TextChoices`` so the
  inspection-interval mapping (``INSPECTION_INTERVALS``) is type-safe,
* ``record_date`` (M1 ISO string) → ``performed_date`` (proper ``DateField``)
  to keep parity with :attr:`Reservation.start_date` naming,
* ``next_inspection`` is computed by the service layer
  (:func:`service.services.create_service_record`) using
  :func:`dateutil.relativedelta.relativedelta` so leap years / month-length
  edge cases are correct — never the 30-day approximation M1 used.

Every save is captured by ``django_simple_history`` (audit trail). Files
attached to inspections (``inspection_document``) are validated by
:func:`core.validators.validate_document_upload` (PDF only, 20 MB max).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel
from core.validators import validate_document_upload

from .managers import ServiceRecordManager

# Mapping :class:`ServiceRecord.RecordType` value → liczba miesięcy do następnego
# obowiązkowego przeglądu. Module-level constant — nie używamy magic numbers
# wewnątrz :func:`services.create_service_record` (ZASADA #8).
INSPECTION_INTERVALS: dict[str, int] = {
    "przegląd_kwartalny": 3,
    "przegląd_polroczny": 6,
    "przegląd_roczny": 12,
}


class ServiceRecord(TimestampedModel):
    """Wpis serwisowy — przegląd techniczny lub naprawa maszyny.

    Cykl życia w ramach maszyny:

    * przegląd (``przegląd_*``) aktualizuje
      :attr:`machines.Machine.inspection_date` na nowszą z dwóch wartości
      (zachowuje się jak "max" — nigdy nie cofa daty),
    * naprawa (``naprawa``) ma ``next_inspection = NULL`` i nie wpływa na
      ``Machine.inspection_date`` (tylko wlicza koszt do raportu).
    """

    class RecordType(models.TextChoices):
        """Rodzaj wpisu — wartości w DB po polsku (snake_case dla compatibility)."""

        PRZEGLAD_KWARTALNY = "przegląd_kwartalny", _("Przegląd kwartalny (3 mc)")
        PRZEGLAD_POLROCZNY = "przegląd_polroczny", _("Przegląd półroczny (6 mc)")
        PRZEGLAD_ROCZNY = "przegląd_roczny", _("Przegląd roczny (12 mc)")
        NAPRAWA = "naprawa", _("Naprawa")

    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.PROTECT,
        related_name="service_records",
        verbose_name="Maszyna",
    )
    record_type = models.CharField(
        max_length=30,
        choices=RecordType.choices,
        db_index=True,
        verbose_name="Typ wpisu",
    )
    performed_date = models.DateField(
        db_index=True,
        verbose_name="Data wykonania",
        help_text="Data faktycznego wykonania przeglądu lub naprawy.",
    )
    performed_by = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Wykonawca",
        help_text="Imię i nazwisko serwisanta lub nazwa firmy zewnętrznej.",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Opis",
        help_text="Szczegóły wykonanych prac, wymienione części, uwagi.",
    )
    cost = MoneyField(
        max_digits=10,
        decimal_places=2,
        default_currency="EUR",
        default=Decimal("0.00"),
        verbose_name="Koszt",
    )
    inspection_document = models.FileField(
        upload_to="inspections/%Y/%m/",
        null=True,
        blank=True,
        validators=[validate_document_upload],
        verbose_name="Protokół (PDF)",
        help_text="Plik PDF (max 20 MB).",
    )
    next_inspection = models.DateField(
        null=True,
        blank=True,
        verbose_name="Następny przegląd",
        help_text="Wyliczane automatycznie dla przeglądów; puste dla napraw.",
    )

    history = HistoricalRecords()

    objects = ServiceRecordManager()

    class Meta:
        verbose_name = "Wpis serwisowy"
        verbose_name_plural = "Wpisy serwisowe"
        ordering = ["-performed_date"]
        indexes = [
            models.Index(fields=["machine", "-performed_date"]),
            models.Index(fields=["record_type", "performed_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.machine.uid} {self.performed_date} {self.get_record_type_display()}"

    def __repr__(self) -> str:
        return (
            f"ServiceRecord(pk={self.pk!r}, machine_id={self.machine_id!r}, "
            f"record_type={self.record_type!r}, performed_date={self.performed_date!r})"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_inspection(self) -> bool:
        """``True`` when the record is any of the ``przegląd_*`` types."""
        return self.record_type != self.RecordType.NAPRAWA

    def is_overdue_followup(self, today: date | None = None) -> bool:
        """``True`` when ``next_inspection`` is set and already in the past.

        Useful for the "Zaległe przeglądy" widget on the reports page.
        Method (not property) because it accepts an injected ``today`` for
        freezegun-style tests.
        """
        if not self.next_inspection:
            return False
        return self.next_inspection < (today or date.today())
