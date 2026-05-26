"""Wspólne helpery do mapowania ``ValidationError`` warstwy serwisów.

Funkcje serwisowe (``machines.services``, ``reservations.services``,
``service.services``) podnoszą ``django.core.exceptions.ValidationError``,
która może mieć trzy kształty:

* ``error_dict`` — błędy per pole (``form.add_error("field", "...")``),
* ``error_list`` — lista non-field errors,
* gołe ``ValidationError("...")`` — pojedynczy komunikat.

Każdy widok robił to samo: jeden helper przepisujący na ``form.add_error``,
drugi spłaszczający dla toast/messages. Konsolidujemy je tutaj.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError


def add_form_errors(form, exc: ValidationError) -> None:
    """Przepisuje ``ValidationError`` z warstwy serwisów na ``form.add_error``.

    Jeśli ``exc.message_dict`` ma klucz odpowiadający polu formularza —
    błąd ląduje przy tym polu; w przeciwnym wypadku trafia do
    ``__all__`` (non-field error).
    """
    if hasattr(exc, "message_dict"):
        for field, messages in exc.message_dict.items():
            target = field if field in form.fields else "__all__"
            for message in messages:
                form.add_error(target, message)
    else:
        for message in exc.messages:
            form.add_error("__all__", message)


def join_validation_error(exc: ValidationError) -> str:
    """Spłaszcza ``ValidationError`` do jednego stringa (np. dla toast/messages).

    Dict-shape błędy są poprzedzone nazwą pola (``field: message``);
    non-field errors zostają bez prefixu.
    """
    if hasattr(exc, "message_dict"):
        # PERF401: list-comprehension zamiast nested append'ów — Ruff zgłaszał
        # ``list.extend`` hint, ale dla nested loop ``[expr for ... for ...]``
        # jest bardziej idiomatyczne (jeden expression, czytelny generator chain).
        parts = [
            (message if field == "__all__" else f"{field}: {message}")
            for field, messages in exc.message_dict.items()
            for message in messages
        ]
        return "; ".join(parts)
    return "; ".join(exc.messages)
