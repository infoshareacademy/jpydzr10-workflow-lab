from datetime import date

from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel
from core.validators import validate_image_upload

from .managers import MachineManager

INSPECTION_WARNING_DAYS = 14

UID_VALIDATOR = RegexValidator(
    regex=r"^[A-Z0-9_\-]+$",
    message="UID może zawierać tylko duże litery A-Z, cyfry 0-9, podkreślenie i myślnik.",
)


class Machine(TimestampedModel):
    class Status(models.TextChoices):
        W_MAGAZYNIE   = "W magazynie", "W magazynie"
        NA_BUDOWIE    = "Na budowie", "Na budowie"
        ZAREZERWOWANA = "Zarezerwowana", "Zarezerwowana"
        W_SERWISIE    = "W serwisie", "W serwisie"
        WYCOFANA      = "Wycofana", "Wycofana z floty"

    class Type(models.TextChoices):
        KOPARKA              = "koparka", "Koparka"
        MINIKOPARKA          = "minikoparka", "Minikoparka"
        PODNOSNIK_NOZYCOWY   = "podnośnik nożycowy", "Podnośnik nożycowy"
        PODNOSNIK_TELESKOPOWY = "podnośnik teleskopowy", "Podnośnik teleskopowy"
        AGREGAT              = "agregat prądotwórczy", "Agregat prądotwórczy"
        WOZEK_WIDLOWY        = "wózek widłowy", "Wózek widłowy"
        WALEC                = "walec", "Walec"
        ZAGESZCZARKA         = "zagęszczarka", "Zagęszczarka"
        SPAWARKA             = "spawarka", "Spawarka"
        INNE                 = "inne", "Inne"

    uid = models.CharField(
        max_length=20, unique=True, db_index=True,
        validators=[UID_VALIDATOR],
        verbose_name=_("UID maszyny"),
        help_text="Unikalny identyfikator firmowy (np. KOP-001).",
    )
    name = models.CharField(max_length=100, verbose_name=_("Nazwa"))
    machine_type = models.CharField(
        max_length=30, choices=Type.choices, default=Type.INNE,
        db_index=True, verbose_name=_("Typ"),
    )
    model = models.CharField(max_length=100, blank=True, default="", verbose_name=_("Model"))
    capacity = models.PositiveIntegerField(
        default=0, verbose_name=_("Udźwig / wydajność"),
        help_text="Wartość liczbowa (kg dla koparki, l/min dla agregatu).",
    )
    inspection_date = models.DateField(
        null=True, blank=True, db_index=True,
        verbose_name=_("Data ostatniego przeglądu"),
    )
    location = models.CharField(
        max_length=200, default="Magazyn", verbose_name=_("Lokalizacja"),
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.W_MAGAZYNIE, db_index=True,
    )
    manufacturer = models.CharField(max_length=100, blank=True, default="")
    serial_number = models.CharField(max_length=50, blank=True, default="")
    build_year = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(2100)],
        help_text="0 = nieznany.",
    )
    notes = models.TextField(blank=True, default="")
    image = models.ImageField(
        upload_to="machines/", null=True, blank=True,
        validators=[validate_image_upload],
    )

    history = HistoricalRecords()
    objects = MachineManager()

    class Meta:
        verbose_name = _("Maszyna")
        verbose_name_plural = _("Maszyny")
        ordering = ["uid"]

    def __str__(self) -> str:
        return f"{self.uid} — {self.name}"

    @property
    def inspection_status(self) -> str:
        """Bucket: 'unknown' | 'overdue' | 'warning' | 'ok'."""
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
            "ok": "Przegląd aktualny",
            "warning": "Wkrótce przegląd",
            "overdue": "Przegląd przeterminowany",
            "unknown": "Brak daty przeglądu",
        }[self.inspection_status]

    @property
    def inspection_days_left(self) -> int | None:
        """Signed number of days to the next inspection, or ``None``."""
        if not self.inspection_date:
            return None
        return (self.inspection_date - date.today()).days

    @property
    def is_available(self) -> bool:
        return self.status == self.Status.W_MAGAZYNIE
