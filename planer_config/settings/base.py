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

import logging
import os
import sys
from pathlib import Path

from csp.constants import NONCE
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
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()
]


# =============================================================================
# APLIKACJE
# =============================================================================

DJANGO_APPS = [
    # django-unfold MUSI być przed django.contrib.admin
    # (nadpisuje template tags + base templates admina)
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "simple_history",  # audit trail per model (HistoricalRecords)
    "django_htmx",  # request.htmx flag + HX-* shortcuts
    "widget_tweaks",  # widget.attrs class injection w template
    "axes",  # brute-force protection na login
    "django_cleanup.apps.CleanupConfig",  # auto-delete orphan FileField uploads
    "djmoney",  # MoneyField (kwota + waluta) dla kosztów serwisowych
    "django_otp",  # 2FA TOTP (Google Authenticator) dla kont uprzywilejowanych
    "django_otp.plugins.otp_totp",  # urządzenia TOTP
    "django_otp.plugins.otp_static",  # kody zapasowe (recovery codes)
]

LOCAL_APPS = [
    "core.apps.CoreConfig",
    "accounts.apps.AccountsConfig",
    "machines.apps.MachinesConfig",
    "reservations.apps.ReservationsConfig",
    "service.apps.ServiceConfig",
    "chatbot.apps.ChatbotConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# =============================================================================
# MIDDLEWARE
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # whitenoise dodawany w prod.py (insert na pozycję 1)
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware — MUSI być po SessionMiddleware (czyta language z sesji),
    # ale przed CommonMiddleware (locale wpływa na URL resolution + redirecty).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",  # request.user.is_verified() (2FA)
    "accounts.middleware.TwoFactorEnforcementMiddleware",  # wymuszenie 2FA dla ról
    "core.middleware.AuditLogMiddleware",  # dziennik zdarzeń (POST/PUT/PATCH/DELETE)
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",  # Content Security Policy
    "core.middleware.AdminCspRelaxMiddleware",  # luzniejszy script-src tylko dla /admin/
    "django_htmx.middleware.HtmxMiddleware",  # request.htmx flag
    "simple_history.middleware.HistoryRequestMiddleware",  # request._history_user
    "chatbot.middleware.RatelimitedMiddleware",  # Ratelimited -> 429 + polski msg
    "axes.middleware.AxesMiddleware",  # MUSI być na końcu listy
]


# =============================================================================
# django-ratelimit — niestandardowy widok dla 429
# =============================================================================
# django-ratelimit w trybie ``block=True`` rzuca ``Ratelimited`` (subklasa
# ``PermissionDenied`` → Django renderuje 403). Middleware
# ``chatbot.middleware.RatelimitedMiddleware`` przechwytuje exception i wywołuje
# widok skonfigurowany niżej — zwraca 429 + polski user-friendly komunikat.
RATELIMIT_VIEW = "chatbot.views.ratelimited"


# =============================================================================
# AUTENTYKACJA + django-axes (brute-force protection)
# =============================================================================

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # MUSI być pierwszy
    "django.contrib.auth.backends.ModelBackend",
]

# Login URL routing (używane przez @login_required + LoginView)
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/"  # po login wracamy do home/dashboard, nie do profilu
LOGOUT_REDIRECT_URL = "home"

# =============================================================================
# 2FA (django-otp) — TOTP wymagane dla kont uprzywilejowanych
# =============================================================================
# Wymuszenie drugiego składnika dla administratorów/kierowników/magazynierów.
# Domyślnie włączone; w środowisku dev można wyłączyć ustawiając OTP_ENFORCE_2FA=0.
OTP_ENFORCE_2FA = os.environ.get("OTP_ENFORCE_2FA", "1") == "1"
# Nazwa wystawcy widoczna w aplikacji authenticator (np. Google Authenticator).
OTP_TOTP_ISSUER = "Planer Maszyn"
# Obejście 2FA dla testów — czytane w czasie żądania przez middleware
# (włączane w settings/test.py oraz przez @override_settings).
OTP_TESTING_BYPASS = False

# django-axes config — wartości konserwatywne (5 prób, 1h lockout)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # 1 godzina lockout po 5 nieudanych próbach
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_VERBOSE = True
# URL strony pokazywanej po zablokowaniu konta — spójny look z resztą UI,
# zamiast domyślnej "białej" strony 403 od axes.
AXES_LOCKOUT_URL = "/accounts/zablokowane/"


# =============================================================================
# django-simple-history — audit trail per model
# =============================================================================
# Każdy model dodaje pole `history = HistoricalRecords()` które tworzy tabelę
# `<app>_historical<model>` z snapshotem przy każdej zmianie.

SIMPLE_HISTORY_REVERT_DISABLED = False  # pozwala na revert w adminie


