"""Admin (django-unfold) dla aplikacji accounts."""

from django.contrib import admin, messages
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from core.admin import PlanerHistoryAdmin

from .models import EmployeeProfile
from .services import anonymize_employee, terminate_employee


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(PlanerHistoryAdmin):
    """Admin profilu pracownika z historią zmian (simple_history)."""

    list_display = (
        "user",
        "function",
        "phone",
        "employee_id",
        "is_active_employee",
        "is_anonymized",
        "updated_at",
    )
    list_filter = (
        "function",
        "is_active_employee",
        "is_anonymized",
        "theme_preference",
    )
    search_fields = ("user__username", "user__email", "phone", "employee_id")
    readonly_fields = ("created_at", "updated_at", "anonymized_at")
    actions = ["action_terminate", "action_anonymize"]
    fieldsets = (
        (_("Powiązanie z użytkownikiem"), {"fields": ("user",)}),
        (
            _("Dane pracownika"),
            {
                "fields": (
                    "function",
                    "employee_id",
                    "phone",
                    "is_active_employee",
                ),
            },
        ),
        (_("Preferencje UI"), {"fields": ("theme_preference",)}),
        (
            _("Offboarding / GDPR"),
            {
                "fields": (
                    "termination_date",
                    "termination_reason",
                    "is_anonymized",
                    "anonymized_at",
                ),
            },
        ),
        (_("Metadane"), {"fields": ("created_at", "updated_at")}),
    )

    @admin.action(description=_("Zakończ zatrudnienie wybranych"))
    def action_terminate(self, request, queryset):
        """Bulk-terminacja aktywnych pracowników (z pominięciem zanonimizowanych)."""
        count = 0
        for profile in queryset.filter(is_active_employee=True, is_anonymized=False):
            terminate_employee(profile, actor=request.user)
            count += 1
        self.message_user(
            request,
            gettext("Zakończono zatrudnienie %(count)s pracowników.") % {"count": count},
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Anonimizuj wybranych (GDPR Art.17)"))
    def action_anonymize(self, request, queryset):
        """Bulk-anonimizacja pracowników (idempotentnie pomija już zanonimizowanych)."""
        count = 0
        for profile in queryset.filter(is_anonymized=False):
            anonymize_employee(profile, actor=request.user)
            count += 1
        self.message_user(
            request,
            gettext("Zanonimizowano %(count)s pracowników.") % {"count": count},
            level=messages.WARNING,
        )
