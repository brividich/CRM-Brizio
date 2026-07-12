"""URLconf per l'innesto nell'HUB (area SOC IT - CN).

Fase B1: dashboard. B2: Alert/Ticket/KPI. B3: pipeline (esecuzione sincrona).
NON si include `security/urls.py` (accoppiato a DRF/AI/API): le rotte API restano
fuori. admin/config, inbox e diagnostica arrivano nelle fasi successive di B3.
"""
from django.urls import path

from . import views

app_name = "security"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("panoramica/", views.dashboard, name="security_dashboard"),
    # B2 — Alert / Ticket / KPI
    path("alerts/", views.alerts_list, name="alerts_list"),
    path("alerts/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("alerts/<int:pk>/actions/<slug:action>/", views.alert_action, name="alert_action"),
    path("tickets/", views.tickets_list, name="tickets_list"),
    path("kpis/", views.kpis_page, name="kpis"),
    # B3 — pipeline (esecuzione sincrona via HTMX POST; nessuna coda/Celery)
    path("pipeline/", views.pipeline_page, name="pipeline"),
    path("pipeline/run/<slug:action>/", views.pipeline_run, name="pipeline_run"),
]
