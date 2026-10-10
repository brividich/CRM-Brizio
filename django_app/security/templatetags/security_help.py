"""Link «Guida di questa pagina»: dal nome della rotta SOC al capitolo della guida in-app."""
from django import template
from django.urls import reverse

register = template.Library()

# url_name -> (slug del documento, ancora). Le ancore sono i titoli resi da docs_render._heading_slug:
# se cambia un titolo della guida, tests/test_docs_render.py lo segnala.
PAGE_HELP = {
    "dashboard": ("13-lavoro-quotidiano", "da-dove-partire"),
    "security_dashboard": ("13-lavoro-quotidiano", "da-dove-partire"),
    "my_work": ("13-lavoro-quotidiano", "da-dove-partire"),
    "search": ("13-lavoro-quotidiano", "cercare-qualcosa"),
    "alerts_list": ("13-lavoro-quotidiano", "alert"),
    "alert_detail": ("13-lavoro-quotidiano", "alert"),
    "events": ("13-lavoro-quotidiano", "eventi"),
    "event_detail": ("13-lavoro-quotidiano", "eventi"),
    "tickets_list": ("13-lavoro-quotidiano", "ticket"),
    "case_detail": ("13-lavoro-quotidiano", "ticket"),
    "history": ("13-lavoro-quotidiano", "analisi-dello-storico"),
    "pc_detail": ("13-lavoro-quotidiano", "scheda-pc-e-server"),
    "incidents": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_create": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_edit": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_detail": ("14-incidenti-e-report", "le-scadenze"),
    "report": ("14-incidenti-e-report", "report-periodico"),
    "backup": ("15-backup-vpn-kpi-asset", "backup"),
    "backup_log": ("15-backup-vpn-kpi-asset", "backup"),
    "backup_device": ("15-backup-vpn-kpi-asset", "backup"),
    "vpn_history": ("15-backup-vpn-kpi-asset", "accessi-vpn"),
    "kpis": ("15-backup-vpn-kpi-asset", "kpi-e-trend"),
    "kpi_detail": ("15-backup-vpn-kpi-asset", "kpi-e-trend"),
    "assets": ("15-backup-vpn-kpi-asset", "asset"),
    "pipeline": ("15-backup-vpn-kpi-asset", "stato-elaborazione"),
    "soc_settings": ("16-impostazioni-e-ai", "avvisi-automatici"),
    "suppressions": ("12-automatismi-e-vulnerabilita", "soppressione-appresa"),
    "automation": ("12-automatismi-e-vulnerabilita", "automatismi-di-rientro"),
    "vulnerabilities": ("12-automatismi-e-vulnerabilita", "impatto-cve-sugli-asset"),
    "cve_detail": ("12-automatismi-e-vulnerabilita", "come-si-legge-lesito"),
    "inventory": ("12-automatismi-e-vulnerabilita", "importare-un-inventario"),
    "inventory_map": ("12-automatismi-e-vulnerabilita", "importare-un-inventario"),
    "software_mapping": ("12-automatismi-e-vulnerabilita", "collegare-i-software-alle-cve-cpe"),
    "admin_mailbox_sources_list": ("mailbox-ingestion", ""),
    "admin_mailbox_source_detail": ("mailbox-ingestion", ""),
    "admin_autoconfig": ("02-admin-guide", "autoconfigurazione"),
}


@register.simple_tag
def soc_page_help_url(url_name):
    """URL del capitolo della guida per la pagina corrente; l'indice della guida se non c'è un capitolo dedicato."""
    if url_name in PAGE_HELP:
        slug, anchor = PAGE_HELP[url_name]
    elif (url_name or "").startswith("admin_config"):
        slug, anchor = "08-configuration-guide", ""
    else:
        return reverse("security:help")
    url = reverse("security:doc_detail", args=[slug])
    return f"{url}#{anchor}" if anchor else url
