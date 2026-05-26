"""Models for the reservations app — construction sites + reservations.

Statuses use Polish strings as ``value`` (with ``label`` identical) so DB
rows are self-explanatory and consistent with the ``machines`` app
convention (``W magazynie``, ``Na budowie`` …).

``ConstructionSite`` uses the local Polish project numbering format
``BUD-RRRR-NNN`` (project decision, M2 W1) — NOT the 9-digit Belgian format.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel

from .managers import ReservationManager

# Anchored regex — odrzuca ``BUD-2026-001-x`` i podobne przypadkowe prefiksy.
PROJECT_NUMBER_PATTERN = r"^BUD-\d{4}-\d{3}$"

PROJECT_NUMBER_VALIDATOR = RegexValidator(
    regex=PROJECT_NUMBER_PATTERN,
    message="Numer projektu musi być w formacie BUD-RRRR-NNN (np. BUD-2026-001).",
)


# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


class ConstructionSite(TimestampedModel):
    """Budowa, do której rezerwujemy maszyny. Lifecycle: aktywna → zakończona / anulowana."""

    class Status(models.TextChoices):
        AKTYWNA = "aktywna", "Aktywna"
        ZAKONCZONA = "zakończona", "Zakończona"
        ANULOWANA = "anulowana", "Anulowana"

    project_number = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        validators=[PROJECT_NUMBER_VALIDATOR],
        verbose_name=_("Numer projektu"),
        help_text="Format: BUD-RRRR-NNN (np. BUD-2026-001).",
    )
    name = models.CharField(max_length=200, verbose_name=_("Nazwa budowy"))
    client_name = models.CharField(max_length=200, blank=True, default="", verbose_name=_("Klient"))
    address = models.CharField(max_length=300, verbose_name=_("Adres"))
    city = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Miasto"))
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.AKTYWNA,
        db_index=True,
        verbose_name=_("Status"),
    )
    start_date = models.DateField(null=True, blank=True, verbose_name=_("Data rozpoczęcia"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("Planowana data zakończenia"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Notatki"))

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Budowa")
        verbose_name_plural = _("Budowy")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.project_number} — {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.AKTYWNA

    @property
    def active_reservation_count(self) -> int:
        return self.reservations.filter(
            status__in=(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
        ).count()

    @property
    def has_active_reservations(self) -> bool:
        return self.reservations.filter(
            status__in=(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
        ).exists()

    def clean(self) -> None:
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "Planowana data zakończenia musi być >= data rozpoczęcia."}
            )


# =============================================================================
# RESERVATION
# =============================================================================


class Reservation(TimestampedModel):
    """Rezerwacja jednej maszyny na zakres dat. ``site`` opcjonalne (legacy M1)."""

    class Status(models.TextChoices):
        OCZEKUJACA   = "oczekująca", "Oczekująca"
        POTWIERDZONA = "potwierdzona", "Potwierdzona"
        ANULOWANA    = "anulowana", "Anulowana"
        ZAKONCZONA   = "zakończona", "Zakończona"

    class CancellationReason(models.TextChoices):
        """B-2 — powody anulowania (raporty miesięczne). DB ASCII, label PL."""
        KLIENT_ZREZYGNOWAL = "klient_zrezygnowal", "Klient zrezygnował"
        AWARIA             = "awaria", "Awaria maszyny"
        ZMIANA_TERMINU     = "zmiana_terminu", "Zmiana terminu / przesunięcie"
        BRAK_DOSTEPNOSCI   = "brak_dostepnosci", "Brak dostępności maszyny"
        INNE               = "inne", "Inne (zobacz notatkę)"

    # FK do machines.Machine — string reference żeby uniknąć import-time circular dep.
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.PROTECT,
        related_name="reservations",
        verbose_name=_("Maszyna"),
    )
    site = models.ForeignKey(
        ConstructionSite,
        on_delete=models.PROTECT,
        related_name="reservations",
        null=True,
        blank=True,
        verbose_name=_("Budowa"),
    )
    start_date = models.DateField(db_index=True, verbose_name=_("Data początku"))
    end_date = models.DateField(db_index=True, verbose_name=_("Data końca"))
    person = models.CharField(max_length=100, verbose_name=_("Osoba rezerwująca"))
    # Wave 14-A Bundle 4 — adres dostawy wymagany w form, blank=True na modelu
    # żeby legacy M1 fixtures bez tego pola importowały się czysto.
    address = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("Adres dostawy")
    )
    # Wave 14-A Bundle 4 — kierownik / brygadzista na budowie (odrębny od ``person``).
    responsible_person = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name=_("Osoba odpowiedzialna na budowie"),
        help_text=_(
            "Imie i nazwisko kierownika/brygadzisty odpowiedzialnego za maszyne na budowie."
        ),
    )
    notes = models.TextField(blank=True, default="", verbose_name=_("Notatki"))
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OCZEKUJACA,
        db_index=True,
        verbose_name=_("Status"),
    )

    # B-2: powód anulowania — required przy status=ANULOWANA (service-layer validation).
    cancellation_reason = models.CharField(
        max_length=30,
        choices=CancellationReason.choices,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Powód anulowania"),
        help_text=_("Wymagane jeśli rezerwacja jest anulowana — używane w raportach."),
    )
    cancellation_note = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Notatka do powodu anulowania"),
    )

    # B-3: wcześniejszy zwrot — używamy w ``has_conflict`` zamiast end_date jeśli ustawione.
    actual_return_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Faktyczna data zwrotu"),
    )

    # B-6: wymiana mid-reservation — wskazuje na zastępczą rezerwację.
    # SET_NULL żeby usunięcie zastępczej nie wymazało historycznej.
    replaced_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replaces",
        verbose_name=_("Zastąpiona przez"),
    )

    # B-7: rezerwacja grupowa — wszystkie z batch dzielą ten sam UUID.
    batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("ID grupy rezerwacji"),
    )

    history = HistoricalRecords()

    objects = ReservationManager()

    class Meta:
        verbose_name = _("Rezerwacja")
        verbose_name_plural = _("Rezerwacje")
        ordering = ["-start_date"]
        indexes = [
            # Hot path: "all reservations for machine X newest-first" (detail + timeline).
            models.Index(fields=["machine", "-start_date"]),
            # Hot path: dashboard widgets ("upcoming pending", "active today").
            models.Index(fields=["status", "start_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.machine.uid} {self.start_date} - {self.end_date} ({self.person})"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.OCZEKUJACA, self.Status.POTWIERDZONA)

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def title(self) -> str:
        return f"{self.machine.uid} — {self.person}"

    def clean(self) -> None:
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Data końca musi być >= data początku."})
