"""URL routing dla projektu planer_config.

Konwencja: każda app ma własny `urls.py`, włączany tu przez `include()`.
Ten plik jest celowo cienki — tylko top-level routing + home + includy.

Wave 4 P0: home view został przeniesiony do ``core.views.home`` żeby
dodać ``@login_required`` (GDPR — wyciek PII przez listę rezerwacji
``person`` w dashboardzie anonymous).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from core.email_preview import email_preview
from core.views import home, maps_view

urlpatterns = [
    path("", home, name="home"),
    # Przeglądarki żądają /favicon.ico z roota mimo <link rel="icon"> na SVG —
    # bez tego jedyny 404 w konsoli na każdej stronie. Przekierowujemy na SVG.
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.svg", permanent=True)),
    # Deweloperski podglad maili — PRZED include admina, zeby nie zostal
    # polkniety przez admin.site.urls. Aktywny tylko w DEBUG + dla staff.
    path("admin/preview-email/", email_preview, name="email_preview"),
    path("admin/", admin.site.urls),
    # /mapy/ - Google Maps widget (BETA) - pin per maszyna. Sebastian #60.
    # Widok wymaga GOOGLE_MAPS_API_KEY w .env zeby aktywowac mape; bez
    # klucza pokazuje panel informacyjny.
    path("mapy/", maps_view, name="maps"),
    # i18n set_language endpoint — POST language=<code>&next=<path>; ustawia
    # ``django_language`` cookie + session, robi redirect na ``next``. Działa
    # globalnie (BEZ ``i18n_patterns``) — language jest per-user, nie per-URL.
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("accounts.urls")),
    path("maszyny/", include("machines.urls")),
    path("rezerwacje/", include("reservations.urls")),
    path("serwis/", include("service.urls")),
    path("asystent/", include("chatbot.urls")),
    # Webhook agenta głosowego (Twilio → TwiML ConversationRelay).
    path("voice/", include("chatbot.voice_routing")),
    path("", include("core.urls")),  # healthz
]

if settings.DEBUG:  # pragma: no cover — dev-only branch, test settings have DEBUG=False
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # debug_toolbar można wyłączyć przez DJDT_DISABLED=1 (audyty a11y/CSP) — wtedy
    # app nie jest zainstalowany, więc include'ujemy jego URL-e tylko gdy obecny.
    if "debug_toolbar" in settings.INSTALLED_APPS:
        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

# Custom error handlers — jawnie wskazane (mimo że to wartości domyślne Django),
# żeby udokumentować, że projekt świadomie korzysta z własnych szablonów
# ``templates/403.html`` / ``404.html`` / ``500.html`` (renderowanych przy
# ``DEBUG=False``). ``templates/maintenance.html`` to osobna strona przerwy
# technicznej (HTTP 503) serwowana przez warstwę wdrożeniową/proxy.
handler403 = "django.views.defaults.permission_denied"
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"
