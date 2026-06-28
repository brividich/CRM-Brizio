from django.urls import path

from . import views


app_name = "monitoring_admin"

urlpatterns = [
    path("", views.admin_dashboard, name="dashboard"),
    path("status/", views.system_status, name="system_status"),
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/<int:issue_id>/", views.issue_detail, name="issue_detail"),
    path("automations/", views.automation_list, name="automation_list"),
    path("automations/<int:job_id>/", views.automation_detail, name="automation_detail"),
]

