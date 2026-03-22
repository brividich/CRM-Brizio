from django.contrib import admin

from .models import (
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureDocument,
    ProcedureReadEvent,
    ProcedureRevision,
)


class ProcedureRevisionInline(admin.TabularInline):
    model = ProcedureRevision
    extra = 0
    fields = ("revision_code", "revision_date", "effective_date", "source_type", "file_name", "is_current")
    readonly_fields = ("created_at",)


@admin.register(ProcedureDocument)
class ProcedureDocumentAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "document_type", "category", "is_active", "requires_acknowledgement", "created_at")
    list_filter = ("document_type", "is_active", "requires_acknowledgement")
    search_fields = ("code", "title", "category", "owner_department")
    inlines = [ProcedureRevisionInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProcedureRevision)
class ProcedureRevisionAdmin(admin.ModelAdmin):
    list_display = ("document", "revision_code", "revision_date", "effective_date", "source_type", "is_current")
    list_filter = ("source_type", "is_current")
    search_fields = ("document__code", "document__title", "revision_code", "file_name")
    readonly_fields = ("created_at", "updated_at")


class ProcedureCampaignDocumentInline(admin.TabularInline):
    model = ProcedureCampaignDocument
    extra = 0
    fields = ("revision", "is_mandatory", "display_order")
    autocomplete_fields = ()


@admin.register(ProcedureCampaign)
class ProcedureCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "start_date", "due_date", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)
    inlines = [ProcedureCampaignDocumentInline]
    readonly_fields = ("created_at", "updated_at", "published_at", "closed_at")


@admin.register(ProcedureAssignment)
class ProcedureAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "campaign", "revision", "status", "assigned_at", "read_confirmed_flag")
    list_filter = ("status", "campaign")
    search_fields = ("user__username", "user__last_name", "campaign__name")
    readonly_fields = ("assigned_at", "first_opened_at", "last_opened_at", "read_confirmed_at", "open_count", "created_at", "updated_at")


@admin.register(ProcedureReadEvent)
class ProcedureReadEventAdmin(admin.ModelAdmin):
    list_display = ("assignment", "event_type", "event_at", "event_by")
    list_filter = ("event_type",)
    readonly_fields = ("event_at",)
