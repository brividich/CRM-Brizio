"""URLconf per l'innesto nell'HUB (area SOC IT - CN).

Fase B1: dashboard. B2: Alert/Ticket/KPI. B3: pipeline + inbox + admin/config +
diagnostica. NON si include `security/urls.py` (accoppiato a DRF/AI/API): le rotte
API REST e mailbox-admin restano fuori (arrivano più avanti).
"""
from django.http import JsonResponse
from django.urls import path

from . import api, views, views_backup, views_cases, views_events, views_incidents, views_report, views_soc, views_work

from .permissions import soc_view_required as _guard

app_name = "security"


def _api_non_montata(request, *args, **kwargs):
    """Stub: le API REST (DRF) non sono montate in questa fase (arrivano dopo).

    Serve solo a far risolvere il `reverse('security:api_addon_detail')` fatto da
    `services/addon_registry.py` per rendere la pagina Moduli.
    """
    return JsonResponse({"detail": "API non disponibile in questa fase (SOC IT - CN B3)."}, status=501)

urlpatterns = [
    path("", _guard(views.dashboard), name="dashboard"),
    path("panoramica/", _guard(views.dashboard), name="security_dashboard"),
    # B2 — Alert / Ticket / KPI
    path("alerts/", _guard(views.alerts_list), name="alerts_list"),
    path("alerts/<int:pk>/", _guard(views.alert_detail), name="alert_detail"),
    path("alerts/<int:pk>/actions/<slug:action>/", _guard(views.alert_action), name="alert_action"),
    path("alerts/<int:pk>/spiega/", views.alert_explain, name="alert_explain"),
    path("panoramica/sintesi/", views.overview_brief, name="overview_brief"),
    path("alerts/bulk/", _guard(views_cases.alerts_bulk), name="alerts_bulk"),
    # Eventi ingeriti: tutti, anche quelli giudicati «a posto»; promozione ad alert (allarme mancato)
    path("eventi/", views_events.events_list, name="events"),
    path("eventi/<int:pk>/", views_events.event_detail, name="event_detail"),
    path("eventi/<int:pk>/promuovi/", views_events.event_promote, name="event_promote"),
    path("eventi/<int:pk>/a-posto/", views_events.event_confirm_ok, name="event_confirm_ok"),
    path("eventi/<int:pk>/ai/", views_events.event_ai_triage, name="event_ai_triage"),
    path("eventi/regole-apprese/<int:pk>/attiva/", views_events.escalation_rule_toggle, name="escalation_rule_toggle"),
    # Registro incidenti (NIS2 / GDPR) e report periodico
    path("incidenti/", views_incidents.incidents_list, name="incidents"),
    path("incidenti/nuovo/", views_incidents.incident_create, name="incident_create"),
    path("incidenti/registro.pdf", views_incidents.incidents_register_pdf, name="incidents_register_pdf"),
    path("incidenti/da-ticket/<int:case_pk>/", views_incidents.incident_from_case, name="incident_from_case"),
    path("incidenti/<int:pk>/", views_incidents.incident_detail, name="incident_detail"),
    path("incidenti/<int:pk>/modifica/", views_incidents.incident_edit, name="incident_edit"),
    path("incidenti/<int:pk>/notifica/<slug:key>/", views_incidents.incident_milestone, name="incident_milestone"),
    path("incidenti/<int:pk>/note/", views_incidents.incident_note, name="incident_note"),
    path("incidenti/<int:pk>/ticket/", views_incidents.incident_link_case, name="incident_link_case"),
    path("incidenti/<int:pk>/pdf/", views_incidents.incident_pdf, name="incident_pdf"),
    path("impostazioni/", views_work.settings_page, name="soc_settings"),
    path("impostazioni/esegui/", views_work.settings_run_now, name="soc_settings_run"),
    path("mio-lavoro/", views_work.my_work, name="my_work"),
    path("cerca/", views_work.search, name="search"),
    path("pc/", views_work.pc_detail, name="pc_detail"),
    path("backup/", views_backup.backup_overview, name="backup"),
    path("backup/dispositivo/", views_backup.backup_device, name="backup_device"),
    path("backup/log/", views_backup.backup_log, name="backup_log"),
    path("report/", views_report.report_page, name="report"),
    path("report/pdf/", views_report.report_pdf, name="report_pdf"),
    path("tickets/", _guard(views_cases.tickets_list), name="tickets_list"),
    path("tickets/new/", _guard(views_cases.case_create), name="case_create"),
    path("tickets/<int:pk>/", _guard(views_cases.case_detail), name="case_detail"),
    path("tickets/<int:pk>/status/", _guard(views_cases.case_status), name="case_status"),
    path("tickets/<int:pk>/assign/", _guard(views_cases.case_assign), name="case_assign"),
    path("tickets/<int:pk>/notes/", _guard(views_cases.case_note), name="case_note"),
    path("tickets/<int:pk>/tasks/", _guard(views_cases.case_task_add), name="case_task_add"),
    path("tickets/<int:pk>/tasks/many/", _guard(views_cases.case_tasks_add_many), name="case_tasks_add_many"),
    path("tickets/<int:pk>/ai/passi/", views_cases.case_ai_steps, name="case_ai_steps"),
    path("tickets/<int:pk>/ai/esito/", views_cases.case_ai_resolution, name="case_ai_resolution"),
    path("analisi/", views.history_page, name="history"),
    path("analisi/proposte/", views.history_proposals, name="history_proposals"),
    path("tickets/<int:pk>/tasks/<int:task_id>/toggle/", _guard(views_cases.case_task_toggle), name="case_task_toggle"),
    path("tickets/<int:pk>/tasks/<int:task_id>/delete/", _guard(views_cases.case_task_delete), name="case_task_delete"),
    path("kpis/", _guard(views.kpis_page), name="kpis"),
    path("kpis/<slug:name>/", _guard(views.kpi_detail_page), name="kpi_detail"),
    path("assets/", views_soc.assets_list, name="assets"),
    path("vpn/", views_soc.vpn_history, name="vpn_history"),
    # B3 — pipeline (esecuzione sincrona via HTMX POST; nessuna coda/Celery)
    path("pipeline/", _guard(views.pipeline_page), name="pipeline"),
    path("pipeline/run/<slug:action>/", _guard(views.pipeline_run), name="pipeline_run"),
    # B3 — inbox & help
    path("inbox/", views.inbox_page, name="inbox"),
    path("help/", views.help_page, name="help"),
    path("docs/<slug:slug>/", views.doc_detail, name="doc_detail"),
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
    # B3 — autoconfigurazione (piano + fix guidati dalla diagnostica)
    path("admin/autoconfig/", views.admin_autoconfig, name="admin_autoconfig"),
    path("admin/autoconfig/apply/", views.admin_autoconfig_apply, name="admin_autoconfig_apply"),
    path("admin/autoconfig/fix/<slug:code>/", views.admin_autoconfig_fix, name="admin_autoconfig_fix"),
    # B3 — diagnostica / docs / addons
    path("admin/diagnostics/", views.admin_diagnostics, name="admin_diagnostics"),
    path("admin/docs/", views.admin_docs, name="admin_docs"),
    path("admin/addons/", views.admin_addons, name="admin_addons"),
    path("admin/addons/<slug:code>/", views.admin_addon_detail, name="admin_addon_detail"),
    # API REST read-only (summary JSON; api_ai e api_configuration ESCLUSI di proposito)
    path("api/dashboard-summary/", api.DashboardSummaryApiView.as_view(), name="api_dashboard_summary"),
    path("api/alerts/recent/", api.RecentAlertsApiView.as_view(), name="api_alerts_recent"),
    path("api/kpis/summary/", api.KpiSummaryApiView.as_view(), name="api_kpis_summary"),
    # mailbox sources (config sola lettura; ingestione Graph/IMAP non wired)
    path("admin/mailbox/", views.admin_mailbox_sources_list, name="admin_mailbox_sources_list"),
    path("admin/mailbox/run/", views_soc.run_mailbox_ingestion_view, name="run_mailbox_ingestion"),
    path("admin/mailbox/<slug:code>/", views.admin_mailbox_source_detail, name="admin_mailbox_source_detail"),
    # stub API richiesto da addon_registry per il reverse (API reale → fase futura)
    path("api/addons/<slug:code>/", _api_non_montata, name="api_addon_detail"),
]

