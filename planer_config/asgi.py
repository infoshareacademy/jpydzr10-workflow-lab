"""
ASGI config for planer_config project.

Eksponuje ASGI callable jako module-level zmienną `application`.

ASGI obsługuje też surowe gniazdo WebSocket agenta głosowego pod
``/ws/voice/`` (Twilio ConversationRelay ↔ Gemini Live). NIE używamy Channels —
uvicorn obsługuje scope ``websocket`` natywnie, a my ręcznie kierujemy ścieżkę do
:func:`chatbot.voice_consumer.run_voice_socket`. Pozostałe scope (``http``,
``lifespan``) idą do standardowej aplikacji Django.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planer_config.settings.prod")

_django_app = get_asgi_application()

# Ścieżka gniazda głosowego — musi zgadzać się z URL-em w TwiML
# (``wss://{tunnel}/ws/voice/`` budowanym w ``chatbot.voice_views``).
VOICE_WS_PATH = "/ws/voice/"


async def application(scope, receive, send):
    """Router ASGI: WebSocket ``/ws/voice/`` → agent głosowy, reszta → Django."""
    if scope["type"] == "websocket" and scope.get("path") == VOICE_WS_PATH:
        # Lazy import — apps muszą być załadowane (po get_asgi_application powyżej).
        from chatbot.voice_consumer import run_voice_socket

        await run_voice_socket(scope, receive, send)
        return
    await _django_app(scope, receive, send)
