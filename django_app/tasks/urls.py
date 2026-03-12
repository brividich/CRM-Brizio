from __future__ import annotations

from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.task_list, name="list"),
    path("tasks/projects/", views.project_list, name="project_list"),
    path("tasks/projects/<int:project_id>/gantt/", views.project_gantt, name="project_gantt"),
    path(
        "tasks/projects/<int:project_id>/gantt/tasks/<int:task_id>/update/",
        views.project_gantt_update_task,
        name="project_gantt_update_task",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/tasks/<int:task_id>/shift/",
        views.project_gantt_shift_task,
        name="project_gantt_shift_task",
    ),
    path("tasks/projects/<int:project_id>/info-json/", views.project_info_json, name="project_info_json"),
    path("tasks/projects/<int:project_id>/comments/add/", views.add_project_comment, name="add_project_comment"),
    path("tasks/gestione/", views.gestione_admin, name="gestione_admin"),
    path("tasks/new/", views.task_create, name="create"),
    path("tasks/<int:task_id>/", views.task_detail, name="detail"),
    path("tasks/<int:task_id>/edit/", views.task_edit, name="edit"),
    path("tasks/<int:task_id>/update-due-date/", views.update_due_date, name="update_due_date"),
    path("tasks/<int:task_id>/change-status/", views.change_status, name="change_status"),
    path("tasks/<int:task_id>/comments/add/", views.add_comment, name="add_comment"),
    path("tasks/<int:task_id>/subtasks/add/", views.add_subtask, name="add_subtask"),
    path("tasks/<int:task_id>/attachments/add/", views.add_attachment, name="add_attachment"),
    path(
        "tasks/<int:task_id>/subtasks/<int:subtask_id>/status/",
        views.edit_subtask_status,
        name="edit_subtask_status",
    ),
]
