"""Per-page selector mixin dla wszystkich ListView.

Sebastian (2026-05-31): "ustalmy, że każdy nasz jeden widok w Django musi
wczytywać po 100 naraz rekordów. I użytkownik może filtrować między 10, 20,
50, 100, 500 i 5000". Default 100 (poprzednio 20/25), opcje 10/20/50/100/500/5000.
GET param ``per_page`` z whitelist'a respektowany, fallback domyslny.
"""

from __future__ import annotations

DEFAULT_PER_PAGE = 100
PER_PAGE_CHOICES = (10, 20, 50, 100, 500, 5000)


def resolve_per_page(request) -> int:
    """Zwraca per_page z GET param albo default. Whitelist anti-DoS.

    Bez whitelist'a uzytkownik moglby request ?per_page=999999999 zeby
    DoS-owac baze. Zwracamy tylko jedna z zatwierdzonych wartosci, fallback
    do DEFAULT_PER_PAGE.
    """
    raw = (request.GET.get("per_page") or "").strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return n if n in PER_PAGE_CHOICES else DEFAULT_PER_PAGE


class PerPageMixin:
    """Mixin dla ListView — uzywa ?per_page= z GET, default 100.

    Dodaje tez `per_page_choices` + `current_per_page` do context, zeby
    template mogl wyrenderowac selector. Zachowuje wszystkie inne GET
    params w URL'u opcji (page=1 reset bo zmiana per_page zmienia
    indeksowanie).
    """

    paginate_by = DEFAULT_PER_PAGE

    def get_paginate_by(self, queryset):
        return resolve_per_page(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["per_page_choices"] = PER_PAGE_CHOICES
        ctx["current_per_page"] = resolve_per_page(self.request)
        return ctx
