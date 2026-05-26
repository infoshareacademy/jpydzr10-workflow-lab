"""Routing URL dla aplikacji chatbot.

Włączone w :mod:`planer_config.urls` pod prefiksem ``/asystent/`` (np.
``/asystent/drawer/`` → :func:`chatbot.views.drawer`).
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
    path("drawer/", views.drawer, name="drawer"),
    path("zapytaj/", views.ask, name="ask"),
]
