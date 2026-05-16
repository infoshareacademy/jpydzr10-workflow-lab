"""
ASGI config for planer_config project.

Eksponuje ASGI callable jako module-level zmienną `application`.

ASGI jest potrzebne dla async views, WebSocket (Channels), Server-Sent Events
i SSE streaming z chatbotem (W4 bonus).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planer_config.settings.prod")

application = get_asgi_application()
