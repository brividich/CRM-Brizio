from django.contrib import admin

from .models import (
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureChangeRequest,
    ProcedureDocument,
    ProcedureQuiz,
    ProcedureQuizAttempt,
    ProcedureReadEvent,
    ProcedureRevision,
    SgiSyncLog,
)


class ProcedureRevisionInline(admin.TabularInline):
    model = ProcedureRevision
    extra = 0
    fields = ("revision_code", "revision_date", "effective_date", "source_type", "file_name", "is_current")
    readonly_fields = ("created_at",)


@admin.register(ProcedureDocument)
class ProcedureDocumentAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "document_type", "category", "is_active", "requires_acknowledgement", "escludi_dal_rag", "created_at")
    list_filter = ("document_type", "is_active", "requires_acknowledgement", "escludi_dal_rag")
    list_editable = ("escludi_dal_rag",)
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


@admin.register(ProcedureChangeRequest)
class ProcedureChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("document", "status", "created_by", "gestita_da", "created_at")
    list_filter = ("status", "document__document_type")
    search_fields = ("document__code", "document__title", "testo")
    readonly_fields = ("created_at", "updated_at", "gestita_il")


@admin.register(SgiSyncLog)
class SgiSyncLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "azione", "document_code", "revision_old", "revision_new", "origine", "run_id")
    list_filter = ("azione", "origine")
    search_fields = ("document_code", "run_id", "note")
    readonly_fields = ("run_id", "azione", "document_code", "revision_old", "revision_new", "note", "origine", "created_at")

    def has_add_permission(self, request):
        return False  # append-only: scritto solo dai task di sync
