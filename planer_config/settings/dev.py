"""
Ustawienia środowiska deweloperskiego.

Wczytywane przez `manage.py` (default) i przez pytest (`pyproject.toml`
ustawia `DJANGO_SETTINGS_MODULE = "planer_config.settings.dev"`).

Wszystko co specyficzne tylko dla developmentu (DEBUG, debug-toolbar,
weaker security, console email backend) trafia tutaj. Importujemy `*` z `base`
i nadpisujemy/dodajemy.
"""

import os

from .base import *  # noqa: F403

# =============================================================================
# DEBUG ON — szczegółowe komunikaty błędów + auto-reload
# =============================================================================

DEBUG = True

# W dev pozwalamy na cały localhost, 127.0.0.1 + dowolny *.localhost
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", ".localhost"]


# =============================================================================
# django-debug-toolbar — SQL profiling, request inspection, settings dump
# =============================================================================
# Pokazuje się jako pasek po prawej stronie w przeglądarce gdy DEBUG=True
# i request idzie z INTERNAL_IPS.
#
# Można wyłączyć przez ``DJDT_DISABLED=1`` w środowisku — przydatne do audytów,
# które toolbar zaburza: kontrast a11y (przycisk toolbara to jedyny dev-only fail
# Lighthouse) oraz CSP (toolbar dorzuca własne skrypty). Wtedy ``make run`` daje
# czysty obraz aplikacji bez przełączania na DEBUG=False.

if os.environ.get("DJDT_DISABLED") != "1":
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

    # Middleware MUSI być wstawione PRZED HtmxMiddleware (żeby toolbar
    # nie był renderowany w HTMX partial responses) — znajdujemy index ręcznie.
    _htmx_idx = MIDDLEWARE.index("django_htmx.middleware.HtmxMiddleware")  # noqa: F405
    MIDDLEWARE.insert(_htmx_idx, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405

    INTERNAL_IPS = ["127.0.0.1", "localhost"]

DEBUG_TOOLBAR_CONFIG = {
    # ProfilingPanel wyłączony: cProfile koliduje przy współbieżnych requestach
    # (HTMX + główny request) → "Another profiling tool is already active" = 500.
    # Dev-only artefakt toolbara, nie kod aplikacji; wyłączamy dla stabilności demo.
    "DISABLE_PANELS": {
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
    },
    "SHOW_TEMPLATE_CONTEXT": True,
}


# =============================================================================
# django-axes — wyłączone w dev (uniknięcie lockoutu podczas testowania)
# =============================================================================

AXES_ENABLED = False


# =============================================================================
# EMAIL — sterowane środowiskiem
# =============================================================================
# Gdy w `.env` ustawiono EMAIL_HOST → realna wysyłka SMTP (np. Gmail do pokazu
# albo Mailpit pod localhost:1025). W przeciwnym razie maile lecą do konsoli.
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
    # Fallback: gdy ani DEFAULT_FROM_EMAIL ani EMAIL_HOST_USER nie są ustawione
    # (np. Mailpit bez auth), nie wolno zostawić pustego stringa — pusty
    # from_email wysadza EmailMultiAlternatives.send() (ValueError / SMTP odrzuca
    # nadawcę), a wyjątek ginie cicho w on_commit. Gwarantujemy poprawny adres.
    DEFAULT_FROM_EMAIL = os.environ.get(
        "DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@localhost"
    )
else:
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
