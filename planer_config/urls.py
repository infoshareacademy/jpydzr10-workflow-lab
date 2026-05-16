"""
URL routing dla projektu planer_config.

Konwencja: każda app ma własny `urls.py`, włączany tu przez `include()`.
Ten plik jest celowo cienki — tylko top-level routing + healthz.
"""

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path


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
