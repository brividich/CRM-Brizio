from django.contrib import admin

from .models import Project, ProjectComment, SubTask, Task, TaskAttachment, TaskComment, TaskEvent


class SubTaskInline(admin.TabularInline):
    model = SubTask
    extra = 0
    fields = ("title", "status", "assigned_to", "due_date", "order_index")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "project",
        "status",
        "priority",
        "assigned_to",
        "created_by",
        "due_date",
        "next_step_due",
        "updated_at",
    )
    list_filter = ("status", "priority", "project", "due_date", "next_step_due")
    search_fields = ("title", "description", "next_step_text")
    filter_horizontal = ("subscribers",)
    autocomplete_fields = ("created_by", "assigned_to", "project")
    readonly_fields = ("created_at", "updated_at")
    inlines = [SubTaskInline]


@admin.register(SubTask)
class SubTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "title", "status", "assigned_to", "due_date", "order_index", "updated_at")
    list_filter = ("status", "due_date")
    search_fields = ("title", "task__title")
    autocomplete_fields = ("task", "assigned_to")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "author", "target_user", "created_at")
    search_fields = ("task__title", "author__username", "body")
    autocomplete_fields = ("task", "author", "target_user")
    readonly_fields = ("created_at",)


@admin.register(TaskEvent)
class TaskEventAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "type", "actor", "created_at")
    list_filter = ("type", "created_at")
    search_fields = ("task__title", "actor__username")
    autocomplete_fields = ("task", "actor")
    readonly_fields = ("created_at",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "client_name",
        "project_manager",
        "capo_commessa",
        "programmer",
        "part_number",
        "updated_at",
    )
    search_fields = (
        "name",
        "description",
        "client_name",
        "control_method",
        "part_number",
        "similar_work_note",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )
    autocomplete_fields = (
        "created_by",
        "project_manager",
        "capo_commessa",
        "programmer",
        "similar_project",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "project", "uploaded_by", "original_name", "created_at")
    search_fields = ("original_name", "task__title", "project__name", "uploaded_by__username")
    autocomplete_fields = ("task", "project", "uploaded_by")
    readonly_fields = ("created_at",)


@admin.register(ProjectComment)
class ProjectCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "author", "target_user", "created_at")
    search_fields = ("project__name", "author__username", "target_user__username", "body")
    autocomplete_fields = ("project", "author", "target_user")
    readonly_fields = ("created_at",)
