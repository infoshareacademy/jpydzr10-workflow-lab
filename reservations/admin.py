"""Django admin registration for the reservations app.

Uses :class:`simple_history.admin.SimpleHistoryAdmin` so each save in the
admin is captured in the historical tables (``reservations_historicalreservation``,
``reservations_historicalconstructionsite``). The ``django-unfold`` theme
inherits the Tailwind styling project-wide; ``core.admin.PlanerHistoryAdmin``
pulls in :class:`unfold.admin.ModelAdmin` so per-page widgets render in the
unfold style.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from core.admin import PlanerHistoryAdmin

from .models import ConstructionSite, Reservation
from .services import (
    cancel_reservation,
    complete_reservation,
    confirm_reservation,
)

# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


@admin.register(ConstructionSite)
class ConstructionSiteAdmin(PlanerHistoryAdmin):
    list_display = (
        "project_number",
        "name",
        "client_name",
        "city",
        "status",
        "active_reservation_count",
        "created_at",
    )
    list_filter = ("status", "city")
    search_fields = ("project_number", "name", "client_name", "address", "city")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Podstawowe",
            {
                "fields": (
                    "project_number",
                    "name",
                    "client_name",
                    "status",
                ),
            },
        ),
        (
            "Lokalizacja",
            {
                "fields": ("address", "city"),
            },
        ),
        (
            "Harmonogram",
            {
                "fields": ("start_date", "end_date"),
            },
        ),
        (
            "Dodatkowe",
            {
                "fields": ("notes", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Aktywne rezerwacje", ordering="reservations")
    def active_reservation_count(self, obj: ConstructionSite) -> int:
        return obj.active_reservation_count


# =============================================================================
# RESERVATION
# =============================================================================


@admin.register(Reservation)
class ReservationAdmin(PlanerHistoryAdmin):
    list_display = (
        "pk",
        "machine",
        "site",
        "start_date",
        "end_date",
        "person",
        "status",
        "created_at",
    )
    list_filter = ("status", "machine__machine_type", "site__status")
    list_select_related = ("machine", "site")
    search_fields = (
        "machine__uid",
        "machine__name",
        "person",
        "address",
        "site__project_number",
        "site__name",
    )
    autocomplete_fields = ("machine", "site")
    ordering = ("-start_date",)
    date_hierarchy = "start_date"
    readonly_fields = ("created_at", "updated_at")
    actions = ("action_confirm", "action_cancel", "action_complete")
    fieldsets = (
        (
            "Rezerwacja",
            {
                "fields": (
                    "machine",
                    "site",
                    "status",
                ),
            },
        ),
        (
            "Termin",
            {
                "fields": ("start_date", "end_date"),
            },
        ),
        (
            "Osoba i adres",
            {
                "fields": ("person", "address"),
            },
        ),
        (
            "Dodatkowe",
            {
                "fields": ("notes", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    # ---------- bulk actions (call services, gather errors) -----------------

    def _bulk_apply(self, request, queryset, fn, success_label: str) -> None:
        """Apply ``fn`` to each row in ``queryset`` and report counts."""
        success = 0
        failures: list[str] = []
        for res in queryset:
            try:
                fn(res)
            except ValidationError as exc:
                failures.append(
                    f"Rezerwacja #{res.pk}: {' '.join(getattr(exc, 'messages', [str(exc)]))}"
                )
            else:
                success += 1
        if success:
            self.message_user(
                request, f"{success_label}: {success} rezerwacji.", level=messages.SUCCESS
            )
        if failures:
            self.message_user(request, " | ".join(failures), level=messages.WARNING)

    @admin.action(description="Potwierdź zaznaczone rezerwacje")
    def action_confirm(self, request, queryset):
        self._bulk_apply(request, queryset, confirm_reservation, "Potwierdzono")

    @admin.action(description="Anuluj zaznaczone rezerwacje (powód: inne)")
    def action_cancel(self, request, queryset):
        """B-2: bulk action ustawia reason="inne" (operator może doprecyzować
        ręcznie). Inne wybory ograniczyłyby UX bulk-operations w admin —
        zaawansowane workflow (np. masowe anulowanie z powodu awarii flotty)
        wymagałyby dedykowanego widoku z dropdownem reason.
        """
        from functools import partial

        cancel_with_reason = partial(cancel_reservation, reason="inne")
        self._bulk_apply(request, queryset, cancel_with_reason, "Anulowano")

    @admin.action(description="Zakończ zaznaczone rezerwacje")
    def action_complete(self, request, queryset):
        self._bulk_apply(request, queryset, complete_reservation, "Zakończono")
