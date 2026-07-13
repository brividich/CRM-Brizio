"""URLconf per l'innesto nell'HUB (area SOC IT - CN).

Fase B1: dashboard. B2: Alert/Ticket/KPI. B3: pipeline + inbox + admin/config +
diagnostica. NON si include `security/urls.py` (accoppiato a DRF/AI/API): le rotte
API REST e mailbox-admin restano fuori (arrivano più avanti).
"""
from django.http import JsonResponse
from django.urls import path

from . import views, views_soc

app_name = "security"


def _api_non_montata(request, *args, **kwargs):
    """Stub: le API REST (DRF) non sono montate in questa fase (arrivano dopo).

    Serve solo a far risolvere il `reverse('security:api_addon_detail')` fatto da
    `services/addon_registry.py` per rendere la pagina Moduli.
    """
    return JsonResponse({"detail": "API non disponibile in questa fase (SOC IT - CN B3)."}, status=501)

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("panoramica/", views.dashboard, name="security_dashboard"),
    # B2 — Alert / Ticket / KPI
    path("alerts/", views.alerts_list, name="alerts_list"),
    path("alerts/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("alerts/<int:pk>/actions/<slug:action>/", views.alert_action, name="alert_action"),
    path("tickets/", views.tickets_list, name="tickets_list"),
    path("kpis/", views.kpis_page, name="kpis"),
    path("assets/", views_soc.assets_list, name="assets"),
    # B3 — pipeline (esecuzione sincrona via HTMX POST; nessuna coda/Celery)
    path("pipeline/", views.pipeline_page, name="pipeline"),
    path("pipeline/run/<slug:action>/", views.pipeline_run, name="pipeline_run"),
    # B3 — inbox & help
    path("inbox/", views.inbox_page, name="inbox"),
    path("help/", views.help_page, name="help"),
    # B3 — admin / config (Configuration Studio)
    path("admin/config/", views.admin_config_dashboard, name="admin_config"),
    path("admin/config/general/", views.admin_config_general, name="admin_config_general"),
    path("admin/config/sources/", views.admin_config_sources, name="admin_config_sources"),
    path("admin/config/parsers/", views.admin_config_parsers, name="admin_config_parsers"),
    path("admin/config/alert-rules/", views.admin_config_alert_rules, name="admin_config_alert_rules"),
    path("admin/config/suppressions/", views.admin_config_suppressions, name="admin_config_suppressions"),
    path("admin/config/backups/", views.admin_config_backups, name="admin_config_backups"),
    path("admin/config/notifications/", views.admin_config_notifications, name="admin_config_notifications"),
    path("admin/config/ticketing/", views.admin_config_ticketing, name="admin_config_ticketing"),
    path("admin/config/audit/", views.admin_config_audit, name="admin_config_audit"),
    # B3 — diagnostica / docs / addons
    path("admin/diagnostics/", views.admin_diagnostics, name="admin_diagnostics"),
    path("admin/docs/", views.admin_docs, name="admin_docs"),
    path("admin/addons/", views.admin_addons, name="admin_addons"),
    path("admin/addons/<slug:code>/", views.admin_addon_detail, name="admin_addon_detail"),
    # mailbox sources (config sola lettura; ingestione Graph/IMAP non wired)
    path("admin/mailbox/", views.admin_mailbox_sources_list, name="admin_mailbox_sources_list"),
    path("admin/mailbox/<slug:code>/", views.admin_mailbox_source_detail, name="admin_mailbox_source_detail"),
    # stub API richiesto da addon_registry per il reverse (API reale → fase futura)
    path("api/addons/<slug:code>/", _api_non_montata, name="api_addon_detail"),
]