# =============================================================================
# django-unfold — Tailwind admin theme
# =============================================================================
# Konfiguracja branding + dashboard. Pełna lista opcji:
# https://unfoldadmin.com/docs/configuration/settings/

UNFOLD = {
    "SITE_TITLE": "Planer Maszyn Budowlanych",
    "SITE_HEADER": "Planer Maszyn",
    "SITE_SUBHEADER": "Panel administracyjny",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,  # przycisk historii w detail view
    "SHOW_VIEW_ON_SITE": True,
    "THEME": None,  # None = user wybiera (light/dark/auto)
    "LOGIN": {
        "image": None,  # opcjonalnie logo na ekranie loginu
    },
    # Dashboard callback — wstrzykuje 4 KPI cards na admin landing page.
    "DASHBOARD_CALLBACK": "core.unfold_dashboard.callback",
    "COLORS": {
        # Kolor primary = jasny niebieski (#2563eb) — domyślny Tailwind blue-600.
        # Można zmienić w late W3 polish.
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
            "950": "23 37 84",
        },
    },
}


# =============================================================================
# CONTENT SECURITY POLICY (django-csp 4.x)
# =============================================================================
# Aktualny stan (M3 — strict nonce-based script-src):
#   - 'unsafe-inline' (script) USUNIĘTE: wszystkie inline <script> mają nonce
#     ({{ CSP_NONCE }}), a inline event-handlery (onclick/onchange/onsubmit) zostały
#     przeniesione na delegację zdarzeń w static/js/app.js (data-confirm /
#     data-autosubmit / data-history-back / data-row-href). Panel /admin/ (szablony
#     zewnętrzne django-unfold z inline on*) dostaje 'unsafe-inline' z powrotem przez
#     AdminCspRelaxMiddleware — zaufana powierzchnia is_staff, front-end pozostaje ścisły.
#   - 'unsafe-eval' (script) zostaje TYLKO ze względu na Alpine.js 3.x default
#     build, który używa ``new Function()`` w evaluatorach x-data / x-show /
#     @click. Tailwind Play CDN został wyłączony (poprzednio drugi requestor
#     ``new Function()``); pozostaje jedna zależność. Migracja na Alpine CSP
#     build (``@alpinejs/csp``) wymaga rewrite'u wszystkich inline x-data="{..}"
#     do ``Alpine.data('name', () => ({..}))`` — TODO osobna sesja, sporo
#     templatek.
#   - 'unsafe-inline' (style) zostaje: Tailwind generuje inline ``<style>`` dla
#     dynamicznych klas + nasze custom transitions. Strict CSS-only setup byłby
#     możliwy po przejściu na nonce-based, ale nieproporcjonalne.

# Google Maps widget (BETA, /mapy/) wymaga whitelistowania domen w CSP:
#   - script-src: maps.googleapis.com - loader JS API
#   - img-src: maps.gstatic.com + maps.googleapis.com - tile images + marker icons
#   - connect-src: maps.googleapis.com - XHR dla geocoding / places API
# Bez tych wpisow przegladarka blokuje wszystkie requesty Google Maps + console
# zapelnia sie bledami CSP. Widget jest gated przez `if GOOGLE_MAPS_API_KEY`
# w template - bez klucza skrypt sie nawet nie laduje.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "style-src": ("'self'", "'unsafe-inline'", "https://fonts.googleapis.com"),
        "script-src": (
            "'self'",
            NONCE,  # emituje 'nonce-<...>' — pokrywa inline <script nonce="{{ CSP_NONCE }}">
            "'unsafe-eval'",  # Alpine.js 3.x (new Function w evaluatorach) — patrz nota wyżej
            "https://maps.googleapis.com",
        ),
        "img-src": (
            "'self'",
            "data:",
            "https://maps.gstatic.com",
            "https://maps.googleapis.com",
            "https://*.googleusercontent.com",
        ),
        "font-src": ("'self'", "data:", "https://fonts.gstatic.com"),
        "connect-src": ("'self'", "https://maps.googleapis.com"),
        "frame-ancestors": ("'none'",),
    },
}


