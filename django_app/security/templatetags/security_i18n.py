from django import template


register = template.Library()


LABELS = {
    "acknowledged": "Preso in carico",
    "closed": "Chiuso",
    "critical": "Critico",
    "disabled": "Disattivato",
    "error": "Errore",
    "failed": "Fallito",
    "false_positive": "Falso positivo",
    "high": "Alto",
    "info": "Info",
    "kpi_only": "Solo KPI",
    "alert": "Alert",
    "suppressed_kpi_only": "Soppresso (solo KPI)",
    "completed": "Completato",
    "in_progress": "In lavorazione",
    "low": "Basso",
    "medium": "Medio",
    "misconfigured": "Configurazione errata",
    "muted": "Silenziato",
    "new": "Nuovo",
    "ok": "OK",
    "open": "Aperto",
    "parsed": "Analizzato",
    "pending": "In attesa",
    "resolved": "Risolto",
    "skipped": "Scartato",
    "success": "Riuscita",
    "partial": "Parziale",
    "running": "In corso",
    "already_processed": "Già elaborato",
    "dry_run": "Prova",
    "enabled": "Attivo",
    "manual": "Manuale",
    "hourly": "Oraria",
    "daily": "Giornaliera",
    "weekly": "Settimanale",
    "monthly": "Mensile",
    "snoozed": "Posticipato",
    "suppressed": "Soppresso",
    "warning": "Attenzione",
}


CANONICAL_LABELS = {
    "acknowledged": "Acknowledged",
    "closed": "Closed",
    "false_positive": "False positive",
    "in_progress": "In progress",
    "muted": "Muted",
    "new": "New",
    "open": "Open",
    "resolved": "Resolved",
    "snoozed": "Snoozed",
    "suppressed": "Suppressed",
}


@register.filter
def ui_label(value):
    if value is None:
        return "-"
    text = str(value)
    return LABELS.get(text.lower(), text)


@register.filter
def canonical_status_label(value):
    if value is None:
        return "-"
    text = str(value)
    return CANONICAL_LABELS.get(text.lower(), text)


@register.filter
def si_no(value):
    return "Si" if value else "No"


# Chiavi tecniche nei payload/decision trace: nomi leggibili in italiano.
KV_LABELS = {
    "rule": "Regola",
    "reason": "Motivo",
    "decision": "Decisione",
    "cve": "CVE",
    "cvss": "CVSS",
    "exposed_devices": "Dispositivi esposti",
    "affected_product": "Prodotto",
    "backup_status": "Esito backup",
    "job_name": "Job",
    "status": "Stato",
    "vendor": "Fornitore",
    "source": "Sorgente",
    "sender": "Mittente",
    "sender_domain": "Dominio mittente",
    "claimed_vendor": "Si presenta come",
    "subject": "Oggetto",
    "device_name": "Dispositivo",
    "nas_name": "NAS",
    "start_time": "Inizio",
    "end_time": "Fine",
    "duration_seconds": "Durata (s)",
    "transferred_size_gb": "Trasferiti (GB)",
    "protected_items": "Elementi protetti",
    "received_at": "Ricevuto il",
    "expected_every_hours": "Cadenza attesa (h)",
    "hours_silent": "Ore di silenzio",
    "last_report_at": "Ultimo report",
    "organization": "Organizzazione",
    "detail": "Dettaglio",
}
KV_HIDDEN = {"alert_created", "dedup_hash", "raw_body_hash", "raw_excerpt_hash", "fingerprint", "raw_excerpt"}


def _pretty_datetime(text):
    """'2026-09-26T12:16:39.646+00:00' -> '26/09/2026 14:16' (ora locale); altro invariato."""
    from datetime import datetime

    from django.utils import timezone

    if len(text) < 16 or text[4:5] != "-" or text[10:11] not in ("T", " "):
        return text
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y %H:%M")


@register.filter
def kv_items(value, limit=40):
    """Dict (payload / decision trace) -> [(etichetta, valore)] leggibili.

    Sostituisce la stampa del dict Python grezzo: vuoti e hash tecnici nascosti,
    testi lunghi troncati, liste/dict annidati resi compatti.
    """
    import json

    if not isinstance(value, dict):
        return []
    rows = []
    for key, raw in value.items():
        if key in KV_HIDDEN or raw in (None, "", [], {}):
            continue
        if isinstance(raw, (dict, list)):
            text = json.dumps(raw, ensure_ascii=False, default=str)
        elif isinstance(raw, bool):
            text = "sì" if raw else "no"
        else:
            text = _pretty_datetime(str(raw))
        if len(text) > 160:
            text = text[:157] + "…"
        label = KV_LABELS.get(key, key.replace("_", " ").capitalize())
        rows.append((label, ui_label(text) if key in {"status", "backup_status", "decision"} else text))
        if len(rows) >= int(limit):
            break
    return rows


ACTION_LABELS = {
    "alert_created": "Alert creato",
    "alert_reused": "Nuova occorrenza sullo stesso alert",
    "acknowledge": "Preso in carico",
    "acknowledged": "Preso in carico",
    "close": "Chiuso",
    "closed": "Chiuso",
    "false_positive": "Segnato falso positivo",
    "snooze": "Posticipato",
    "snoozed": "Posticipato",
    "reopen": "Riaperto",
    "reopened": "Riaperto",
    "backup_ticket_created": "Ticket backup creato",
    "ticket_created": "Ticket creato",
    "ticket_updated": "Ticket aggiornato",
}


@register.filter
def action_label(value):
    text = str(value or "")
    return ACTION_LABELS.get(text, text.replace("_", " ").capitalize())


METRIC_LABELS = {
    "backup_completed_count": "Backup completati",
    "backup_failed_count": "Backup falliti",
    "backup_warning_count": "Backup con avvisi",
    "backup_transferred_total_gb": "Dati trasferiti (GB)",
    "backup_duration_avg_seconds": "Durata media backup (s)",
    "backup_duration_max_seconds": "Durata massima backup (s)",
    "backup_devices_backed_up": "Dispositivi salvati",
    "backup_job": "Eventi job di backup",
    "vulnerability_finding": "Vulnerabilità rilevate",
    "vpn_auth_denied": "Accessi VPN negati",
    "vpn_auth_allowed": "Accessi VPN consentiti",
    "vpn_denied_count": "Accessi VPN negati",
    "source_silent": "Sorgenti silenziose",
    "possible_sender_spoofing": "Possibili spoofing mittente",
    "watchguard_report_summary": "Report WatchGuard ricevuti",
    "watchguard_alert_candidate": "Segnalazioni WatchGuard",
    "exposed_devices": "Dispositivi esposti",
    "cvss": "CVSS",
}


@register.filter
def metric_label(value):
    """Nome tecnico della metrica -> etichetta italiana (fallback: nome reso leggibile)."""
    text = str(value or "")
    if text in METRIC_LABELS:
        return METRIC_LABELS[text]
    human = text.replace("_", " ").strip()
    return human[:1].upper() + human[1:]
