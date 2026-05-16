"""
Ustawienia środowiska produkcyjnego (Sprint 8 / Milestone 3).

Importowane przez `wsgi.py` i `asgi.py` (DJANGO_SETTINGS_MODULE =
"planer_config.settings.prod" w env vars systemu).

Wszystko co specyficzne tylko dla produkcji (DEBUG=False, security headers,
whitenoise, SMTP email, dłuższe cache) trafia tutaj.

UWAGA: ten plik wymaga env vars produkcyjnych. Brak żadnego z poniższych
spowoduje crash przy starcie — celowo, żeby nie startować z niepełną
konfiguracją.
"""

import os

from .base import *  # noqa: F401, F403

# =============================================================================
# DEBUG OFF + ścisła kontrola hostów
# =============================================================================

DEBUG = False

# ALLOWED_HOSTS musi być wyraźnie ustawiony w env (żadnego wildcard "*")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ValueError("DJANGO_ALLOWED_HOSTS musi być ustawiony w env produkcyjnym")


# =============================================================================
# WHITENOISE — serwowanie static files w prod (zamiast nginx)
# =============================================================================

# Whitenoise musi być DRUGIM middleware (zaraz po SecurityMiddleware)
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405

# Compressed manifest — versioned filenames + gzip/brotli na fly
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# =============================================================================
# SECURITY — produkcyjne nagłówki HTTPS
# =============================================================================

# HSTS (1 rok)
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie security
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Misc
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Reverse proxy header (gdy za nginx/Caddy z X-Forwarded-Proto)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True


# =============================================================================
# EMAIL — SMTP (env vars)
# =============================================================================

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@planer-maszyn.local")


# =============================================================================
# CACHES — w prod używamy database-backed cache (brak Redis w scope kursu)
# =============================================================================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "planer_cache_table",
    }
}


# =============================================================================
# LOGOWANIE — WARNING jako default, INFO dla naszych apps, ERROR dla Django
# =============================================================================

LOGGING["root"]["level"] = "WARNING"  # noqa: F405
LOGGING["loggers"]["django"] = {  # noqa: F405
    "level": "ERROR",
    "propagate": False,
    "handlers": ["console"],
}