# =============================================================================
# GOOGLE MAPS API (widok /mapy/ - BETA)
# =============================================================================
# Klucz API Google Maps JavaScript API. Pobierany z .env (GOOGLE_MAPS_API_KEY).
# Pusta wartosc = widget /mapy/ pokazuje panel "brak klucza" zamiast crashowac
# (gating w templates/core/maps.html). Klucz powinien byc obostrzony przez
# referrer restriction w Google Cloud Console: tylko domena produkcyjna +
# localhost dla dev.
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


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
                "core.context_processors.navigation",
                "core.context_processors.chatbot_drawer",
                "core.context_processors.static_version",
                # ``CSP_NONCE`` w kontekście — używane przez templates dla
                # inline <script nonce="{{ CSP_NONCE }}"> (przygotowanie do
                # nonce-based CSP w M3, gdy usuniemy 'unsafe-inline').
                "csp.context_processors.nonce",
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
# AUTHENTICATION + PASSWORD HASHING (NIST SP 800-63B Rev 4 + HIBP)
# =============================================================================
# Argon2id jest aktualną rekomendacją NIST SP 800-63B Rev 4 dla hashowania
# haseł (memory-hard KDF, odporny na ASIC / GPU farms). Wymaga paczki
# ``argon2-cffi`` zadeklarowanej w runtime dependencies.
#
# Pozostałe hashery (PBKDF2 + BCrypt) zostawiamy w liście, żeby:
#   1. istniejące hasła zapisane jako PBKDF2 (default Django) nadal działały;
#   2. Django zrobił "lazy upgrade" — przy następnym successful login
#      hasło zostanie automatycznie przehashowane na Argon2id i zapisane.

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]


# =============================================================================
# WALIDACJA HASEŁ
# =============================================================================
# Stack: 4 walidatory Django + ``pwned-passwords-django`` (HIBP API).
#
# ``MinimumLengthValidator`` ma ``min_length=10`` (NIST zaleca min 8, my
# bierzemy 10 dla większego marginesu) — zwiększone z domyślnych 8.
#
# ``PwnedPasswordsValidator`` używa modelu k-anonymity (Have I Been Pwned API):
# wysyła tylko prefix 5 znaków SHA-1 hash hasła, nigdy nie wysyła pełnego
# hasła ani pełnego hash. Failuje miękko (timeout / 5xx → pass), więc nie
# blokuje rejestracji gdy HIBP jest niedostępne.
#
# UWAGA: w testach walidator HIBP jest usuwany (zob. ``test.py``) żeby
# uniknąć network calls i flakiness — testy muszą być offline.

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {
        # K-anonymity API check przeciwko bazie HIBP (haveibeenpwned.com).
        # Nigdy nie wysyła plain hasła ani pełnego hash — tylko prefix
        # 5 znaków SHA-1 (model k-anonymity).
        "NAME": "pwned_passwords_django.validators.PwnedPasswordsValidator",
    },
]


# =============================================================================
# INTERNATIONALIZATION — Polski (default) + NL/FR/EN (klient NL/FR mixed)
# =============================================================================
# Polski jest językiem domyślnym (klucze gettext_lazy są pisane po polsku).
# Pozostałe języki są tłumaczone przez .po files w ``locale/<lang>/LC_MESSAGES/``.
# Wybór języka: cookie ``django_language`` (ustawiane przez ``set_language``),
# nagłówek ``Accept-Language`` (fallback) lub session.

LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Wymuszamy europejski format daty (dd.mm.yyyy) w CAŁYM programie — niezależnie
# od aktywnego języka (PL/EN) i adminie. Moduł nadpisuje wbudowane formaty
# locale en/pl (decyzja Sebastiana: data zawsze w formacie europejskim).
FORMAT_MODULE_PATH = ["planer_config.formats"]

# Nazwy języków podajemy w ich WŁASNYM języku (endonimy) i celowo NIE
# tłumaczymy — w przełączniku "Polski"/"English" mają wyglądać tak samo
# niezależnie od aktualnego locale (standard UX selektorów języka).
LANGUAGES = [
    ("pl", "Polski"),
    ("en", "English"),
]

# LOCALE_PATHS — Django szuka tu .po/.mo files dla każdej języka.
LOCALE_PATHS = [BASE_DIR / "locale"]

# =============================================================================
# WALUTY (django-money)
# =============================================================================
# Koszty serwisowe trzymamy jako MoneyField (kwota + waluta). Domyślnie EUR
# (operacje w Belgii); PLN dostępne dla danych historycznych z Milestone 1.
CURRENCIES = ("EUR", "PLN")
CURRENCY_CHOICES = [("EUR", "EUR €"), ("PLN", "PLN zł")]
DEFAULT_CURRENCY = "EUR"


# =============================================================================
# STATIC FILES (CSS, JavaScript, fonty, ikony)
# =============================================================================

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # output collectstatic (prod)
STATICFILES_DIRS = [BASE_DIR / "static"]  # source files (dev + collectstatic)

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

_AUDIT_LOG_DIR = BASE_DIR / "logs"
_AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
        "audit": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        # Wave 14-H Bundle M-4: persist audit trail dla chatbot WRITE operations.
        # Rotating file (10 MB x 5 backupow = 50 MB max), zeby disk sie nie zapelnil.
        # Audit log MUSI być persistowany na disk — console-only nie wystarczy
        # bo container restart traci dowody dla incident response.
        "chatbot_audit_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_AUDIT_LOG_DIR / "chatbot_audit.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "audit",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",  # tylko WARNING+ (bez SQL spam)
            "propagate": False,
        },
        # Wave 14-H Bundle M-4: audit channel pisze do osobnego pliku ORAZ
        # console (propagate=True). Każdy CHATBOT PROPOSE / CONFIRM / CANCEL /
        # EXECUTE / WRITE RATELIMIT idzie tu — niezbędne dla post-incident
        # forensics (kto, kiedy, jaka akcja, na jakim obiekcie).
        "chatbot.audit": {
            "level": "INFO",
            "handlers": ["chatbot_audit_file", "console"],
            "propagate": False,
        },
    },
}


