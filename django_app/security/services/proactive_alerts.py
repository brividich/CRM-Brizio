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


# --- ISO 27001: presa in carico, riesami, azioni correttive, prove di ripristino -------------

EVENT_TRIAGE = "triage_overdue"
EVENT_RIESAME = "incident_review_missing"
EVENT_AZIONE = "corrective_action_due"
EVENT_RIPRISTINO = "restore_test_overdue"


def check_triage(now=None):
    """Alert attivi mai presi in carico oltre l'obiettivo della loro gravità: un avviso per alert."""
    if not soc_settings.value("iso.triage.attivo"):
        return 0
    from security.services import triage_tempi

    channels = _channels("iso.triage.canali")
    sent = 0
    for alert in triage_tempi.alert_oltre_tempo(now):
        t = alert.triage
        subject = f"[SOC] Alert senza presa in carico da {t['ore_oltre']} h oltre il tempo: {alert.title[:80]}"
        body = "\n".join([
            f"Alert      : #{alert.pk} - {alert.title}",
            f"Gravità    : {alert.severity} (presa in carico entro {t['target_ore']} h)",
            f"Creato il  : {timezone.localtime(alert.created_at):%d/%m/%Y %H:%M}",
            f"Sorgente   : {alert.source.name}",
            "",
            "Prendilo in carico dalla scheda dell'alert: la presa in carico ferma questo avviso.",
            _link(f"/soc/alerts/{alert.pk}/"),
        ])
        sent += _send(channels, event_kind=EVENT_TRIAGE, severity=Severity.HIGH if t["classe"] in {"critical", "high"} else Severity.WARNING,
                      dedup_hash=make_hash("triage", alert.pk), subject=subject, body=body)
    return sent


def check_riesami(now=None):
    """Incidenti risolti/chiusi senza Lezioni apprese oltre N giorni, e azioni correttive scadute o in scadenza."""
    if not soc_settings.value("iso.triage.attivo"):
        return 0
    from security.services import riesame

    channels = _channels("iso.triage.canali")
    sent = 0
    for incident in riesame.incidenti_senza_riesame(now, solo_da_avvisare=True):
        subject = f"[SOC] {incident.code}: riesame mancante (Lezioni apprese)"
        body = "\n".join([
            f"Incidente : {incident.code} - {incident.title}",
            f"Stato     : {incident.get_status_display()} dal {timezone.localtime(incident.resolved_at or incident.updated_at):%d/%m/%Y}",
            "",
            "Compila le Lezioni apprese nella scheda: causa, cosa ha funzionato, cosa migliorare, azioni correttive.",
            _link(f"/soc/incidenti/{incident.pk}/"),
        ])
        sent += _send(channels, event_kind=EVENT_RIESAME, severity=Severity.WARNING,
                      dedup_hash=make_hash("riesame", incident.pk, (incident.resolved_at or incident.updated_at).isoformat()),
                      subject=subject, body=body)
    oggi = timezone.localdate(now or timezone.now())
    for azione, fase in [(a, "scaduta") for a in riesame.azioni_scadute(oggi)] + [(a, "in_scadenza") for a in riesame.azioni_in_scadenza(oggi)]:
        incident = azione.incident
        subject = f"[SOC] Azione correttiva {'SCADUTA' if fase == 'scaduta' else 'in scadenza'}: {azione.titolo[:80]}"
        body = "\n".join([
            f"Incidente    : {incident.code} - {incident.title}",
            f"Azione       : {azione.titolo}",
            f"Responsabile : {azione.responsabile or '-'}",
            f"Scadenza     : {azione.scadenza:%d/%m/%Y}",
            "",
            "Segnala l'azione come fatta nella scheda dell'incidente.",
            _link(f"/soc/incidenti/{incident.pk}/"),
        ])
        sent += _send(channels, event_kind=EVENT_AZIONE, severity=Severity.WARNING if fase == "scaduta" else Severity.INFO,
                      dedup_hash=make_hash("azione", azione.pk, fase, azione.scadenza.isoformat()), subject=subject, body=body)
    return sent


def check_ripristini(now=None):
    """Prova di ripristino più vecchia della cadenza (o mai fatta): un avviso per scadenza."""
    if not soc_settings.value("iso.ripristini.attivo"):
        return 0
    from security.services import ripristini

    s = ripristini.stato(timezone.localdate(now or timezone.now()))
    if not s["in_ritardo"]:
        return 0
    ultima = s["ultima_riuscita"]
    subject = "[SOC] Prova di ripristino dei backup in ritardo"
    body = "\n".join([
        f"Ultima prova riuscita : {ultima.data:%d/%m/%Y} ({ultima.sistema})" if ultima else "Ultima prova riuscita : mai registrata",
        f"Cadenza attesa        : ogni {s['cadenza_giorni']} giorni",
        f"Ritardo               : {s['giorni_ritardo']} giorni" if ultima else "",
        "",
        "Esegui una prova di ripristino e registrala in Backup › Prove di ripristino.",
        _link("/soc/backup/ripristini/"),
    ])
    dedup = make_hash("ripristino", s["prossima_entro"].isoformat() if s["prossima_entro"] else "mai", s["cadenza_giorni"])
    return _send(_channels("iso.ripristini.canali"), event_kind=EVENT_RIPRISTINO, severity=Severity.WARNING,
                 dedup_hash=dedup, subject=subject, body=body)


def run_scheduled_notifications(now=None):
    """Passo del ciclo periodico: ogni controllo è isolato dagli altri."""
    result = {}
    for name, check in (("incidenti", check_incidents), ("backup", check_backups), ("report", check_report),
                        ("triage", check_triage), ("riesami", check_riesami), ("ripristini", check_ripristini)):
        try:
            result[name] = check(now)
        except Exception as exc:  # noqa: BLE001 - un controllo che fallisce non blocca gli altri
            logger.exception("Avvisi SOC: controllo %s fallito", name)
            result[name] = f"errore: {exc}"[:200]
    return result
