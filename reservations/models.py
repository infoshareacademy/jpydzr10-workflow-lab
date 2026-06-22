"""Models for the reservations app — construction sites + reservations.

Statuses use Polish strings as ``value`` (with ``label`` identical) so DB
rows are self-explanatory and consistent with the ``machines`` app
convention (``W magazynie``, ``Na budowie`` …).

``ConstructionSite`` uses the local Polish project numbering format
``BUD-RRRR-NNN`` (project decision, M2 W1) — NOT a plain 9-digit numeric format.

``Reservation`` ties a :class:`machines.Machine` to a date range, optionally
referencing a :class:`ConstructionSite`. Status transitions are guarded in the
service layer (:mod:`reservations.services`) — the model itself only stores
the value; calling ``.save()`` directly does NOT trigger transition checks.

All ``status`` values are picked so they import cleanly from the historical
Milestone 1 JSON fixtures (``archive/milestone-1/data/reservations.json``)
without a data migration.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel

from .managers import ReservationManager

# Regex for the local Polish project number formats. Two supported forms
# (anchored to keep accidental prefixes / suffixes out):
#
# 1. ``10YYNNNNNNN`` (11 cyfr) — preferowany nowy format od 2026-05-31:
#    ``10`` (staly prefix) + ``YY`` (dwie cyfry roku) + 7-cyfrowy numer
#    sekwencyjny. Przyklad: ``10260000001`` = 1. budowa 2026.
# 2. ``BUD-RRRR-NNN`` (12 znakow) — legacy format z M2 W1. Zostaje
#    obslugiwany dla wstecznej kompatybilnosci (istniejacych budow, testow,
#    chatbot tools, archiwalnych dokumentow).
#
# Walidator akceptuje OBA formaty (alternacja regex). Anchory ``^...$``
# obejmuja cala alternacje przez zewnetrzna grupe non-capturing zeby `re.search`
# poprawnie dzialal i odrzucal prefiksy/sufiksy w obu wariantach.
PROJECT_NUMBER_PATTERN = r"^(?:10\d{2}\d{7}|BUD-\d{4}-\d{3})$"

PROJECT_NUMBER_VALIDATOR = RegexValidator(
    regex=PROJECT_NUMBER_PATTERN,
    message=(
        "Numer projektu musi byc w formacie 10YYNNNNN (np. 10260000001) "
        "lub starym BUD-RRRR-NNN (np. BUD-2026-001)."
    ),
)


# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


class ConstructionSite(TimestampedModel):
    """A construction site / project that machines are reserved for.

    A site groups reservations together so the magazynier can see at a glance
    "which machines are at job XY right now". It is optional on a reservation
    (you can still book ad-hoc without a site), but recommended for reporting.

    Lifecycle:

    * ``aktywna`` — the default; new reservations can be created.
    * ``zakończona`` — the project is finished; treated as read-only.
    * ``anulowana`` — never started / cancelled mid-way.
    """

    class Status(models.TextChoices):
        """Lifecycle of the site. Values are Polish on purpose (ZASADA #2)."""

        AKTYWNA = "aktywna", "Aktywna"
        ZAKONCZONA = "zakończona", "Zakończona"
        ANULOWANA = "anulowana", "Anulowana"

    project_number = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        validators=[PROJECT_NUMBER_VALIDATOR],
        verbose_name=_("Numer projektu"),
        help_text="Format: 10YYNNNNNNN (11 cyfr: 10 + rok + 7-cyfrowy seq, np. 10260000001). Stare numery BUD-RRRR-NNN dalej akceptowane.",
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

    def __repr__(self) -> str:
        return f"ConstructionSite(project_number={self.project_number!r}, status={self.status!r})"

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True when new reservations may be attached to the site."""
        return self.status == self.Status.AKTYWNA

    @property
    def active_reservation_count(self) -> int:
        """Count of pending / confirmed reservations attached to the site."""
        return self.reservations.filter(
            status__in=(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
        ).count()

    @property
    def has_active_reservations(self) -> bool:
        """True when the site still has open reservations (blocks deletion)."""
        return self.reservations.filter(
            status__in=(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA)
        ).exists()

    def clean(self) -> None:
        """Cross-field validation — ``end_date`` must be ≥ ``start_date``."""
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "Planowana data zakończenia musi być >= data rozpoczęcia."}
            )


# =============================================================================
# RESERVATION
# =============================================================================


class Reservation(TimestampedModel):
    """A reservation of a single :class:`machines.Machine` for a date range.

    A reservation always references a machine; the construction site is
    optional (legacy bookings from M1 may not have one). The ``person`` field
    is a free-text label of the operator/foreman who booked the machine — in
    Milestone 3 it will be replaced by an FK to ``accounts.EmployeeProfile``.

    Status lifecycle:

    * ``oczekująca`` (default) → ``potwierdzona`` via service ``confirm``;
      ``potwierdzona`` is what ``run_daily_sync`` looks at when deciding
      whether to flip a machine to ``Na budowie``.
    * ``potwierdzona`` → ``zakończona`` via service ``complete`` (also
      returns the machine to the warehouse).
    * any non-terminal → ``anulowana`` via service ``cancel``.
    """

    class Status(models.TextChoices):
        """Lifecycle of a reservation. Values are Polish (M1-compatible)."""

        OCZEKUJACA = "oczekująca", "Oczekująca"
        POTWIERDZONA = "potwierdzona", "Potwierdzona"
        ANULOWANA = "anulowana", "Anulowana"
        ZAKONCZONA = "zakończona", "Zakończona"

    class CancellationReason(models.TextChoices):
        """Powód anulowania rezerwacji (B-2) — używane do raportów miesięcznych.

        Wartości DB są ASCII snake_case (compatibility z fixturami), labele PL.
        """

        KLIENT_ZREZYGNOWAL = "klient_zrezygnowal", "Klient zrezygnował"
        AWARIA = "awaria", "Awaria maszyny"
        ZMIANA_TERMINU = "zmiana_terminu", "Zmiana terminu / przesunięcie"
        BRAK_DOSTEPNOSCI = "brak_dostepnosci", "Brak dostępności maszyny"
        INNE = "inne", "Inne (zobacz notatkę)"

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    # FK to machines.Machine — string reference to avoid an import-time
    # circular dependency (machines.services imports reservations lazily too).
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
    # Wave 14-A Bundle 4 -- Sebastian walkthrough 17 maja 2026:
    # `address` jest teraz egzekwowany jako wymagany na poziomie formularza
    # (zob. `ReservationForm.address`). Na modelu zostawiamy `blank=True` +
    # `default=""` zeby istniejace fixtures M1 (legacy bez adresu) nie wymagaly
    # data migration -- enforcement jest podnoszony tylko dla nowych rekordow
    # przez form layer.
    address = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("Adres dostawy")
    )
    # Wave 14-A Bundle 4 -- Sebastian walkthrough: osoba odpowiedzialna na
    # budowie (kierownik/brygadzista). Rozdzielona od `person` (osoba ktora
    # rezerwowala w biurze): `person` = ten kto wpisuje rezerwacje w systemie,
    # `responsible_person` = ten kto odpowiada za maszyne fizycznie na budowie.
    # Wymagane przez form (przy create + update). Default="" zeby istniejace
    # M1 fixtures nie wymagaly data migration.
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

    # B-2: Powód anulowania — wymagany przy status=ANULOWANA, ignored dla innych
    # statusów (walidacja na poziomie service.cancel_reservation()). Pole jest
    # blank=True na poziomie modelu żeby istniejące dane historyczne (M1
    # fixtures) nie musiały być wstecznie wypełniane data migration'em.
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
        help_text=_("Opcjonalna — dodatkowy kontekst (np. przyczyna awarii, kto odwołał)."),
    )

    # B-3: Faktyczna data zwrotu — wcześniejszy zwrot maszyny zwalnia ją
    # dla następnego klienta. Jeśli ustawione, używane w ``has_conflict``
    # zamiast ``end_date`` (planowana data). NULL = brak wcześniejszego zwrotu.
    actual_return_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Faktyczna data zwrotu"),
        help_text=_(
            "Wcześniejszy zwrot — jeśli ustawione, używamy do konfliktów "
            "zamiast planowanej daty końca."
        ),
    )

    # B-6: Wymiana maszyny mid-reservation — jeśli rezerwacja została wymieniona
    # na zastępczą maszynę w trakcie trwania, to pole wskazuje na nową rezerwację
    # pokrywającą pozostały okres. ``on_delete=SET_NULL`` żeby usunięcie nowej
    # rezerwacji (np. anulowanie zastępczej) nie wymazało historycznej.
    # ``related_name="replaces"`` daje odwrotny dostęp: ``new.replaces.first()``
    # zwraca rezerwację która została zastąpiona.
    replaced_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replaces",
        verbose_name=_("Zastąpiona przez"),
        help_text=_(
            "Jeśli rezerwacja została wymieniona mid-flight na inną maszynę — "
            "wskazuje na zastępczą rezerwację."
        ),
    )

    # B-7: Rezerwacja batch (multi-maszynowa) — wszystkie rezerwacje utworzone
    # jednym kliknięciem w formularzu "Grupa rezerwacji" dzielą ten sam UUID,
    # dzięki czemu widok ``batch_detail_view`` może zebrać je w jedną grupę
    # i renderować akcje bulk (potwierdź wszystkie, anuluj wszystkie, zmień
    # operatora na wszystkich). Opcjonalne — single-machine rezerwacje
    # (legacy + indywidualne) zostają z ``batch_id=NULL``. ``db_index=True``
    # bo query "wszystkie z tego batch'a" to hot path detail page.
    batch_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("ID grupy rezerwacji"),
        help_text=_(
            "Jeśli rezerwacja należy do grupy (multi-maszynowa), "
            "wszystkie rezerwacje w grupie mają ten sam UUID."
        ),
    )

    history = HistoricalRecords()

    objects = ReservationManager()

    class Meta:
        verbose_name = _("Rezerwacja")
        verbose_name_plural = _("Rezerwacje")
        ordering = ["-start_date"]
        indexes = [
            # Hot path: "all reservations for machine X newest-first" — used
            # by the machine detail page and the timeline grid (Sprint 7).
            models.Index(fields=["machine", "-start_date"]),
            # Hot path: dashboard widgets ("upcoming pending", "active today").
            models.Index(fields=["status", "start_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.machine.uid} {self.start_date} - {self.end_date} ({self.person})"

    def __repr__(self) -> str:
        return (
            f"Reservation(pk={self.pk!r}, machine_id={self.machine_id!r}, status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Convenience properties / helpers
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True for reservations that should still affect machine status."""
        return self.status in (self.Status.OCZEKUJACA, self.Status.POTWIERDZONA)

    @property
    def is_pending(self) -> bool:
        """True dla rezerwacji oczekujących na potwierdzenie."""
        return self.status == self.Status.OCZEKUJACA

    @property
    def is_confirmed(self) -> bool:
        """True dla rezerwacji potwierdzonych (jeszcze nie zakończonych)."""
        return self.status == self.Status.POTWIERDZONA

    @property
    def is_closed(self) -> bool:
        """True dla rezerwacji zakończonych lub anulowanych — terminal states."""
        return self.status in (self.Status.ZAKONCZONA, self.Status.ANULOWANA)

    @property
    def duration_days(self) -> int:
        """Length of the reservation in days (inclusive)."""
        return (self.end_date - self.start_date).days + 1

    @property
    def title(self) -> str:
        """Short label for the timeline bar / detail header."""
        return f"{self.machine.uid} — {self.person}"

    def clean(self) -> None:
        """Cross-field validation — ``end_date`` must be ≥ ``start_date``."""
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Data końca musi być >= data początku."})
