"""Models for the machines app — inventory of construction machinery.

The :class:`Machine` model is ported 1:1 from the Milestone 1 console version
(see ``archive/milestone-1/console/models.py`` in the kursowe repo) into Django:

* string ``VALID_STATUSES`` tuple → :class:`Machine.Status` ``TextChoices``
* string ``inspection_date`` → ``DateField``
* hand-rolled ``check_inspection_status`` staticmethod → property
  :attr:`Machine.inspection_status` that returns ``"ok" | "warning" | "overdue"
  | "unknown"`` (we add ``"unknown"`` for the no-date case — M1 collapsed it
  with overdue, which is unfair in the UI)

The model exposes a custom manager (:class:`machines.managers.MachineManager`)
with helpers used everywhere (``available()``, ``overdue_inspection()``,
``upcoming_inspection()``, ``by_type()``) — see ``managers.py``.

All ``Status.value`` / ``Type.value`` strings are Polish on purpose (Zasada
#2 z dokumentu projektowego): value equals UI label, so we never have to
translate in admin or templates, and historical M1 JSON fixtures import
cleanly.
"""

from datetime import date

from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel
from core.validators import validate_image_upload

from .managers import MachineManager

# Number of days before ``inspection_date`` at which a machine starts showing
# the "warning" badge. Module-level constant — never use the bare ``14`` in
# code (ZASADA #8: no magic numbers).
INSPECTION_WARNING_DAYS = 14

# UID format constraint — wielkie litery A-Z, cyfry 0-9, podkreślenie, myślnik.
# Świadomie ODRZUCAMY kropki (`.`), żeby uniknąć path-traversal-podobnych
# UID-ów typu ``M..0001`` (działają w URL `[\w.\-]+`, ale są niezamierzone).
# Spacje/slashe są już odrzucane przez routing — to dodatkowa warstwa na
# poziomie form validation i ``full_clean()`` w services.create_machine.
UID_VALIDATOR = RegexValidator(
    regex=r"^[A-Z0-9_\-]+$",
    message=_("UID może zawierać tylko duże litery A-Z, cyfry 0-9, podkreślenie i myślnik."),
)


