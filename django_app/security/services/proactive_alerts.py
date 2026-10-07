"""Avvisi programmati del SOC: scadenze degli incidenti, backup dei PC, report periodico.

Gira dentro ``security_cycle`` (ogni 15 minuti). Ogni avviso ha un ``dedup_hash`` che ne
descrive lo *stato* (es. «incidente 12, pre-notifica, scaduta»): parte una volta per
canale e riparte solo se lo stato cambia. Il registro è ``SecurityNotificationLog``, lo
stesso degli alert, quindi «chi è stato avvisato e quando» si legge in un solo posto.

Nessun contenuto sensibile: titoli, codici, date e link; mai corpi di mail o payload.
"""
from __future__ import annotations

import logging
from urllib.parse import quote
from datetime import timedelta

from django.utils import timezone

from security.models import SecurityNotificationChannel, Severity
from security.services import soc_settings
from security.services.dedup import make_hash
from security.services.notifications import _link, deliver_once

logger = logging.getLogger(__name__)

EVENT_INCIDENT = "incident_deadline"
EVENT_BACKUP = "backup_attention"
EVENT_REPORT = "periodic_report"


def _channels(key):
    ids = soc_settings.value(key)
    return list(SecurityNotificationChannel.objects.filter(pk__in=ids, enabled=True)) if ids else []


def _send(channels, *, event_kind, severity, dedup_hash, subject, body, attachment=None):
    sent = 0
    for channel in channels:
        log = deliver_once(channel, event_kind=event_kind, severity=severity, dedup_hash=dedup_hash,
                           subject=subject, body=body, attachment=attachment)
        sent += bool(log and log.outcome == "sent")
    return sent


# --- Scadenze incidenti ------------------------------------------------------------------

def incident_items(now=None):
    """Scadenze da avvisare adesso: scadute, o entro l'anticipo impostato."""
    from security.models import SecurityIncident
    from django.db.models import Q
    from security.services.incidents import deadlines

    now = now or timezone.now()
    lead = timedelta(hours=soc_settings.value("avvisi.incidenti.anticipo_ore"))
    items = []
    for incident in SecurityIncident.objects.filter(Q(is_significant=True) | Q(personal_data_breach=True)).order_by("detected_at"):
        for d in deadlines(incident, now):
            if d["done_at"]:
                continue
            if d["state"] == "overdue":
                phase = "overdue"
            elif d["due_at"] - now <= lead:
                phase = "soon"
            else:
                continue
            items.append({"incident": incident, "deadline": d, "phase": phase})
    return items


def check_incidents(now=None):
    if not soc_settings.value("avvisi.incidenti.attivo"):
        return 0
    channels = _channels("avvisi.incidenti.canali")
    sent = 0
    for item in incident_items(now):
        incident, d, overdue = item["incident"], item["deadline"], item["phase"] == "overdue"
        due = timezone.localtime(d["due_at"]).strftime("%d/%m/%Y %H:%M")
        subject = f"[SOC] {incident.code}: {d['label']} {'SCADUTA' if overdue else 'in scadenza'}"
        body = "\n".join([
            f"Incidente : {incident.code} - {incident.title}",
            f"Notifica  : {d['label']}",
            f"Scadenza  : {due} ({d['remaining_label']})",
            f"Stato     : {incident.get_status_display()}",
            "",
            "Registra l'invio nella scheda dell'incidente quando la notifica è partita.",
            _link(f"/soc/incidenti/{incident.pk}/"),
        ])
        sent += _send(channels, event_kind=EVENT_INCIDENT, severity=Severity.CRITICAL if overdue else Severity.HIGH,
                      dedup_hash=make_hash("incident", incident.pk, d["key"], item["phase"]), subject=subject, body=body)
    return sent


# --- Backup -------------------------------------------------------------------------------

def backup_items(now=None):
    """PC da segnalare: senza backup riuscito oltre la soglia, o con l'ultimo backup fallito."""
    from security.services.backup_center import FAIL, overview

    data = overview(30, now)
    include_failed = soc_settings.value("avvisi.backup.fallito")
    items = []
    for row in data["devices"]:
        if row["stale"]:
            items.append({"row": row, "reason": "stale"})
        elif include_failed and row["last_status"] == FAIL:
            items.append({"row": row, "reason": "failed"})
    return items


