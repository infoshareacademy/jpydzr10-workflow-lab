"""
URL routing dla projektu planer_config.

Konwencja: każda app ma własny `urls.py`, włączany tu przez `include()`.
Ten plik jest celowo cienki — tylko top-level routing + healthz +
warunkowe URL'e debug-toolbar w trybie DEBUG.
"""

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import include, path


def home(request):
    """Welcome page — pokazuje status projektu + skróty do admina / healthz.

    Zostanie zastąpione w Sprint 5 dashboardem z timeline rezerwacji
    (KPI cards + overdue alerts + filterable timeline grid).
    """
    return render(request, "home.html")


def healthz(request):
    """Endpoint dla monitoringu (load balancer / uptime check).

    Zwraca HTTP 200 + plain text 'ok'. NIE używa DB (więc działa nawet
    gdy Postgres jest down — używamy do liveness probe).
    """
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", home, name="home"),
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
]


# =============================================================================
# django-debug-toolbar — URL'e tylko w trybie DEBUG
# =============================================================================
# Toolbar middleware (dodane w dev.py) renderuje pasek z linkami do
# `djdt:render_panel` / `djdt:history_sidebar`. Te nazwy musimy wpiąć
# w urlpatterns, inaczej template `debug_toolbar/base.html` rzuca
# NoReverseMatch przy każdym requeście.
if settings.DEBUG:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]
