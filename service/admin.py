"""Django admin registration for the service app.

Mirrors :mod:`reservations.admin` — ``core.admin.PlanerHistoryAdmin``
pakuje :class:`SimpleHistoryAdmin` (audit trail) z
:class:`unfold.admin.ModelAdmin` (Tailwind theming), z
``raw_id_fields = ("machine",)`` zamiast ``autocomplete_fields`` żeby
admin pozostał szybki przy tysiącach maszyn.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from core.admin import PlanerHistoryAdmin

from .models import ServiceRecord


@admin.register(ServiceRecord)
class ServiceRecordAdmin(PlanerHistoryAdmin):
    list_display = (
        "pk",
        "machine_uid",
        "performed_date",
        "record_type",
        "performed_by",
        "cost",
        "next_inspection",
    )
    list_filter = ("record_type", "performed_date", "machine__machine_type")
    list_select_related = ("machine",)
    search_fields = (
        "machine__uid",
        "machine__name",
        "performed_by",
        "description",
    )
    date_hierarchy = "performed_date"
    raw_id_fields = ("machine",)
    ordering = ("-performed_date", "-pk")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            _("Wpis serwisowy"),
            {"fields": ("machine", "record_type", "performed_date", "performed_by")},
        ),
        (
            _("Szczegóły"),
            {"fields": ("description", "cost", "inspection_document")},
        ),
        (
            _("Następny przegląd"),
            {"fields": ("next_inspection",)},
        ),
        (
            _("Audyt"),
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    @admin.display(description=_("UID maszyny"), ordering="machine__uid")
    def machine_uid(self, obj: ServiceRecord) -> str:
        return obj.machine.uid
