"""Routing HTTP agenta głosowego (webhook połączenia przychodzącego Twilio).

Montowany w ``planer_config/urls.py`` pod ``/voice/``, więc końcowy URL webhooka
to ``/voice/incoming/`` (taki sam wpisuje się w konsoli Twilio).
"""

from __future__ import annotations

from django.urls import path

from . import voice_views

app_name = "voice"

urlpatterns = [
    path("incoming/", voice_views.voice_incoming, name="incoming"),
    path("verify-pin/", voice_views.voice_verify_pin, name="verify_pin"),
]
