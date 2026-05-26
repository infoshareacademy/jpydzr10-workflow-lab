"""Admin (django-unfold) dla aplikacji accounts."""

from django.contrib import admin, messages

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
        ("Powiązanie z użytkownikiem", {"fields": ("user",)}),
        (
            "Dane pracownika",
            {
                "fields": (
                    "function",
                    "employee_id",
                    "phone",
                    "is_active_employee",
                ),
            },
        ),
        ("Preferencje UI", {"fields": ("theme_preference",)}),
        (
            "Offboarding / GDPR",
            {
                "fields": (
                    "termination_date",
                    "termination_reason",
                    "is_anonymized",
                    "anonymized_at",
                ),
            },
        ),
        ("Metadane", {"fields": ("created_at", "updated_at")}),
    )

    @admin.action(description="Zakończ zatrudnienie wybranych")
    def action_terminate(self, request, queryset):
        """Bulk-terminacja aktywnych pracowników (z pominięciem zanonimizowanych)."""
        count = 0
        for profile in queryset.filter(is_active_employee=True, is_anonymized=False):
            terminate_employee(profile, actor=request.user)
            count += 1
        self.message_user(
            request,
            f"Zakończono zatrudnienie {count} pracowników.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Anonimizuj wybranych (GDPR Art.17)")
    def action_anonymize(self, request, queryset):
        """Bulk-anonimizacja pracowników (idempotentnie pomija już zanonimizowanych)."""
        count = 0
        for profile in queryset.filter(is_anonymized=False):
            anonymize_employee(profile, actor=request.user)
            count += 1
        self.message_user(
            request,
            f"Zanonimizowano {count} pracowników.",
            level=messages.WARNING,
        )
