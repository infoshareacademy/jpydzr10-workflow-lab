"""
Ustawienia środowiska testowego (pytest).

Wczytywane przez pytest (pyproject.toml: DJANGO_SETTINGS_MODULE).
Importuje wszystko z `base.py` i nadpisuje tylko to co konieczne dla
szybkich, izolowanych testów (MD5 hasher, locmem cache, InMemoryStorage,
axes off).
"""

import os as _os

from .base import *  # noqa: F403

# =============================================================================
# DEBUG OFF + hosty stałe dla TestClient
# =============================================================================

DEBUG = False
ALLOWED_HOSTS = ["testserver"]

# =============================================================================
# TWILIO — neutralizuj realny token z .env w testach (inaczej suita czerwona)
# =============================================================================
# ``chatbot.voice_views._signature_valid`` włącza walidację podpisu Twilio, gdy
# ``TWILIO_AUTH_TOKEN`` jest ustawiony w settings LUB os.environ. Na maszynie z
# wypełnionym ``.env`` realny token sprawia, że niepodpisane żądania testowe
# webhooka dostają 403 (7 testów voice pada — CI jest zielone tylko dlatego, że
# nie ma tam ``.env``). Usuwamy token ze środowiska procesu testowego → webhook
# idzie ścieżką dev-bypass (200). Test negatywny ustawia ``settings.TWILIO_AUTH_TOKEN``
# lokalnie (override_settings), więc nadal weryfikuje odrzucenie złego podpisu.
_os.environ.pop("TWILIO_AUTH_TOKEN", None)
TWILIO_AUTH_TOKEN = ""
# Bez tokenu webhook głosowy domyślnie wpada w bypass (200) — testy ścieżki
# pozytywnej i fail-closed jawnie nadpisują tę flagę przez ``settings`` fixture.
VOICE_REQUIRE_SIGNATURE = False
# Biały list wyłączony w testach — testy ścieżki gościa zostają; test odrzucenia
# jawnie włącza flagę przez ``settings`` fixture (override_settings).
VOICE_REJECT_UNKNOWN_CALLERS = False

# =============================================================================
# 2FA — obejście wymuszenia w testach (czytane w czasie żądania przez middleware)
# =============================================================================
# Istniejące testy logują się przez ``force_login`` bez przechodzenia 2FA, więc
# domyślnie omijamy wymuszenie. Dedykowane testy 2FA włączają je przez
# ``@override_settings(OTP_TESTING_BYPASS=False)``.
OTP_TESTING_BYPASS = True


# =============================================================================
# PASSWORD HASHER — najszybszy dla testów (czysty MD5, bezpieczny w pamięci)
# =============================================================================

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# =============================================================================
# DJANGO-AXES — wyłączone w testach (testy logowania nie powinny lockoutować)
# =============================================================================

AXES_ENABLED = False


# =============================================================================
# AUTH_PASSWORD_VALIDATORS — usuń HIBP w testach (offline, brak network)
# =============================================================================
# Walidator ``PwnedPasswordsValidator`` w base.py robi network call do HIBP
# API. W testach jednostkowych zabronione (flakiness + slow + offline CI).
# Override base list — filtrujemy wszystko z "Pwned" w nazwie modułu.

AUTH_PASSWORD_VALIDATORS = [
    v
    for v in AUTH_PASSWORD_VALIDATORS  # noqa: F405
    if "Pwned" not in v["NAME"]
]


# =============================================================================
# CACHES — local-memory dla izolacji testów (każdy run swój dict)
# =============================================================================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "planer-test-cache",
    }
}


# =============================================================================
# EMAIL — w pamięci (mail.outbox w testach)
# =============================================================================

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# =============================================================================
# LOGOWANIE — tylko WARNING+, mniej szumu w testach
# =============================================================================

LOGGING["root"]["level"] = "WARNING"  # noqa: F405

# Wave 14-H Bundle M-4: w testach disabling chatbot_audit_file handler
# (no disk writes), propagate=True żeby pytest caplog (na root) widział
# audit logs. Replace rotating file z NullHandler — uniknie finalization
# warning podczas pytest teardown.
LOGGING["handlers"]["chatbot_audit_file"] = {  # noqa: F405
    "class": "logging.NullHandler",
}
LOGGING["loggers"]["chatbot.audit"]["propagate"] = True  # noqa: F405


# =============================================================================
# STORAGES — domyślne file storage w pamięci (nie zapisuje do MEDIA_ROOT)
# =============================================================================

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
