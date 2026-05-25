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
# CSP override — Alpine.js (django-unfold + base.html Tailwind Play CDN) wymaga 'unsafe-eval'
# =============================================================================
# Alpine.js w panelu admina (django-unfold) i Tailwind JIT runtime używają
# `new Function(...)` dla reactive expressions (x-data="theme()", x-show,
# tailwind.config). Bez 'unsafe-eval' Alpine ciszy się, modal-overlay
# zostaje widoczny -> cała strona admina rozmyta backdrop-blur-xs.
#
# WAŻNE: 'unsafe-eval' jest TYLKO w dev. prod.py ma własną politykę
# (zero unsafe-* — admin tam działa z prekompilowanym Alpine CSP build
# lub static Tailwind CSS bez JIT).

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        **CONTENT_SECURITY_POLICY["DIRECTIVES"],  # noqa: F405
        "script-src": ("'self'", "'unsafe-inline'", "'unsafe-eval'"),
    }
}


# =============================================================================
# django-debug-toolbar — SQL profiling, request inspection, settings dump
# =============================================================================
# Pokazuje się jako pasek po prawej stronie w przeglądarce gdy DEBUG=True
# i request idzie z INTERNAL_IPS.

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

# Middleware MUSI być wstawione PRZED HtmxMiddleware (żeby toolbar
# nie był renderowany w HTMX partial responses) — znajdujemy index ręcznie.
_htmx_idx = MIDDLEWARE.index("django_htmx.middleware.HtmxMiddleware")  # noqa: F405
MIDDLEWARE.insert(_htmx_idx, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405

INTERNAL_IPS = ["127.0.0.1", "localhost"]

DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": {"debug_toolbar.panels.redirects.RedirectsPanel"},
    "SHOW_TEMPLATE_CONTEXT": True,
}


# =============================================================================
# django-axes — wyłączone w dev (uniknięcie lockoutu podczas testowania)
# =============================================================================

AXES_ENABLED = False


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
