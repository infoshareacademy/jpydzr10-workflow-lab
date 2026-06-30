"""Rezygnacja (opt-out) z nieobowiązkowych maili + podpisane linki „wypisz się".

Maile transakcyjne (potwierdzenie/anulowanie rezerwacji, nowy wniosek, reset
hasła) są OBOWIĄZKOWE i nie podlegają rezygnacji. Z kategorii nieobowiązkowych
(przypomnienia, alerty przeglądowe) pracownik może się wypisać przez link w
stopce maila — link zawiera podpisany (HMAC, ``django.core.signing``) token
identyfikujący użytkownika i kategorię, więc nie wymaga logowania i nie da się
go podrobić ani użyć dla innego konta.
"""

from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class EmailCategory:
    """Klucze kategorii nieobowiązkowych maili (zapisywane w ``email_opt_outs``)."""

    REMINDERS = "reminders"
    INSPECTIONS = "inspections"


# Etykiety prezentowane na stronie zarządzania preferencjami.
CATEGORY_LABELS = {
    EmailCategory.REMINDERS: _("Przypomnienia o rezerwacjach"),
    EmailCategory.INSPECTIONS: _("Alerty o przeglądach maszyn"),
}

# Sól podpisu — oddziela tokeny rezygnacji od innych zastosowań signing.
_SALT = "accounts.email-optout"


def make_unsubscribe_token(user_pk: int, category: str) -> str:
    """Zwróć podpisany token (HMAC) kodujący użytkownika i kategorię."""
    return signing.dumps({"uid": user_pk, "cat": category}, salt=_SALT)


def parse_unsubscribe_token(token: str) -> tuple[int, str] | None:
    """Zweryfikuj i rozkoduj token. Zwraca ``(user_pk, category)`` albo ``None``.

    Linki rezygnacji celowo nie wygasają (``max_age`` pominięty) — wypisanie ma
    działać także po dłuższym czasie od wysłania maila.
    """
    try:
        data = signing.loads(token, salt=_SALT)
    except signing.BadSignature:
        return None
    uid, cat = data.get("uid"), data.get("cat")
    if not isinstance(uid, int) or cat not in CATEGORY_LABELS:
        return None
    return uid, cat


def is_opted_out(user, category: str) -> bool:
    """Czy użytkownik wypisał się z danej kategorii maili."""
    profile = getattr(user, "profile", None)
    return bool(profile and category in (profile.email_opt_outs or []))


def unsubscribe_url_for(user, category: str) -> str:
    """Pełny (absolutny) URL „wypisz się" z tokenem dla danego użytkownika+kategorii."""
    base = getattr(settings, "EMAIL_LINK_BASE_URL", "http://localhost:8002").rstrip("/")
    path = reverse("accounts:email_preferences")
    token = make_unsubscribe_token(user.pk, category)
    return f"{base}{path}?token={token}"


def preferences_url() -> str:
    """Absolutny URL strony preferencji bez tokenu (dla maili wieloadresatowych)."""
    base = getattr(settings, "EMAIL_LINK_BASE_URL", "http://localhost:8002").rstrip("/")
    return f"{base}{reverse('accounts:email_preferences')}"