class Machine(TimestampedModel):
    """A single piece of construction machinery owned by the company.

    Lifecycle (status transitions):

    * ``W magazynie`` ⇄ ``Zarezerwowana`` ⇄ ``Na budowie`` (reservation flow)
    * any state → ``W serwisie`` (only when no future confirmed reservation)
    * ``W serwisie`` → ``W magazynie`` (after the service is closed)

    The model tracks an optional ``inspection_date`` (next mandatory periodic
    inspection). :attr:`inspection_status` collapses the date into one of four
    UI buckets (``ok``/``warning``/``overdue``/``unknown``) — the template tag
    :func:`machines.templatetags.machines_tags.inspection_dot` turns those
    into a coloured status dot.
    """

    class Status(models.TextChoices):
        """Operational status of a machine. Values are Polish on purpose."""

        W_MAGAZYNIE = "W magazynie", _("W magazynie")
        NA_BUDOWIE = "Na budowie", _("Na budowie")
        ZAREZERWOWANA = "Zarezerwowana", _("Zarezerwowana")
        W_SERWISIE = "W serwisie", _("W serwisie")
        WYCOFANA = "Wycofana", _("Wycofana z floty")

    class Type(models.TextChoices):
        """Category of machine — drives filters and grouping in the UI."""

        KOPARKA = "koparka", _("Koparka")
        MINIKOPARKA = "minikoparka", _("Minikoparka")
        PODNOSNIK_NOZYCOWY = "podnośnik nożycowy", _("Podnośnik nożycowy")
        PODNOSNIK_TELESKOPOWY = "podnośnik teleskopowy", _("Podnośnik teleskopowy")
        AGREGAT = "agregat prądotwórczy", _("Agregat prądotwórczy")
        WOZEK_WIDLOWY = "wózek widłowy", _("Wózek widłowy")
        WALEC = "walec", _("Walec")
        ZAGESZCZARKA = "zagęszczarka", _("Zagęszczarka")
        SPAWARKA = "spawarka", _("Spawarka")
        INNE = "inne", _("Inne")

    uid = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        validators=[UID_VALIDATOR],
        verbose_name=_("UID maszyny"),
        help_text=_("Unikalny identyfikator firmowy (np. KOP-001)."),
    )
    name = models.CharField(max_length=100, verbose_name=_("Nazwa"))
    machine_type = models.CharField(
        max_length=30,
        choices=Type.choices,
        default=Type.INNE,
        db_index=True,
        verbose_name=_("Typ"),
    )
    model = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Model"))
    capacity = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Udźwig / wydajność"),
        help_text=_("Wartość liczbowa zależna od typu (np. kg dla koparki, l/min dla agregatu)."),
    )
    inspection_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Data ostatniego przeglądu"),
        help_text=_(
            "Pusta wartość = brak danych o przeglądzie (zobacz status w kolumnie 'Przegląd')."
        ),
    )
    location = models.CharField(
        max_length=200,
        default="Magazyn",
        verbose_name=_("Lokalizacja"),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.W_MAGAZYNIE,
        db_index=True,
        verbose_name=_("Status"),
    )
    manufacturer = models.CharField(
        max_length=100, blank=True, default="", verbose_name=_("Producent")
    )
    serial_number = models.CharField(
        max_length=50, blank=True, default="", verbose_name=_("Numer seryjny")
    )
    build_year = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(2100)],
        verbose_name=_("Rok produkcji"),
        help_text=_("0 = nieznany."),
    )
    notes = models.TextField(blank=True, default="", verbose_name=_("Notatki"))
    image = models.ImageField(
        upload_to="machines/",
        null=True,
        blank=True,
        validators=[validate_image_upload],
        verbose_name=_("Zdjęcie"),
    )
    is_reservable = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Dostępna do rezerwacji"),
        help_text=_(
            "Maszyna magazynowa (np. wózek widłowy obsługujący magazyn) zostaje "
            "w bazie i jest widoczna na timeline (śledzimy przegląd), ale nie "
            "można jej rezerwować na budowę."
        ),
    )

    history = HistoricalRecords()

    objects = MachineManager()

    class Meta:
        verbose_name = _("Maszyna")
        verbose_name_plural = _("Maszyny")
        ordering = ["uid"]

    def __str__(self) -> str:
        return f"{self.uid} — {self.name}"

    def __repr__(self) -> str:
        return f"Machine(uid={self.uid!r}, status={self.status!r})"

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    @property
    def inspection_status(self) -> str:
        """One-word bucket for the inspection date.

        * ``"unknown"`` — no ``inspection_date`` set yet
        * ``"overdue"`` — ``inspection_date`` already in the past
        * ``"warning"`` — ``inspection_date`` ≤ :data:`INSPECTION_WARNING_DAYS`
          from today
        * ``"ok"`` — anything further in the future
        """
        if not self.inspection_date:
            return "unknown"
        days_left = (self.inspection_date - date.today()).days
        if days_left < 0:
            return "overdue"
        if days_left <= INSPECTION_WARNING_DAYS:
            return "warning"
        return "ok"

    @property
    def inspection_status_label(self) -> str:
        """Human-readable Polish label matching :attr:`inspection_status`."""
        return {
            "ok": _("Przegląd aktualny"),
            "warning": _("Wkrótce przegląd"),
            "overdue": _("Przegląd przeterminowany"),
            "unknown": _("Brak daty przeglądu"),
        }[self.inspection_status]

    @property
    def inspection_days_left(self) -> int | None:
        """Signed number of days to the next inspection, or ``None``."""
        if not self.inspection_date:
            return None
        return (self.inspection_date - date.today()).days

    @property
    def is_available(self) -> bool:
        """True when the machine is in the warehouse and ready to be reserved."""
        return self.status == self.Status.W_MAGAZYNIE
