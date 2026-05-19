from django.contrib import admin

from .models import AiKnowledgeEntry


@admin.register(AiKnowledgeEntry)
class AiKnowledgeEntryAdmin(admin.ModelAdmin):
    list_display = ("question", "source_label", "is_active", "updated_at", "created_by")
    list_filter = ("is_active", "source_label", "created_at")
    search_fields = ("question", "answer", "source_label")
    readonly_fields = ("created_at", "updated_at")
