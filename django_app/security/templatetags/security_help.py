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
    "pc_copertura": ("15-backup-vpn-kpi-asset", "dispositivi"),
    "watchguard_pc": ("12-automatismi-e-vulnerabilita", "patch-e-protezione-watchguard"),
    "watchguard_patch_installate": ("12-automatismi-e-vulnerabilita", "patch-installate"),
    "watchguard_task": ("12-automatismi-e-vulnerabilita", "installazioni-da-console"),
    "watchguard_patch_tempi": ("12-automatismi-e-vulnerabilita", "tempi-delle-patch"),
    "dipendenze_portale": ("12-automatismi-e-vulnerabilita", "librerie-del-portale"),
    "rete_indirizzi": ("15-backup-vpn-kpi-asset", "rete-ip"),
    "letture": ("16-impostazioni-e-ai", "letture-automatiche"),
    "battito": ("16-impostazioni-e-ai", "battito-del-soc"),
    "segnalazioni": ("13-lavoro-quotidiano", "le-segnalazioni"),
    "search": ("13-lavoro-quotidiano", "cercare-qualcosa"),
    "alerts_list": ("13-lavoro-quotidiano", "alert"),
    "alert_detail": ("13-lavoro-quotidiano", "alert"),
    "alert_proposte": ("13-lavoro-quotidiano", "proposte-di-chiusura-dellai"),
    "events": ("13-lavoro-quotidiano", "eventi"),
    "event_detail": ("13-lavoro-quotidiano", "eventi"),
    "tickets_list": ("13-lavoro-quotidiano", "ticket"),
    "case_create": ("13-lavoro-quotidiano", "ticket"),
    "case_detail": ("13-lavoro-quotidiano", "ticket"),
    "history": ("13-lavoro-quotidiano", "analisi-dello-storico"),
    "pc_detail": ("13-lavoro-quotidiano", "scheda-pc-e-server"),
    "incidents": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_create": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_edit": ("14-incidenti-e-report", "registrare-un-incidente"),
    "incident_detail": ("14-incidenti-e-report", "le-scadenze"),
    "report": ("14-incidenti-e-report", "report-periodico"),
    "iso27001": ("19-conformita-iso27001", "la-pagina"),
    "backup": ("15-backup-vpn-kpi-asset", "backup"),
    "backup_log": ("15-backup-vpn-kpi-asset", "backup"),
    "backup_ripristini": ("15-backup-vpn-kpi-asset", "prove-di-ripristino"),
    "backup_device": ("15-backup-vpn-kpi-asset", "backup"),
    "vpn_history": ("15-backup-vpn-kpi-asset", "accessi-vpn"),
    "kpis": ("15-backup-vpn-kpi-asset", "kpi-e-trend"),
    "kpi_detail": ("15-backup-vpn-kpi-asset", "kpi-e-trend"),
    "assets": ("15-backup-vpn-kpi-asset", "dispositivi"),
    "pipeline": ("15-backup-vpn-kpi-asset", "stato-elaborazione"),
    "soc_settings": ("16-impostazioni-e-ai", "avvisi-automatici"),
    "suppressions": ("12-automatismi-e-vulnerabilita", "soppressione-appresa"),
    "automation": ("12-automatismi-e-vulnerabilita", "automatismi-di-rientro"),
    "vulnerabilities": ("12-automatismi-e-vulnerabilita", "impatto-cve-sugli-asset"),
    "cve_detail": ("12-automatismi-e-vulnerabilita", "come-si-legge-lesito"),
    "accettazioni_rischio": ("12-automatismi-e-vulnerabilita", "accettazione-del-rischio"),
    "cve_correzioni": ("12-automatismi-e-vulnerabilita", "correzioni-cve"),
    "inventory": ("12-automatismi-e-vulnerabilita", "importare-un-inventario"),
    "inventory_map": ("12-automatismi-e-vulnerabilita", "importare-un-inventario"),
    "software_mapping": ("12-automatismi-e-vulnerabilita", "collegare-i-software-alle-cve-cpe"),
    "admin_config": ("08-configuration-guide", ""),
    "admin_config_general": ("08-configuration-guide", ""),
    "admin_config_sources": ("08-configuration-guide", "sorgenti"),
    "admin_config_parsers": ("08-configuration-guide", "parser"),
    "admin_config_alert_rules": ("08-configuration-guide", "regole-alert"),
    "admin_config_suppressions": ("08-configuration-guide", "soppressioni"),
    "admin_config_backups": ("08-configuration-guide", "backup"),
    "admin_config_notifications": ("08-configuration-guide", "notifiche"),
    "admin_config_ticketing": ("08-configuration-guide", "ticketing"),
    "admin_config_audit": ("08-configuration-guide", "audit"),
    "watchguard_credenziali": ("12-automatismi-e-vulnerabilita", "patch-e-protezione-watchguard"),
    "veeam_credenziali": ("16-impostazioni-e-ai", "backup-letti-direttamente-da-veeam"),
    "admin_mailbox_sources_list": ("mailbox-ingestion", ""),
    "admin_mailbox_source_detail": ("mailbox-ingestion", ""),
    "admin_autoconfig": ("02-admin-guide", "autoconfigurazione"),
    "inbox": ("13-lavoro-quotidiano", "caricare-un-report-a-mano"),
    "admin_addons": ("17-moduli-diagnostica-documentazione", "moduli"),
    "admin_addon_detail": ("17-moduli-diagnostica-documentazione", "la-scheda-del-modulo"),
    "admin_diagnostics": ("17-moduli-diagnostica-documentazione", "diagnostica"),
    "admin_docs": ("17-moduli-diagnostica-documentazione", "documentazione"),
    "registro_log": ("18-registro-accessi", "panoramica"),
    "registro_log_eventi": ("18-registro-accessi", "eventi"),
    "registro_log_evento": ("18-registro-accessi", "eventi"),
    "registro_log_ads": ("18-registro-accessi", "amministratori-di-sistema"),
    "registro_log_ads_nomina": ("18-registro-accessi", "amministratori-di-sistema"),
    "registro_log_account": ("18-registro-accessi", "account-ad"),
    "registro_log_verifica": ("18-registro-accessi", "verifica-annuale"),
    "registro_log_archivio": ("18-registro-accessi", "archivio-e-integrità"),
    "registro_log_infra": ("18-registro-accessi", "server-e-virtualizzazione"),
    "registro_log_fonti": ("18-registro-accessi", "fonti-e-impostazioni"),
    "registro_log_postazioni": ("18-registro-accessi", "pc-del-dominio"),
    "registro_log_indagini": ("18-registro-accessi", "indagini-file-stampe-e-usb"),
    "registro_log_indagine": ("18-registro-accessi", "indagini-file-stampe-e-usb"),
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
