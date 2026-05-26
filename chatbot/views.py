"""Widoki HTTP dla chatbota.

Dwa endpointy:

* :func:`drawer` — GET, render slide-out panelu w drawer (Alpine x-show)
  z listą ostatnich konwersacji użytkownika.
* :func:`ask` — POST, przyjmuje pytanie z formularza i zwraca odpowiedź
  agenta jako HTMX partial (``_conversation.html``).

Oba endpointy wymagają zalogowania (``@login_required``). Endpoint ``ask``
jest dodatkowo rate-limitowany przez ``django-ratelimit`` (50 zapytań na
użytkownika dziennie — chroni przed spam / nadużyciem API Gemini).
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import ChatMessageForm
from .models import Conversation, Message
from .services import ask_chatbot

logger = logging.getLogger("chatbot")

# Limit konwersacji widocznych w drawer (sidebar) per user.
DRAWER_CONVERSATION_LIMIT = 5

# Limit wiadomości pokazywanych w jednej konwersacji w drawer (window).
DRAWER_MESSAGE_LIMIT = 50


@login_required
def drawer(request: HttpRequest) -> HttpResponse:
    """Render slide-out drawera asystenta (panel boczny w body).

    Zwraca panel z formą pytania + listą max
    :data:`DRAWER_CONVERSATION_LIMIT` ostatnich (niezarchiwizowanych)
    konwersacji użytkownika.
    """
    conversations = Conversation.objects.filter(user=request.user, is_archived=False).order_by(
        "-created_at"
    )[:DRAWER_CONVERSATION_LIMIT]
    form = ChatMessageForm()
    return render(
        request,
        "chatbot/drawer.html",
        {"conversations": conversations, "form": form},
    )


@login_required
@require_POST
@ratelimit(key="user", rate="50/d", method="POST", block=True)
def ask(request: HttpRequest) -> HttpResponse:
    """POST endpoint — przyjmuje pytanie i zwraca odpowiedź jako HTMX partial.

    Rate limit: 50 pytań na użytkownika dziennie (``block=True`` → HTTP 429
    automatycznie z dekoratora). To kompromis pomiędzy wygodą a kosztem
    Gemini API (cena ~$0.005 / 1k tokens dla flash w 2026).
    """
    form = ChatMessageForm(request.POST)
    if not form.is_valid():
        # Zbierz wszystkie błędy do jednego stringa dla template `_message`.
        errors = "; ".join(f"{field}: {', '.join(errs)}" for field, errs in form.errors.items())
        return render(
            request,
            "chatbot/_message.html",
            {
                "message": {
                    "role": Message.Role.ERROR,
                    "role_label": "Błąd",
                    "content": errors or "Niepoprawne pytanie.",
                    "tokens_used": 0,
                }
            },
            status=400,
        )

    conv = None
    conv_id = form.cleaned_data.get("conversation_id")
    if conv_id:
        conv = Conversation.objects.filter(pk=conv_id, user=request.user).first()

    assistant_message = ask_chatbot(
        user=request.user,
        question=form.cleaned_data["question"],
        conversation=conv,
    )

    # Wave 14-C: jeśli agent zaproponował write action, conversation
    # ma teraz pending_action. UI partial pokazuje confirmation card
    # pod ostatnią wiadomością z buttonami "Potwierdź" / "Anuluj".
    # Refresh from DB żeby pobrać świeży pending_action (ask_chatbot
    # zapisuje go w innej transakcji).
    assistant_message.conversation.refresh_from_db()

    # Render obu wiadomości — usera i odpowiedzi — jako jeden partial żeby
    # HTMX prosto wstrzyknął obie do listy konwersacji.
    return render(
        request,
        "chatbot/_conversation.html",
        {
            "messages": [
                {
                    "role": Message.Role.USER,
                    "role_label": "Ty",
                    "content": form.cleaned_data["question"],
                    "tokens_used": 0,
                },
                {
                    "role": assistant_message.role,
                    "role_label": assistant_message.get_role_display(),
                    "content": assistant_message.content,
                    "tokens_used": assistant_message.tokens_used,
                },
            ],
            "conversation": assistant_message.conversation,
            "pending_action": assistant_message.conversation.pending_action,
        },
    )


def ratelimited(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    """Custom view dla ``Ratelimited`` exception — HTTP 429 + polski komunikat.

    Wywoływane przez :class:`chatbot.middleware.RatelimitedMiddleware` gdy
    dekorator ``@ratelimit(..., block=True)`` rzuci ``Ratelimited``.

    Tryby:
      * **HTMX** (``request.htmx``) — zwraca partial ``_message.html`` żeby
        HTMX wstawił komunikat błędu do listy konwersacji (kontekst:
        user kliknął "Wyślij" w drawer, dostaje error bubble jako odpowiedź).
      * **Full page** — zwraca ``ratelimited.html`` z linkiem do home.
    """
    htmx_request = getattr(request, "htmx", False)
    if htmx_request:
        return render(
            request,
            "chatbot/_message.html",
            {
                "message": {
                    "role": Message.Role.ERROR,
                    "role_label": "Błąd",
                    "content": (
                        "Osiągnąłeś dzienny limit 50 zapytań do asystenta. Spróbuj ponownie jutro."
                    ),
                    "tokens_used": 0,
                }
            },
            status=429,
        )
    return render(request, "chatbot/ratelimited.html", status=429)
