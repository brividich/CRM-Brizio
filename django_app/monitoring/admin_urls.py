from django.urls import path

from . import views, views_backup


app_name = "monitoring_admin"

urlpatterns = [
    path("", views.admin_dashboard, name="dashboard"),
    path("status/", views.system_status, name="system_status"),
    path("status/action/", views.system_action, name="system_action"),
    path("schedules/", views.schedule_list, name="schedule_list"),
    path("schedules/action/", views.schedule_action, name="schedule_action"),
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/<int:issue_id>/", views.issue_detail, name="issue_detail"),
    path("automations/", views.automation_list, name="automation_list"),
    path("automations/<int:job_id>/", views.automation_detail, name="automation_detail"),
    path("backup/", views_backup.backup_status, name="backup_status"),
    path("backup/set/<str:set_id>/", views_backup.backup_set_detail, name="backup_set_detail"),
    path("backup/verify/", views_backup.backup_verify, name="backup_verify"),
    path("backup/restore-plan/", views_backup.backup_restore_plan, name="backup_restore_plan"),
]

