"""Context processory dostępne w każdym template'cie."""

import time

# Limit ostatnich konwersacji pokazywanych w drawerze (sidebar) per user.
# Duplikat z premedytacją wobec chatbot.views.DRAWER_CONVERSATION_LIMIT —
# nie importujemy widoków chatbota, żeby uniknąć ciężkiego eager loadu
# (ratelimit + agent_provider).
_CHATBOT_DRAWER_LIMIT = 5

# Wersja static assets — ustawiona raz przy starcie procesu Django (timestamp).
# Uzywana jako ?v=N query param dla CSS/JS w base.html. Bez tego niektore
# agresywne browser cache (Comet, Brave) trzymaja stary plik mimo F5 — query
# param zmusza ponowne pobranie po kazdym restarcie dev servera (auto po
# manage.py runserver reload).
STATIC_VERSION = str(int(time.time()))


def static_version(request):
    """Wstrzykuje ``STATIC_VERSION`` do kazdego template'a — patrz docstring stalej."""
    return {"STATIC_VERSION": STATIC_VERSION}


def navigation(request):
    """Dostarcza ``current_path`` — aktualną ścieżkę requestu.

    Wykorzystywane przez `active_link` template tag (podkreślenie aktywnej
    pozycji w nawigacji).

    ``is_authenticated`` świadomie pominięte — Django ``auth`` context
    processor (``django.contrib.auth.context_processors.auth``) dostarcza
    ``user`` do każdego template'a, więc warunki w ``base.html`` używają
    ``{% if user.is_authenticated %}``.
    """
    return {"current_path": request.path}


def chatbot_drawer(request):
    """Wstrzykuje ``chatbot_form`` + ``chatbot_conversations`` do każdego template'u.

    Używane przez ``{% include "chatbot/drawer.html" with form=chatbot_form
    conversations=chatbot_conversations only %}`` w ``base.html`` — drawer
    pojawia się na każdej zalogowanej stronie i potrzebuje własnego
    formularza. Osobne nazwy zmiennych (``chatbot_*``) żeby nie kolidować
    z ``form`` używanym przez widoki CRUD (ReservationForm, MachineForm itp.).

    Dla anonimowych użytkowników zwraca pusty słownik — drawer i tak jest
    ukryty w ``base.html`` poprzez ``{% if user.is_authenticated %}``.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    # Lokalne importy żeby uniknąć cyclic import na starcie Django
    # (chatbot zależy od auth + core, więc inverse nie może istnieć
    # na poziomie module-level).
    from chatbot.forms import ChatMessageForm
    from chatbot.models import Conversation

    conversations = list(
        Conversation.objects.filter(user=user, is_archived=False).order_by("-created_at")[
            :_CHATBOT_DRAWER_LIMIT
        ]
    )
    return {
        "chatbot_form": ChatMessageForm(),
        "chatbot_conversations": conversations,
    }
