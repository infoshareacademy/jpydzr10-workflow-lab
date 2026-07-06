"""Przechwytywanie zmian modeli na czas żądania (warstwa AKCJI dziennika zdarzeń).

``django-simple-history`` zapisuje pełną historię pól każdego śledzonego modelu.
:class:`core.models.AuditLogEntry` działa o poziom wyżej — rejestruje *akcję*
użytkownika (które żądanie mutujące, kto, skąd, na czym). Żeby do wpisu trafił
sensowny ``object_repr`` i diff pól, sygnały ``post_save``/``post_delete`` na
śledzonych modelach odkładają „dotknięte" obiekty do kontekstu otwartego przez
:class:`core.middleware.AuditLogMiddleware` na czas pojedynczego żądania.

Kontekst jest trzymany w ``threading.local`` — każdy wątek serwera obsługuje
jedno żądanie naraz, więc nie ma przeciekania między równoległymi żądaniami.
Poza żądaniem mutującym (komendy zarządcze, testy, GET) kontekst jest nieaktywny
i sygnały nie robią nic (zero narzutu).
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

_state = threading.local()

# Pola pomijane przy liczeniu diffu — zmieniają się przy każdym zapisie (auto_now)
# i tylko zaśmiecałyby ``changes`` bez wartości audytowej.
_DIFF_EXCLUDE = frozenset({"updated_at"})

# Pola-sekrety: logujemy FAKT zmiany (ustawiony ↔ pusty), NIGDY wartość. Hash PIN-u
# głosowego (drugi czynnik uwierzytelnienia) nie ma wartości audytowej jako wartość,
# a trzymanie go w dzienniku (czytelnym dla admina) to zbędna ekspozycja sekretu.
_REDACT_FIELDS = frozenset({"voice_pin_hash"})


def _tracked_models() -> tuple[type, ...]:
    """Modele biznesowe objęte dziennikiem (rozwiązywane leniwie po app-registry)."""
    from accounts.models import EmployeeProfile
    from machines.models import Machine
    from reservations.models import ConstructionSite, Reservation
    from service.models import ServiceRecord

    return (Machine, Reservation, ServiceRecord, ConstructionSite, EmployeeProfile)


def begin() -> None:
    """Otwiera kontekst audytu dla bieżącego żądania."""
    _state.active = True
    _state.touched = []


def end() -> None:
    """Zamyka kontekst audytu i czyści listę dotkniętych obiektów."""
    _state.active = False
    _state.touched = []


def is_active() -> bool:
    return getattr(_state, "active", False)


def touched() -> list[dict[str, Any]]:
    return list(getattr(_state, "touched", []))


def _json_safe(value: Any) -> Any:
    """Sprowadza wartość pola do typu serializowalnego do JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _serialize(instance) -> dict[str, Any]:
    """Pełny, JSON-bezpieczny snapshot pól konkretnych (bez relacji wstecznych).

    Pola z ``_REDACT_FIELDS`` (sekrety) są maskowane do znacznika
    ``<ustawiony>``/``<pusty>`` — dziennik widzi że wartość się zmieniła, nigdy samej wartości.
    """
    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        if field.name in _DIFF_EXCLUDE:
            continue
        if field.name in _REDACT_FIELDS:
            data[field.name] = "<ustawiony>" if getattr(instance, field.attname) else "<pusty>"
        else:
            data[field.name] = _json_safe(getattr(instance, field.attname))
    return data


def _record(instance, *, verb: str, changes: dict[str, Any]) -> None:
    _state.touched.append(
        {
            "object_type": instance._meta.label,
            "object_id": str(instance.pk),
            "object_repr": str(instance)[:200],
            "verb": verb,
            "changes": changes,
        }
    )


@receiver(pre_save)
def _capture_pre_state(sender, instance, **kwargs) -> None:
    """Zapamiętuje stan sprzed zapisu (do diffu) — tylko wewnątrz aktywnego audytu."""
    if not is_active() or sender not in _tracked_models() or instance.pk is None:
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._audit_pre = None
        return
    instance._audit_pre = _serialize(old)


@receiver(post_save)
def _capture_save(sender, instance, created, **kwargs) -> None:
    if not is_active() or sender not in _tracked_models():
        return
    new_state = _serialize(instance)
    if created:
        _record(instance, verb="create", changes=new_state)
        return
    pre = getattr(instance, "_audit_pre", None) or {}
    diff = {
        name: [pre.get(name), value] for name, value in new_state.items() if pre.get(name) != value
    }
    if diff:
        _record(instance, verb="update", changes=diff)


@receiver(post_delete)
def _capture_delete(sender, instance, **kwargs) -> None:
    if not is_active() or sender not in _tracked_models():
        return
    _record(instance, verb="delete", changes=_serialize(instance))
