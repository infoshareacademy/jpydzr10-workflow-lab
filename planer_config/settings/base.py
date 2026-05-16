"""
Wspólne ustawienia Django dla Planera Maszyn Budowlanych (Milestone 2).

Ten plik zawiera ustawienia wspólne dla środowiska deweloperskiego
i produkcyjnego. Środowisko-specyficzne wartości (DEBUG, DATABASES, hosts,
toolbar, security headers) są w `dev.py` i `prod.py`, które importują z `*`
z tego pliku i nadpisują/dodają.

Konwencja:
- Wartości wczytywane z .env (przez python-dotenv) — nigdy hardcoded
  w repo (zasada: zero sekretów w gicie).
- Brak SECRET_KEY w tym pliku — każde środowisko musi go mieć w .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# =============================================================================
# ŚCIEŻKI I WCZYTANIE .env
# =============================================================================

# BASE_DIR = root projektu (folder w którym leży manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Wczytaj .env z root projektu (jeśli istnieje — w prod może go nie być,
# bo wartości są w env vars systemu)
load_dotenv(BASE_DIR / ".env")


# =============================================================================
# KONFIGURACJA RDZENIA DJANGO
# =============================================================================

# SECRET_KEY: zawsze z .env. Brak fallbacku — celowo, żeby zapomnienie
# .env w nowym środowisku failowało głośno.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# DEBUG: nadpisywany w dev.py / prod.py. Domyślnie False (bezpieczny default).
DEBUG = False

# ALLOWED_HOSTS: lista oddzielona przecinkami w .env, np. "localhost,127.0.0.1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]


# =============================================================================
# APLIKACJE
# =============================================================================

DJANGO_APPS = [
    # django-unfold MUSI być przed django.contrib.admin
    # (nadpisuje template tags admina)
    # "unfold",                              # dodamy w następnym commicie
    # "unfold.contrib.filters",
    # "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    # Dodawane stopniowo w kolejnych commitach:
    # "simple_history",      # audit trail per model
    # "axes",                # brute-force protection
    # "django_htmx",         # request.htmx + utilities
    # "widget_tweaks",       # widget.attrs class injection
    # "django_cleanup.apps.CleanupConfig",   # auto-delete orphan FileFields
]

LOCAL_APPS = [
    # Dodajemy w Sprint 2+: machines, reservations, service, accounts, core
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# =============================================================================
# MIDDLEWARE
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # whitenoise serwuje static w prod (dev używa runserver)
    # "whitenoise.middleware.WhiteNoiseMiddleware",  # tylko prod
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Dodawane w kolejnych commitach:
    # "django_htmx.middleware.HtmxMiddleware",
    # "axes.middleware.AxesMiddleware",      # po AuthenticationMiddleware
    # "simple_history.middleware.HistoryRequestMiddleware",
]


# =============================================================================
# URL + WSGI/ASGI
# =============================================================================

ROOT_URLCONF = "planer_config.urls"
WSGI_APPLICATION = "planer_config.wsgi.application"
ASGI_APPLICATION = "planer_config.asgi.application"


# =============================================================================
# TEMPLATES
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# =============================================================================
# BAZA DANYCH — PostgreSQL 16 przez Docker (OrbStack)
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "planer_kursowy"),
        "USER": os.environ.get("POSTGRES_USER", "planer"),
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 600,
    }
}


# =============================================================================
# WALIDACJA HASEŁ
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# =============================================================================
# INTERNATIONALIZATION — całość po polsku, strefa Warsaw
# =============================================================================

LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC FILES (CSS, JavaScript, fonty, ikony)
# =============================================================================

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # output collectstatic (prod)
STATICFILES_DIRS = [BASE_DIR / "static"]        # source files (dev + collectstatic)

# Wszystkie biblioteki frontendowe są vendorowane w `static/vendor/`
# (HTMX, Alpine.js, Tailwind, Flatpickr, fonty Inter/JetBrains Mono).
# Zero CDN — apka działa offline na intranecie firmy.


# =============================================================================
# MEDIA FILES (uploadowane przez użytkowników: zdjęcia maszyn, PDF protokoły)
# =============================================================================

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# =============================================================================
# DEFAULT PRIMARY KEY
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# LOGOWANIE — proste console output, rozszerzymy w prod.py
# =============================================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",                 # tylko WARNING+ (bez SQL spam)
            "propagate": False,
        },
    },
}
