"""django-admin (django-unfold themed) configuration for the machines app."""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.admin import PlanerHistoryAdmin
from core.templatetags.planer_tags import status_badge

from .models import Machine


@admin.register(Machine)
class MachineAdmin(PlanerHistoryAdmin):
    """Admin with simple-history audit + django-unfold theming."""

    list_display = (
        "uid",
        "name",
        "machine_type",
        "status_badge_admin",
        "inspection_status_admin",
        "is_reservable",
        "location",
    )
    list_filter = ("status", "machine_type", "is_reservable")
    search_fields = ("uid", "name", "manufacturer", "serial_number")
    list_per_page = 25
    ordering = ("uid",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            _("Podstawowe"),
            {
                "fields": (
                    "uid",
                    "name",
                    "machine_type",
                    "status",
                    "is_reservable",
                    "location",
                )
            },
        ),
        (
            _("Specyfikacja"),
            {"fields": ("model", "capacity", "manufacturer", "serial_number", "build_year")},
        ),
        (_("Przegląd"), {"fields": ("inspection_date",)}),
        (_("Zdjęcie"), {"fields": ("image",)}),
        (_("Notatki"), {"fields": ("notes",)}),
        (_("Audyt"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    # Pretty list-column renderers
    # -----------------------------------------------------------------

    @admin.display(description=_("Status"))
    def status_badge_admin(self, obj: Machine) -> str:
        css = status_badge(obj.status)
        return format_html(
            '<span class="px-2 py-0.5 rounded text-xs {}">{}</span>', css, obj.status
        )

    @admin.display(description=_("Przegląd"))
    def inspection_status_admin(self, obj: Machine) -> str:
        icons = {"ok": "✅", "warning": "⚠️", "overdue": "🔴", "unknown": "❓"}
        marker = icons.get(obj.inspection_status, "❓")
        return f"{marker} {obj.inspection_status_label}"
