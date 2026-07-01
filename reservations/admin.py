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
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

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
            _("Podstawowe"),
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
            _("Lokalizacja"),
            {
                "fields": ("address", "city"),
            },
        ),
        (
            _("Harmonogram"),
            {
                "fields": ("start_date", "end_date"),
            },
        ),
        (
            _("Dodatkowe"),
            {
                "fields": ("notes", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description=_("Aktywne rezerwacje"), ordering="reservations")
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
        "responsible_person",
        "status",
        "cancellation_reason",
        "created_at",
    )
    list_filter = (
        "status",
        "machine__machine_type",
        "site__status",
        "cancellation_reason",
    )
    list_select_related = ("machine", "site", "replaced_by")
    search_fields = (
        "machine__uid",
        "machine__name",
        "person",
        "responsible_person",
        "address",
        "site__project_number",
        "site__name",
        "batch_id",
    )
    autocomplete_fields = ("machine", "site", "replaced_by")
    ordering = ("-start_date",)
    date_hierarchy = "start_date"
    readonly_fields = ("created_at", "updated_at", "batch_id")
    actions = ("action_confirm", "action_cancel", "action_complete")
    fieldsets = (
        (
            _("Rezerwacja"),
            {
                "fields": (
                    "machine",
                    "site",
                    "status",
                ),
            },
        ),
        (
            _("Termin"),
            {
                "fields": ("start_date", "end_date", "actual_return_date"),
                "description": _(
                    "<code>actual_return_date</code> — ewidencyjny zapis faktycznego "
                    "zwrotu maszyny (B-3). Maszynę zwalnia zakończenie rezerwacji "
                    "(status „Zakończona” jest pomijany przy konfliktach), nie ta data."
                ),
            },
        ),
        (
            _("Personel"),
            {
                "fields": ("person", "responsible_person", "address"),
                "description": _(
                    "<code>person</code> = osoba w biurze, która utworzyła rezerwację. "
                    "<code>responsible_person</code> (B-4) = kierownik/brygadzista "
                    "fizycznie odpowiedzialny za maszynę na budowie."
                ),
            },
        ),
        (
            _("Anulowanie (B-2)"),
            {
                "fields": ("cancellation_reason", "cancellation_note"),
                "classes": ("collapse",),
                "description": _(
                    "Wypełniane automatycznie przez <code>cancel_reservation</code> "
                    "service gdy status zmienia się na <em>anulowana</em>."
                ),
            },
        ),
        (
            _("Wymiana maszyny i batch (B-6 / B-7)"),
            {
                "fields": ("replaced_by", "batch_id"),
                "classes": ("collapse",),
                "description": _(
                    "<code>replaced_by</code> — FK do rezerwacji-następczyni po "
                    "<em>swap_machine</em>. <code>batch_id</code> (UUID) grupuje "
                    "rezerwacje utworzone jednym kliknięciem 'Grupa rezerwacji'."
                ),
            },
        ),
        (
            _("Dodatkowe"),
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
                    gettext("Rezerwacja #%(pk)s: %(messages)s")
                    % {
                        "pk": res.pk,
                        "messages": " ".join(getattr(exc, "messages", [str(exc)])),
                    }
                )
            else:
                success += 1
        if success:
            self.message_user(
                request,
                gettext("%(label)s: %(count)s rezerwacji.")
                % {"label": success_label, "count": success},
                level=messages.SUCCESS,
            )
        if failures:
            self.message_user(request, " | ".join(failures), level=messages.WARNING)

    @admin.action(description=_("Potwierdź zaznaczone rezerwacje"))
    def action_confirm(self, request, queryset):
        self._bulk_apply(request, queryset, confirm_reservation, gettext("Potwierdzono"))

    @admin.action(description=_("Anuluj zaznaczone rezerwacje (powód: inne)"))
    def action_cancel(self, request, queryset):
        """B-2: bulk action ustawia reason="inne" (operator może doprecyzować
        ręcznie). Inne wybory ograniczyłyby UX bulk-operations w admin —
        zaawansowane workflow (np. masowe anulowanie z powodu awarii flotty)
        wymagałyby dedykowanego widoku z dropdownem reason.
        """
        from functools import partial

        cancel_with_reason = partial(cancel_reservation, reason="inne")
        self._bulk_apply(request, queryset, cancel_with_reason, gettext("Anulowano"))

    @admin.action(description=_("Zakończ zaznaczone rezerwacje"))
    def action_complete(self, request, queryset):
        self._bulk_apply(request, queryset, complete_reservation, gettext("Zakończono"))
