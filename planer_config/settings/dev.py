"""
Ustawienia środowiska deweloperskiego.

Wczytywane przez `manage.py` (default) i przez pytest (`pyproject.toml`
ustawia `DJANGO_SETTINGS_MODULE = "planer_config.settings.dev"`).

Wszystko co specyficzne tylko dla developmentu (DEBUG, debug-toolbar,
weaker security, console email backend) trafia tutaj. Importujemy `*` z `base`
i nadpisujemy/dodajemy.
"""

from .base import *  # noqa: F401, F403

# =============================================================================
# DEBUG ON — szczegółowe komunikaty błędów + auto-reload
# =============================================================================

DEBUG = True

# W dev pozwalamy na cały localhost, 127.0.0.1 + dowolny *.localhost
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", ".localhost"]


# =============================================================================
# EMAIL — w dev wszystko leci do konsoli (nie spamuje prawdziwych adresów)
# =============================================================================

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# =============================================================================
# CACHES — local-memory (brak Redis w kursowym M2)
# =============================================================================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "planer-dev-cache",
    }
}


# =============================================================================
# LOGOWANIE — dodajemy DEBUG dla naszych apps, INFO dla Django
# =============================================================================

LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
LOGGING["loggers"].update(  # noqa: F405
    {
        "django": {"level": "INFO", "propagate": False, "handlers": ["console"]},
        "django.db.backends": {"level": "WARNING", "propagate": False, "handlers": ["console"]},
    }
)
