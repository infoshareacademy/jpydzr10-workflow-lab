from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    """Abstrakcyjny model dodający każdej tabeli pola created_at + updated_at.

    Użycie:
        class Machine(TimestampedModel):
            uid = models.CharField(...)

    Automatycznie wypełniane przez Django:
    - created_at: pierwsza wartość przy save() (auto_now_add).
    - updated_at: aktualizowana przy każdym save() (auto_now).
    """

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Utworzono")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zaktualizowano")

    class Meta:
        abstract = True


class AuditLogEntry(models.Model):
    """Dziennik zdarzeń aplikacji — jeden wpis na akcję mutującą (POST/PUT/PATCH/DELETE).

    Uzupełnia ``django-simple-history`` (które trzyma pełną historię PÓL każdego
    śledzonego modelu) o warstwę AKCJI: kto, kiedy, z jakiego adresu IP wywołał
    daną trasę (``action`` = nazwa widoku, np. ``reservations:confirm``) oraz na
    jakim obiekcie. Łapie też zdarzenia bez zmiany modelu (logowanie, eksport),
    których simple-history z definicji nie widzi.

    Wpisy są tworzone wyłącznie przez :class:`core.middleware.AuditLogMiddleware`
    i są **niemutowalne** z poziomu admina (read-only) — czyszczenie tylko
    komendą ``prune_audit_log``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
        verbose_name=_("Użytkownik"),
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("Czas"))
    action = models.CharField(max_length=100, db_index=True, verbose_name=_("Akcja"))
    object_type = models.CharField(
        max_length=100, db_index=True, blank=True, verbose_name=_("Typ obiektu")
    )
    object_id = models.CharField(
        max_length=100, db_index=True, blank=True, verbose_name=_("ID obiektu")
    )
    object_repr = models.CharField(max_length=200, blank=True, verbose_name=_("Obiekt"))
    changes = models.JSONField(default=dict, blank=True, verbose_name=_("Zmiany"))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("Adres IP"))
    user_agent = models.CharField(max_length=300, blank=True, verbose_name=_("Klient (User-Agent)"))

    class Meta:
        verbose_name = _("Wpis dziennika zdarzeń")
        verbose_name_plural = _("Dziennik zdarzeń")
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "-timestamp"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self) -> str:
        who = self.user.username if self.user else _("anonim")
        return f"{self.timestamp:%Y-%m-%d %H:%M} {who} {self.action}"
