"""URL routing aplikacji core (healthz endpoint + global search).

Wave 14-D: ``szukaj/`` → ``core:search`` aktywuje topbar input
(dotąd disabled z M1 placeholderem). Włączane do top-level routing
przez ``path("", include("core.urls"))`` w ``planer_config/urls.py``,
więc URL końcowy to ``/szukaj/``.
"""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    # Polityka prywatności (RODO/GDPR) — publiczna, dwujęzyczna.
    path("prywatnosc/", views.privacy_policy, name="privacy"),
    # Wave 14-D — global search (HTMX typeahead + full page fallback).
    path("szukaj/", views.global_search_view, name="search"),
    # Wyzwalacz testowy obserwowalności (tylko superuser) — patrz docs/adr/006.
    path("debug/boom/", views.debug_boom, name="debug_boom"),
]