# =============================================================================
# AGENT GŁOSOWY — bezpieczeństwo webhooka Twilio
# =============================================================================
# Czy webhook ``/voice/incoming/`` MUSI mieć poprawny podpis Twilio.
#
# Gdy ``True`` (domyślnie — bezpieczny default) i w środowisku BRAKUJE
# ``TWILIO_AUTH_TOKEN``, webhook jest ODRZUCANY (fail-closed). Bez tej bramki
# brak tokenu oznaczał „pomiń walidację" → każdy mógłby wysłać sfałszowany
# ``From`` i podszyć się pod uprawnionego dzwoniącego. Dev/test jawnie ustawiają
# ``False`` (lokalny rozwój bez tokenu), a profil ``voice`` (publiczny tunel) —
# ``True``.
VOICE_REQUIRE_SIGNATURE = True

# Biały list numerów: połączenia z numerów SPOZA bazy (nieznanych / nieaktywnych /
# zanonimizowanych) są ODRZUCANE (``<Reject>``) w webhooku, ZANIM cokolwiek dotknie
# Gemini — anti-token-drain („nie da się dodzwonić" z nieautoryzowanego numeru).
# Dev/test ustawiają ``False`` (guest-flow lokalnie testowalny); profil ``voice``
# (demo/prod) — ``True``.
VOICE_REJECT_UNKNOWN_CALLERS = True


# =============================================================================
# OBSERVABILITY — GlitchTip (Sentry SDK), opcjonalne i sterowane DSN
# =============================================================================
# Self-hosted GlitchTip (kompatybilny z Sentry SDK). Bez ``SENTRY_DSN`` w
# środowisku inicjalizacja jest pomijana — aplikacja działa normalnie i NIE
# wysyła żadnych zdarzeń (zero kosztu, brak zależności od usługi zewnętrznej).
SENTRY_DSN = os.environ.get("SENTRY_DSN")

# Nie inicjalizujemy SDK pod pytest (nawet gdyby ktoś miał DSN w lokalnym .env).
_RUNNING_TESTS = "pytest" in sys.modules

# Dokładne (case-insensitive) nazwy kluczy do redakcji. Świadomie NIE używamy
# dopasowania po podłańcuchu — `"token" in "session_tokens"` redagowałoby
# legalne pola (`session_tokens`, `api_key_hash`, `user_secret_answer`). Tu
# redagujemy wyłącznie klucze, których nazwa DOKŁADNIE pasuje (po lowercase).
_SENTRY_REDACT_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "secret",
        "csrf",
        "csrftoken",
        "csrfmiddlewaretoken",
        "authorization",
        "api_key",
        "apikey",
        "x-api-key",
        "access_token",
        "refresh_token",
    }
)

# Pola zdarzenia Sentry, w których realnie pojawiają się dane wejściowe
# użytkownika / nagłówki / breadcrumbs. Walk po nich wystarcza, by spełnić
# minimalizację danych z ADR-006 bez przepisywania całego eventu (stacktrace
# vars zostają — to celowe, do diagnostyki; PII i tak wyłączone send_default_pii).
_SENTRY_SCRUB_FIELDS = ("request", "extra", "breadcrumbs", "contexts", "tags", "user")


def _sentry_before_send(event, hint):  # pragma: no cover - wywoływane tylko z aktywnym DSN
    """Wycina wrażliwe wartości z payloadu zanim trafi do GlitchTip.

    Redaguje wartość, gdy DOKŁADNA (lowercase) nazwa klucza znajduje się w
    ``_SENTRY_REDACT_KEYS``. Przechodzi rekurencyjnie po zagnieżdżonych dict/list,
    więc tablice słowników (np. ``breadcrumbs``) też są czyszczone.
    """

    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: ("[redacted]" if str(k).lower() in _SENTRY_REDACT_KEYS else _scrub(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        return obj

    for field in _SENTRY_SCRUB_FIELDS:
        value = event.get(field)
        if isinstance(value, (dict, list)):
            event[field] = _scrub(value)
    return event


if SENTRY_DSN and not _RUNNING_TESTS:  # pragma: no cover - ścieżka z aktywnym DSN
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            LoggingIntegration(event_level=logging.ERROR),
        ],
        send_default_pii=False,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        release=os.environ.get("APP_RELEASE"),
        before_send=_sentry_before_send,
    )
