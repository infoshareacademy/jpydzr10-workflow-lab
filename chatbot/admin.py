"""Konfiguracja django-admin (django-unfold themed) dla chatbota.

Brak ``simple_history`` — chat history sama w sobie jest pełnym audit trailem
(każdy turn to osobny wiersz w ``Message``), więc nie potrzebujemy
``SimpleHistoryAdmin``. Ekran służy administratorowi do podglądu rozmów
(np. żeby zobaczyć co najczęściej pyta operator, lub debugować błędy agenta).
"""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from .models import Conversation, Message


class MessageInline(TabularInline):
    """Inline lista wiadomości w widoku konwersacji (read-mostly)."""

    model = Message
    extra = 0
    fields = ("created_at", "role", "content", "tokens_used")
    readonly_fields = ("created_at",)
    ordering = ("created_at",)
    show_change_link = True


@admin.register(Conversation)
class ConversationAdmin(ModelAdmin):
    """Lista konwersacji z filtrami per user / status archiwizacji."""

    list_display = ("pk", "user", "title_preview", "message_count", "is_archived", "created_at")
    list_filter = ("is_archived", "created_at")
    search_fields = ("user__username", "user__email", "title")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (MessageInline,)
    fieldsets = (
        (_("Konwersacja"), {"fields": ("user", "title", "is_archived")}),
        (_("Audyt"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Tytuł"))
    def title_preview(self, obj: Conversation) -> str:
        return obj.title or "—"

    @admin.display(description=_("Wiadomości"))
    def message_count(self, obj: Conversation) -> int:
        return obj.messages.count()


@admin.register(Message)
class MessageAdmin(ModelAdmin):
    """Lista pojedynczych wiadomości — przydatne do debugowania błędów agenta."""

    list_display = (
        "pk",
        "conversation",
        "role_badge",
        "content_preview",
        "tokens_used",
        "created_at",
    )
    list_filter = ("role", "created_at")
    search_fields = ("content", "conversation__title", "conversation__user__username")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    raw_id_fields = ("conversation",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description=_("Rola"))
    def role_badge(self, obj: Message) -> str:
        colors = {
            Message.Role.USER: "bg-blue-100 text-blue-800",
            Message.Role.ASSISTANT: "bg-green-100 text-green-800",
            Message.Role.SYSTEM: "bg-gray-100 text-gray-800",
            Message.Role.ERROR: "bg-red-100 text-red-800",
        }
        css = colors.get(obj.role, "bg-gray-100 text-gray-800")
        return format_html(
            '<span class="px-2 py-0.5 rounded text-xs {}">{}</span>', css, obj.get_role_display()
        )

    @admin.display(description=_("Treść"))
    def content_preview(self, obj: Message) -> str:
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")
