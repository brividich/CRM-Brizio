from django.contrib import admin

from .models import (
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureDocument,
    ProcedureQuiz,
    ProcedureQuizAttempt,
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


@admin.register(ProcedureQuiz)
class ProcedureQuizAdmin(admin.ModelAdmin):
    list_display = ("revision", "title", "is_active", "question_count", "updated_at")
    list_filter = ("is_active", "revision__document__document_type")
    search_fields = ("title", "revision__document__code", "revision__document__title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProcedureQuizAttempt)
class ProcedureQuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("quiz", "assignment", "user", "score", "total_questions", "submitted_at")
    list_filter = ("quiz",)
    search_fields = ("user__username", "user__last_name", "quiz__revision__document__code")
    readonly_fields = ("submitted_at",)
