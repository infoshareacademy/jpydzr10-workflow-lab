"""Middleware aplikacji chatbot — przechwytywanie ``Ratelimited`` exception.

``django-ratelimit`` w trybie ``block=True`` rzuca ``Ratelimited``
(podklasa ``PermissionDenied``) — domyślnie Django renderuje to jako
HTTP 403, co dla rate-limit jest nieprawidłowe (powinno być 429).

:class:`RatelimitedMiddleware` przechwytuje ``Ratelimited`` i deleguje
do widoku skonfigurowanego w ``settings.RATELIMIT_VIEW`` (jak Django robi
to dla 404 / 500 / 403 — patrz ``django.urls.resolvers``).

Middleware jest celowo cienki — cała logika renderingu jest w widoku
``chatbot.views.ratelimited`` (HTMX-aware: zwraca partial dla HTMX,
full page dla zwykłych requestów).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.module_loading import import_string
from django_ratelimit.exceptions import Ratelimited

logger = logging.getLogger("chatbot")


class RatelimitedMiddleware:
    """Łapie ``Ratelimited`` z dekoratora ``@ratelimit`` i renderuje 429.

    Aktywuje się tylko jeśli ``settings.RATELIMIT_VIEW`` jest skonfigurowane —
    inaczej propaguje wyjątek dalej (Django zrobi domyślne 403).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        """Renderuje 429 jeśli exception to ``Ratelimited`` i ``RATELIMIT_VIEW`` istnieje."""
        if not isinstance(exception, Ratelimited):
            return None

        view_path = getattr(settings, "RATELIMIT_VIEW", None)
        if not view_path:
            # Brak konfiguracji — propagacja do default handlera (403).
            return None

        try:
            view = import_string(view_path)
        except ImportError:
            logger.error(
                "RATELIMIT_VIEW=%r nie da się zaimportować — fallback do 403.",
                view_path,
            )
            return None

        logger.info(
            "Ratelimit hit dla user_id=%s path=%s",
            getattr(getattr(request, "user", None), "pk", None),
            request.path,
        )
        return view(request, exception)
