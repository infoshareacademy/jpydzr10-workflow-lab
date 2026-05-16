"""
URL routing dla projektu planer_config.

Konwencja: każda app ma własny `urls.py`, włączany tu przez `include()`.
Ten plik jest celowo cienki — tylko top-level routing + healthz.
"""

from django.contrib import admin
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path


def home(request):
    """Tymczasowy widok strony głównej — redirect do admina.

    Zostanie zastąpiony w Sprint 5 dashboardem z timeline rezerwacji.
    """
    return HttpResponseRedirect("/admin/")


def healthz(request):
    """Endpoint do monitoringu (load balancer / uptime check).

    Zwraca HTTP 200 + plain text 'ok'. Można rozszerzyć o probe DB / cache
    w późniejszych etapach (Sprint 8 / Milestone 3).
    """
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", home, name="home"),
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
]
