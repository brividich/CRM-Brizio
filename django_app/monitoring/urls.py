from django.urls import path

from . import views


app_name = "monitoring"

urlpatterns = [
    path("report-problem/", views.report_problem, name="report_problem"),
]

