"""Modele aplikacji accounts (EmployeeProfile rozszerzający Django User)."""

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.models import TimestampedModel
from core.validators import normalize_phone_e164, phone_e164_validator

User = get_user_model()


class EmployeeProfile(TimestampedModel):
    """Profil pracownika — rozszerza Django User o dane specyficzne dla firmy.

    Tworzony automatycznie przez sygnał post_save na User (patrz signals.py).
    Każdy User ma dokładnie jeden profil (OneToOne).
    """

    class Function(models.TextChoices):
        """Funkcja pracownika w firmie."""

        MAGAZYNIER = "magazynier", "Magazynier"
        MONTAZYSTA = "montażysta", "Montażysta"
        KIEROWNIK = "kierownik", "Kierownik"
        ADMIN = "admin", "Administrator"

    class Theme(models.TextChoices):
        """Preferencja motywu UI (light/dark/auto)."""

        AUTO = "auto", "Automatyczny"
        LIGHT = "light", "Jasny"
        DARK = "dark", "Ciemny"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("Użytkownik"),
    )
    function = models.CharField(
        max_length=20,
        choices=Function.choices,
        default=Function.MONTAZYSTA,
        verbose_name=_("Funkcja"),
    )
    phone = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        unique=True,
        validators=[phone_e164_validator],
        verbose_name=_("Telefon"),
    )
    employee_id = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Identyfikator pracownika"),
    )
    theme_preference = models.CharField(
        max_length=10,
        choices=Theme.choices,
        default=Theme.AUTO,
        verbose_name=_("Motyw interfejsu"),
    )
    is_active_employee = models.BooleanField(
        default=True,
        verbose_name=_("Aktywny pracownik"),
    )
    is_anonymized = models.BooleanField(
        default=False,
        verbose_name=_("Zanonimizowany"),
        help_text="Czy profil został zanonimizowany (GDPR Art.17).",
    )
    anonymized_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Data anonimizacji"),
        help_text="Data anonimizacji (UTC).",
    )
    termination_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Data zakończenia zatrudnienia"),
        help_text="Data rozwiązania umowy/zakończenia zatrudnienia.",
    )
    termination_reason = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Powód zakończenia"),
        help_text="Powód zakończenia (opcjonalnie).",
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Profil pracownika")
        verbose_name_plural = _("Profile pracowników")

    def save(self, *args, **kwargs):
        # Numer telefonu jest UNIQUE — pusty numer musi być przechowywany jako
        # NULL (dwa profile z ``""`` złamałyby unikalność). Dodatkowo oczyszczamy
        # separatory ("+48 600…" → "+48600…"), aby każda ścieżka zapisu
        # (formularz, admin, serwis, sygnał) trzymała ścisłe E.164.
        self.phone = normalize_phone_e164(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        full_name = self.user.get_full_name() or self.user.username
        return f"{full_name} ({self.get_function_display()})"
