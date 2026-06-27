"""Wspólne klasy bazowe dla django-admin (unfold theme + simple_history).

Ustandaryzowanie MRO: ``ModelAdmin`` (unfold) MUSI być pierwszy zgodnie z
oficjalną dokumentacją django-unfold — w przeciwnym razie unfoldowy theme
nie nakłada się na widoki nadpisywane przez ``SimpleHistoryAdmin`` (history
list, history detail). Dzięki temu jeden ``PlanerHistoryAdmin`` zastępuje
verbatim duplikaty ``class _UnfoldHistoryAdmin(...)`` w każdej aplikacji.
"""

from __future__ import annotations

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from .models import AuditLogEntry, BounceLog


class PlanerHistoryAdmin(ModelAdmin, SimpleHistoryAdmin):
    """Bazowa klasa dla wszystkich ``ModelAdmin`` używających simple_history.

    Łączy:

    * ``unfold.admin.ModelAdmin`` — Tailwind styling, dashboard widgets,
      consistent input/button look.
    * ``simple_history.admin.SimpleHistoryAdmin`` — przycisk *Historia* +
      detail-view per rewizja na liście admina.
    """


_CSV_COLUMNS = (
    "timestamp",
    "user",
    "action",
    "object_type",
    "object_repr",
    "changes_json",
    "ip_address",
)


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(ModelAdmin):
    """Read-only podgląd dziennika zdarzeń z filtrami i eksportem CSV.

    Wpisy powstają wyłącznie przez :class:`core.middleware.AuditLogMiddleware`;
    admin nie pozwala ich dodawać, edytować ani usuwać (czyszczenie tylko komendą
    ``prune_audit_log``). Dzięki temu dziennik pozostaje wiarygodnym dowodem.
    """

    list_display = (
        "timestamp",
        "user",
        "action",
        "object_type",
        "object_repr",
        "ip_address",
    )
    list_filter = ("action", "object_type", "timestamp", "user")
    search_fields = ("object_repr", "user__username", "object_id")
    date_hierarchy = "timestamp"
    list_select_related = ("user",)
    ordering = ("-timestamp",)
    actions = ("export_as_csv",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.action(description=_("Eksportuj zaznaczone do CSV"))
    def export_as_csv(self, request, queryset) -> HttpResponse:
        """Eksport wybranych wpisów do CSV (UTF-8 z BOM — Excel czyta PL znaki)."""
        filename = f"audit-log-{timezone.now():%Y-%m-%d}.csv"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        # BOM (U+FEFF) na początku pliku — dzięki niemu Excel rozpoznaje UTF-8
        # i nie psuje polskich znaków (ą, ę, ł...).
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(_CSV_COLUMNS)
        for entry in queryset.select_related("user"):
            writer.writerow(
                [
                    entry.timestamp.isoformat(),
                    entry.user.username if entry.user else "",
                    entry.action,
                    entry.object_type,
                    entry.object_repr,
                    str(entry.changes),
                    entry.ip_address or "",
                ]
            )
        return response


@admin.register(BounceLog)
class BounceLogAdmin(ModelAdmin):
    """Read-only podgląd nieudanych wysyłek e-mail (odbicia / błędy SMTP)."""

    list_display = ("created_at", "recipient", "subject")
    list_filter = ("created_at",)
    search_fields = ("recipient", "subject", "error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
