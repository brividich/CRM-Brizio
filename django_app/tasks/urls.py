from __future__ import annotations

from django.urls import path

from . import views, views_projects

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.task_list, name="list"),
    path("tasks/da-gestire/", views.da_gestire, name="da_gestire"),
    path("tasks/incontri-calendario/", views.incontri_calendario, name="incontri_calendario"),
    path("tasks/incontri/", views.incontri_lista, name="incontri_lista"),
    path("tasks/projects/", views.project_list, name="project_list"),
    path("tasks/projects/new/", views.project_create, name="project_create"),
    path(
        "tasks/projects/identity-suggest/",
        views_projects.identity_suggest,
        name="identity_suggest",
    ),
    path(
        "tasks/projects/<int:project_id>/azioni/",
        views_projects.project_actions,
        name="project_actions",
    ),
    path(
        "tasks/projects/<int:project_id>/",
        views_projects.project_overview,
        name="project_overview",
    ),
    path("tasks/projects/<int:project_id>/set-phase/", views.project_set_phase, name="project_set_phase"),
    path("tasks/projects/<int:project_id>/gantt/", views.project_gantt, name="project_gantt"),
    path(
        "tasks/projects/<int:project_id>/copy/",
        views.copy_project_with_vrf,
        name="copy_project_with_vrf",
    ),
    path(
        "tasks/projects/<int:project_id>/copy-without-pn/",
        views.copy_project_with_vrf_without_pn,
        name="copy_project_with_vrf_without_pn",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/baseline/fix/",
        views.project_gantt_fix_baseline,
        name="project_gantt_fix_baseline",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/baseline/clear/",
        views.project_gantt_clear_baseline,
        name="project_gantt_clear_baseline",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/tasks/<int:task_id>/update/",
        views.project_gantt_update_task,
        name="project_gantt_update_task",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/dependencies/add/",
        views.project_gantt_add_dependency,
        name="project_gantt_add_dependency",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/dependencies/<int:dep_id>/remove/",
        views.project_gantt_remove_dependency,
        name="project_gantt_remove_dependency",
    ),
    path(
        "tasks/projects/<int:project_id>/gantt/tasks/<int:task_id>/shift/",
        views.project_gantt_shift_task,
        name="project_gantt_shift_task",
    ),
    path("tasks/projects/<int:project_id>/info-json/", views.project_info_json, name="project_info_json"),
    path("tasks/projects/<int:project_id>/comments/add/", views.add_project_comment, name="add_project_comment"),
    path("tasks/gestione/", views.gestione_admin, name="gestione_admin"),
    path("tasks/impostazioni/", views.impostazioni, name="impostazioni"),
    path("tasks/new/", views.task_create, name="create"),
    path("tasks/<int:task_id>/", views.task_detail, name="detail"),
    path("tasks/<int:task_id>/edit/", views.task_edit, name="edit"),
    path("tasks/<int:task_id>/attrezzature/action/", views.attrezzatura_action, name="attrezzature_action"),
    path("tasks/<int:task_id>/update-due-date/", views.update_due_date, name="update_due_date"),
    path("tasks/<int:task_id>/change-status/", views.change_status, name="change_status"),
    path("tasks/<int:task_id>/comments/add/", views.add_comment, name="add_comment"),
    path("tasks/<int:task_id>/subtasks/add/", views.add_subtask, name="add_subtask"),
    path("tasks/<int:task_id>/attachments/add/", views.add_attachment, name="add_attachment"),
    path("tasks/attachments/<int:attachment_id>/download/", views.task_attachment_download, name="task_attachment_download"),
    path(
        "tasks/<int:task_id>/subtasks/<int:subtask_id>/status/",
        views.edit_subtask_status,
        name="edit_subtask_status",
    ),
    path(
        "tasks/<int:task_id>/subtasks/<int:subtask_id>/toggle/",
        views.subtask_toggle,
        name="subtask_toggle",
    ),
    path("tasks/projects/<int:project_id>/incontri/", views.project_meetings, name="project_meetings"),
    path("tasks/projects/<int:project_id>/incontri/new/", views.project_meeting_create, name="project_meeting_create"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/", views.project_meeting_detail, name="project_meeting_detail"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/edit/", views.project_meeting_edit, name="project_meeting_edit"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/esito/", views.project_meeting_minutes, name="project_meeting_minutes"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/invia-convocazione/", views.project_meeting_send_invite, name="project_meeting_send_invite"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/invia-minuta/", views.project_meeting_send_minute, name="project_meeting_send_minute"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/minuta.pdf", views.project_meeting_minute_pdf, name="project_meeting_minute_pdf"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/approva-minuta/", views.project_meeting_minute_close, name="project_meeting_minute_close"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/riapri-minuta/", views.project_meeting_minute_reopen, name="project_meeting_minute_reopen"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/delete/", views.project_meeting_delete, name="project_meeting_delete"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/problemi/<int:issue_id>/status/", views.project_meeting_issue_status, name="project_meeting_issue_status"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/agenda-toggle/<str:item_id>/", views.project_meeting_agenda_toggle, name="project_meeting_agenda_toggle"),
    path("tasks/projects/<int:project_id>/incontri/<int:meeting_id>/task-da-step/", views.project_meeting_task_from_step, name="project_meeting_task_from_step"),
    path("tasks/projects/<int:project_id>/vrf/", views.project_vrf_upload, name="project_vrf_upload"),
    path("tasks/projects/<int:project_id>/vrf/compile/", views.project_vrf_compile, name="project_vrf_compile"),
    path("tasks/projects/<int:project_id>/vrf/download/", views.project_vrf_download, name="project_vrf_download"),
    path("tasks/import/", views.import_excel, name="import_excel"),
    path("tasks/import/template/", views.download_excel_template, name="download_excel_template"),
    path("tasks/categories/<int:category_id>/fields/", views.category_fields_json, name="category_fields_json"),
    path("tasks/api/asset/<int:asset_id>/availability/", views.asset_availability_json, name="asset_availability_json"),
]
