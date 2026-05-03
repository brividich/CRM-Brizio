from django.urls import path

from . import views


app_name = "monitoring"

urlpatterns = [
    path("report-problem", views.report_problem, name="report_problem_noslash"),
    path("report-problem/", views.report_problem, name="report_problem"),
    # Liveness/readiness — anche senza prefisso "monitoring/" via config/urls.py.
    path("healthz", views.healthz, name="healthz"),
    path("readyz", views.readyz, name="readyz"),
]
