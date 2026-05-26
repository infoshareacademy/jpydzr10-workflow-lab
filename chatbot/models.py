"""Modele aplikacji chatbot — sesja konwersacji + pojedyncze wiadomości.

Aplikacja jest READ-ONLY z punktu widzenia danych biznesowych (nie tworzy
ani nie zmienia maszyn / rezerwacji / serwisu). Persystuje wyłącznie własną
historię czatu w dwóch modelach:

* :class:`Conversation` — sesja użytkownika (kontener wiadomości). Każda
  konwersacja ma jednego właściciela (``user``) i opcjonalny tytuł
  generowany z pierwszego pytania.
* :class:`Message` — pojedynczy turn w konwersacji (rola + treść +
  zużyte tokeny). Trzymamy też wiadomości z rolą ``error`` żeby user widział
  co poszło nie tak (np. brak API key, błąd Gemini).

Brak ``simple_history`` — chat history sama w sobie jest pełnym audit
trailem (każdy turn = osobny wiersz), nie potrzebujemy snapshotów per row.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimestampedModel


class Conversation(TimestampedModel):
    """Sesja czatu jednego użytkownika — grupuje wiele wiadomości w czasie."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="Użytkownik",
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Tytuł",
        help_text="Krótki podgląd pierwszego pytania (auto-generowany).",
    )
    is_archived = models.BooleanField(
        default=False,
        verbose_name="Zarchiwizowana",
        help_text="Zarchiwizowane konwersacje nie pojawiają się w panelu drawer.",
    )
    # Wave 14-C: multi-turn confirmation flow dla write tools.
    # Gdy agent zwróci JSON z ``confirmation_required: true``, services
    # zapisuje tu ``{"action": "...", "params": {...}, "preview": "..."}``
    # i renderuje preview użytkownikowi. Następna wiadomość user'a
    # ("tak"/"nie") triggeruje :func:`chatbot.tools.execute_confirmed_action`
    # albo czyści pole (NIE wykonuje akcji). NULL = brak akcji oczekującej.
    pending_action = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Oczekująca akcja",
        help_text=(
            "Write tool zaproponowany przez agenta, czekający na potwierdzenie "
            "użytkownika w następnej wiadomości (Wave 14-C confirmation step)."
        ),
    )
    # Wave 14-H Bundle H-3: TTL pending_action (10 minut). Pozwala wygasić
    # stary proposal — zapobiega "zombie approval" gdzie user wraca po
    # godzinach do starej sesji i niechcący potwierdza akcję.
    pending_action_created_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Pending action utworzona o",
        help_text=(
            "Timestamp utworzenia pending_action — używane do TTL (10 minut). "
            "Po wygaśnięciu proposal jest odrzucany przy próbie potwierdzenia."
        ),
    )

    class Meta:
        verbose_name = "Konwersacja"
        verbose_name_plural = "Konwersacje"
        ordering = ["-created_at"]
        indexes = [
            # Hot path: drawer pokazuje 5 ostatnich konwersacji per user.
            models.Index(fields=["user", "is_archived", "-created_at"]),
        ]

    def __str__(self) -> str:
        label = self.title or "(bez tytułu)"
        return f"Konwersacja #{self.pk} ({self.user.get_username()}): {label}"


class Message(TimestampedModel):
    """Pojedyncza wiadomość w konwersacji — pytanie usera lub odpowiedź agenta."""

    class Role(models.TextChoices):
        """Rola autora wiadomości. ``error`` to specjalny status dla błędów agenta."""

        USER = "user", "Użytkownik"
        ASSISTANT = "assistant", "Asystent"
        SYSTEM = "system", "System"
        ERROR = "error", "Błąd"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Konwersacja",
    )
    role = models.CharField(
        max_length=12,
        choices=Role.choices,
        db_index=True,
        verbose_name="Rola",
    )
    content = models.TextField(verbose_name="Treść")
    tokens_used = models.PositiveIntegerField(
        default=0,
        verbose_name="Zużyte tokeny",
        help_text="Liczba tokenów zwrócona przez provider (0 dla wiadomości użytkownika).",
    )

    class Meta:
        verbose_name = "Wiadomość"
        verbose_name_plural = "Wiadomości"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        preview = self.content[:60] + ("…" if len(self.content) > 60 else "")
        return f"[{self.get_role_display()}] {preview}"
