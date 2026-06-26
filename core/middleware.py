"""Middleware dziennika zdarzeń (custom audit log).

Rejestruje każde udane (2xx/3xx) żądanie mutujące — POST/PUT/PATCH/DELETE — do
tabeli :class:`core.models.AuditLogEntry`. Dla akcji, które zmieniają śledzony
model (rezerwacje, maszyny, serwis, budowy, profile), tworzy po jednym wpisie na
dotknięty obiekt wraz z diffem pól (dostarczanym przez sygnały z :mod:`core.audit`).
Dla akcji bez zmiany modelu (logowanie, eksport) tworzy pojedynczy wpis-akcję.

Musi stać PO ``AuthenticationMiddleware`` (potrzebuje ``request.user``) i — żeby
złapać zapisy wykonane przez inne middleware'y opakowujące widok — możliwie
blisko widoku. Zapis audytu nigdy nie może wywrócić żądania użytkownika, więc
jego materializacja jest opakowana w obronne ``try/except`` (świadomy wyjątek od
reguły „bez bare except" — błąd audytu logujemy, ale nie pokazujemy userowi 500).
"""

from __future__ import annotations

import logging

from core import audit

logger = logging.getLogger("core.audit")

_AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Ścieżki nieaudytowane: statyki, healthcheck, panel logowania admina, przełącznik
# języka, narzędzia debug. Dopasowanie prefiksowe (``str.startswith``).
_EXCLUDED_PREFIXES = (
    "/static/",
    "/media/",
    "/healthz",
    "/admin/login",
    "/admin/logout",
    "/i18n/",
    "/jsi18n/",
    "/__debug__/",
)


def _client_ip(request) -> str | None:
    """Pierwszy adres z ``X-Forwarded-For`` (za proxy) lub ``REMOTE_ADDR``."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditLogMiddleware:
    """Otwiera kontekst audytu na czas żądania mutującego i materializuje wpisy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        should_audit = request.method in _AUDITED_METHODS and not self._is_excluded(request.path)
        if not should_audit:
            return self.get_response(request)

        audit.begin()
        try:
            response = self.get_response(request)
        finally:
            try:
                if 200 <= getattr(response, "status_code", 500) < 400:
                    self._write_entries(request, response)
            except Exception:
                logger.exception("Nie udało się zapisać wpisu dziennika zdarzeń")
            finally:
                audit.end()
        return response

    @staticmethod
    def _is_excluded(path: str) -> bool:
        return path.startswith(_EXCLUDED_PREFIXES)

    def _write_entries(self, request, response) -> None:
        from core.models import AuditLogEntry

        match = getattr(request, "resolver_match", None)
        action = match.view_name if match else request.path
        user = request.user if request.user.is_authenticated else None
        ip = _client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]

        touched = audit.touched()
        if not touched:
            # Akcja bez zmiany śledzonego modelu (logowanie, eksport, batch bulk).
            AuditLogEntry.objects.create(
                user=user,
                action=action,
                ip_address=ip,
                user_agent=user_agent,
            )
            return

        entries = [
            AuditLogEntry(
                user=user,
                action=action,
                object_type=item["object_type"],
                object_id=item["object_id"],
                object_repr=item["object_repr"],
                changes=item["changes"],
                ip_address=ip,
                user_agent=user_agent,
            )
            for item in touched
        ]
        AuditLogEntry.objects.bulk_create(entries)