def check_backups(now=None):
    if not soc_settings.value("avvisi.backup.attivo"):
        return 0
    channels = _channels("avvisi.backup.canali")
    sent = 0
    for item in backup_items(now):
        row = item["row"]
        last_ok = timezone.localtime(row["last_ok"]).strftime("%d/%m/%Y %H:%M") if row["last_ok"] else "mai negli ultimi 30 giorni"
        if item["reason"] == "stale":
            subject = f"[SOC] Backup fermo: {row['name']}"
            first = f"Nessun backup riuscito da oltre {soc_settings.backup_stale_days()} giorni."
        else:
            subject = f"[SOC] Backup fallito: {row['name']}"
            first = "L'ultimo backup è fallito."
        body = "\n".join([
            first,
            f"Dispositivo     : {row['name']}",
            f"Ultimo esito    : {row['last_label']} ({timezone.localtime(row['last_at']):%d/%m/%Y %H:%M})",
            f"Ultimo riuscito : {last_ok}",
            f"Job             : {', '.join(row['jobs'])}",
            "",
            _link("/soc/pc/?nome=" + quote(row["name"])),
        ])
        # Lo stato include l'ultimo riuscito: dopo un nuovo backup riuscito l'avviso può ripartire.
        dedup = make_hash("backup", row["name"].casefold(), item["reason"], row["last_ok"].isoformat() if row["last_ok"] else "", row["last_at"].isoformat() if item["reason"] == "failed" else "")
        sent += _send(channels, event_kind=EVENT_BACKUP, severity=Severity.HIGH, dedup_hash=dedup, subject=subject, body=body)
    return sent


# --- Report periodico ---------------------------------------------------------------------

def report_due(now=None):
    """``(inizio, fine, etichetta)`` del report da mandare oggi, o None."""
    from security.services.periodic_report import resolve_period

    today = timezone.localdate(now or timezone.now())
    frequency = soc_settings.value("report.auto.frequenza")
    if frequency == "monthly" and today.day == 1:
        return resolve_period("last_month", today=today)
    if frequency == "weekly" and today.weekday() == 0:
        return resolve_period("last_week", today=today)
    return None


def check_report(now=None):
    if not soc_settings.value("report.auto.attivo"):
        return 0
    now = now or timezone.now()
    # Dalle 7 in poi: il report del lunedì arriva a inizio giornata, non a mezzanotte.
    if timezone.localtime(now).hour < 7:
        return 0
    period = report_due(now)
    if not period:
        return 0
    from security.services.periodic_report import build_report
    from security.services.soc_pdf import render_period_report_pdf

    start, end, label = period
    report = build_report(start, end, label, now=now)
    a, b, inc = report["alerts"], report["backup"], report["incidents"]
    rate = f"{b['success_rate']}%".replace(".", ",") if b["success_rate"] is not None else "nessun job"
    body = "\n".join([
        f"Report Security Center - {label}",
        "",
        f"Alert creati      : {a['created']} (ancora aperti: {a['open_now']})",
        f"Backup riusciti   : {rate} ({b['failed']} falliti su {b['total']})",
        f"CVE aperte        : {report['vulnerabilities']['open_now']}",
        f"Incidenti         : {inc['total']} (significativi NIS2: {inc['significant']})",
        "",
        "Il PDF completo è allegato alla mail.",
        _link(f"/soc/report/?period=custom&from={start:%Y-%m-%d}&to={end:%Y-%m-%d}"),
    ])
    pdf = (f"report-soc-{start:%Y%m%d}-{end:%Y%m%d}.pdf", render_period_report_pdf(report), "application/pdf")
    return _send(_channels("report.auto.canali"), event_kind=EVENT_REPORT, severity=Severity.INFO,
                 dedup_hash=make_hash("report", start.isoformat(), end.isoformat()),
                 subject=f"[SOC] Report {label}", body=body, attachment=pdf)


def run_scheduled_notifications(now=None):
    """Passo del ciclo periodico: ogni controllo è isolato dagli altri."""
    result = {}
    for name, check in (("incidenti", check_incidents), ("backup", check_backups), ("report", check_report)):
        try:
            result[name] = check(now)
        except Exception as exc:  # noqa: BLE001 - un controllo che fallisce non blocca gli altri
            logger.exception("Avvisi SOC: controllo %s fallito", name)
            result[name] = f"errore: {exc}"[:200]
    return result
