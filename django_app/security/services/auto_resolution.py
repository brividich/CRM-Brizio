"""Risoluzione automatica: quando l'anomalia rientra, l'alert che aveva generato si chiude.

Un alert nasce da un errore (backup fallito, sorgente silenziosa, CVE esposta). Se un
report *successivo* dimostra che il problema non c'è più, tenerlo aperto è solo rumore:
lo si chiude come «Risolto», con il motivo e il riferimento al report che lo prova.

Le regole sono voci di un **registro** (``REGISTRY``): ognuna dichiara la condizione,
la prova richiesta e l'azione, ha un interruttore (``autoresolve.<codice>.attivo``) e si
può **simulare** sugli ultimi 30 giorni prima di accenderla (``simulate``). Tutte sono
conservative: nel dubbio l'alert resta aperto.

- **backup_job**: un'esecuzione *completata* dello stesso job sullo stesso dispositivo,
  successiva all'ultimo fallimento, chiude gli alert di quel job.
- **vulnerability_finding**: lo stesso finding (stessa CVE, prodotto, organizzazione)
  riletto con 0 dispositivi esposti chiude l'alert. L'assenza dal report NON basta:
  un export parziale non è una prova di rientro.
- **source_silent**: la sorgente torna in regola (report e lettura nei tempi) e
  l'alert di silenzio si chiude. È anche la regola «heartbeat della sorgente OK».
- **vpn_within_limits** (nuova, spenta di default): l'utente o l'IP di un alert VPN
  (riconnessioni brevi, accessi negati) resta sotto soglia per N giorni consecutivi *con
  dati VPN arrivati ogni giorno* (il silenzio non è un rientro).
- **cve_patched_inventory** (nuova, spenta di default): l'inventario software recente
  mostra il prodotto solo in versioni fuori dal range vulnerabile su tutti gli host e
  nessun host impattato o da verificare. Mai per CVE in CISA KEV o critiche.

Gli altri alert (spoofing, dati illeggibili, sessioni lunghe) restano a gestione manuale.
Un caso (ticket) i cui alert sono tutti chiusi e senza attività aperte si chiude a sua
volta; se ha attività ancora da fare resta aperto, con una voce in timeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable

from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityRemediationTicket,
    SecurityVpnAccess,
    Status,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.configuration import get_setting, set_setting

logger = logging.getLogger(__name__)

AUTO_ACTOR = "system"
SIMULATION_DAYS = 30
SIMULATION_VALID_DAYS = 7


@dataclass(frozen=True)
class Candidate:
    """Un alert che la regola chiuderebbe, con il motivo e la prova."""

    alert: SecurityAlert
    reason: str
    evidence_event: object = None
    evidence_ref: str = ""


@dataclass(frozen=True)
class RecoveryRule:
    code: str
    label: str
    signal: str
    condition: str
    proof: str
    action: str
    default_enabled: bool
    trigger: str  # "event" (chiamata dal motore regole) | "periodic" (ciclo SOC)
    simulate_fn: Callable


def auto_resolve_enabled() -> bool:
    value = get_setting("SECURITY_AUTO_RESOLVE_ENABLED", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _setting_key(code):
    return f"autoresolve.{code}.attivo"


def rule_enabled(code) -> bool:
    rule = REGISTRY[code]
    if not auto_resolve_enabled():
        return False
    value = get_setting(_setting_key(code), rule.default_enabled)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def last_simulation(code):
    value = get_setting(f"autoresolve.{code}.simulata_il", "")
    if not value:
        return None
    from django.utils.dateparse import parse_datetime

    return parse_datetime(str(value))


def set_rule_enabled(code, enabled, actor=None):
    """Accende/spegne una regola. Accendere richiede una simulazione recente (ultimi 7 giorni)."""
    if enabled:
        simulated = last_simulation(code)
        if not simulated or simulated < timezone.now() - timedelta(days=SIMULATION_VALID_DAYS):
            raise ValueError("Prima di accendere la regola esegui la simulazione sugli ultimi 30 giorni.")
    set_setting(_setting_key(code), bool(enabled), actor=actor, category="automatismi",
                description=f"Risoluzione automatica: {REGISTRY[code].label}")


def _norm(value):
    return str(value or "").strip().lower()


# --- Azione comune --------------------------------------------------------------------------

def resolve_alert(alert, reason, evidence_event=None, evidence_ref="", rule_code=""):
    """Chiude ``alert`` come Risolto dal sistema e propaga ai casi collegati."""
    now = timezone.now()
    old_status = alert.status
    alert.status = Status.RESOLVED
    alert.status_reason = reason
    alert.closed_at = now
    alert.snoozed_until = None
    alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
    details = {"old_status": old_status, "new_status": Status.RESOLVED, "reason": reason, "actor": AUTO_ACTOR}
    if rule_code:
        details["rule"] = rule_code
    if evidence_event is not None:
        details["evidence_event_id"] = evidence_event.pk
        details["evidence_occurred_at"] = evidence_event.occurred_at.isoformat() if evidence_event.occurred_at else None
    if evidence_ref:
        details["evidence"] = evidence_ref
    SecurityAlertActionLog.objects.create(alert=alert, action="auto_resolved", actor=AUTO_ACTOR, details=details)
    for case in _cases_of(alert):
        maybe_resolve_case(case)
    return alert


def _apply(code, candidates):
    for candidate in candidates:
        resolve_alert(candidate.alert, candidate.reason, evidence_event=candidate.evidence_event,
                      evidence_ref=candidate.evidence_ref, rule_code=code)
    return len(candidates)


def _cases_of(alert):
    from security.services.cases import ACTIVE_CASE_STATUSES

    return (
        SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES)
        .filter(pk__in=list(alert.tickets.values_list("pk", flat=True)) + list(alert.linked_remediation_tickets.values_list("pk", flat=True)))
        .distinct()
    )


def maybe_resolve_case(case):
    """Chiude il caso se tutti i suoi alert sono chiusi e non ha attività aperte."""
    from security.services.cases import ACTIVE_CASE_STATUSES, case_alerts

    if case.status not in ACTIVE_CASE_STATUSES:
        return False
    alerts = case_alerts(case)
    if not alerts or any(alert.status in ACTIVE_ALERT_STATUSES for alert in alerts):
        return False
    open_tasks = case.tasks.filter(done=False).count()
    if open_tasks:
        SecurityAlertActionLog.objects.create(
            ticket=case, action="case_alerts_all_resolved", actor=AUTO_ACTOR,
            details={"reason": "Tutti gli alert sono rientrati, ma restano attività da completare.", "open_tasks": open_tasks},
        )
        return False
    old_status = case.status
    case.status = Status.RESOLVED
    case.closed_at = timezone.now()
    case.resolution = case.resolution or "Risolto automaticamente: tutti gli alert collegati sono rientrati."
    case.save(update_fields=["status", "closed_at", "resolution", "updated_at"])
    SecurityAlertActionLog.objects.create(
        ticket=case, action="case_auto_resolved", actor=AUTO_ACTOR,
        details={"old_status": old_status, "new_status": Status.RESOLVED, "reason": case.resolution},
    )
    return True


def _active_alerts_for(source, event_type):
    return (
        SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=event_type)
        .select_related("event")
    )


def _alerts_open_at(source, event_type, moment):
    """Per la simulazione: alert dello stesso tipo nati prima di ``moment`` e ancora aperti in quel momento."""
    from django.db.models import Q

    return (
        SecurityAlert.objects.filter(source=source, event__event_type=event_type, created_at__lte=moment)
        .filter(Q(closed_at__isnull=True) | Q(closed_at__gt=moment))
        .select_related("event")
    )


# --- backup_job ------------------------------------------------------------------------------

def _backup_candidates(event, alerts):
    payload = event.payload or {}
    job, device = _norm(payload.get("job_name")), _norm(payload.get("device_name"))
    if not job:
        return []
    out = []
    for alert in alerts:
        failure = alert.event
        failure_payload = failure.payload or {}
        if _norm(failure_payload.get("job_name")) != job or _norm(failure_payload.get("device_name")) != device:
            continue
        # Solo un'esecuzione riuscita DOPO il fallimento prova il rientro: i report
        # possono arrivare fuori ordine.
        if failure.occurred_at and event.occurred_at and event.occurred_at <= failure.occurred_at:
            continue
        when = timezone.localtime(event.occurred_at).strftime("%d/%m/%Y %H:%M") if event.occurred_at else "-"
        out.append(Candidate(alert, f"Backup «{payload.get('job_name')}» completato correttamente il {when}.", event))
    return out


def resolve_backup_recovered(event):
    """Un backup completato chiude gli alert dei fallimenti precedenti dello stesso job."""
    if not rule_enabled("backup_job"):
        return 0
    return _apply("backup_job", _backup_candidates(event, _active_alerts_for(event.source, "backup_job")))


def _simulate_backup(since):
    from security.models import SecurityEventRecord

    found = {}
    for event in SecurityEventRecord.objects.filter(event_type="backup_job", occurred_at__gte=since).order_by("occurred_at"):
        if _norm((event.payload or {}).get("status")) != "completed":
            continue
        for candidate in _backup_candidates(event, _alerts_open_at(event.source, "backup_job", event.occurred_at)):
            found.setdefault(candidate.alert.pk, candidate)
    return list(found.values())


# --- vulnerability_finding -------------------------------------------------------------------

def _vulnerability_candidates(event, alerts):
    payload = event.payload or {}
    if payload.get("cvss_unparsed") or payload.get("exposed_devices") in (None, ""):
        return []
    try:
        exposed = int(payload.get("exposed_devices"))
    except (TypeError, ValueError):
        return []
    if exposed > 0:
        return []
    out = []
    for alert in alerts.filter(dedup_hash=event.dedup_hash):
        if alert.event and alert.event.occurred_at and event.occurred_at and event.occurred_at <= alert.event.occurred_at:
            continue
        out.append(Candidate(
            alert,
            f"{payload.get('cve') or 'CVE'} su {payload.get('affected_product') or 'prodotto'}: nessun dispositivo più esposto nel report successivo.",
            event,
        ))
    return out


def resolve_vulnerability_cleared(event):
    """Lo stesso finding riletto con 0 dispositivi esposti chiude l'alert della CVE."""
    if not rule_enabled("vulnerability_finding"):
        return 0
    return _apply("vulnerability_finding", _vulnerability_candidates(event, _active_alerts_for(event.source, "vulnerability_finding")))


def _simulate_vulnerability(since):
    from security.models import SecurityEventRecord

    found = {}
    for event in SecurityEventRecord.objects.filter(event_type="vulnerability_finding", occurred_at__gte=since).order_by("occurred_at"):
        for candidate in _vulnerability_candidates(event, _alerts_open_at(event.source, "vulnerability_finding", event.occurred_at)):
            found.setdefault(candidate.alert.pk, candidate)
    return list(found.values())


# --- source_silent ---------------------------------------------------------------------------

def _source_candidates(alerts, mailbox_code):
    return [
        Candidate(alert, "La sorgente ha ripreso a inviare report nei tempi attesi.")
        for alert in alerts
        if _norm((alert.event.payload or {}).get("source_code")) == _norm(mailbox_code)
    ]


def resolve_source_back_online(security_source, mailbox_code):
    """La sorgente è tornata in regola: chiude i suoi alert di silenzio."""
    if security_source is None or not rule_enabled("source_silent"):
        return 0
    return _apply("source_silent", _source_candidates(_active_alerts_for(security_source, "source_silent"), mailbox_code))


def _simulate_source(since):
    """Alert di silenzio seguiti da un report della stessa sorgente (prova del rientro)."""
    from security.models import SecurityReport

    out = []
    alerts = SecurityAlert.objects.filter(event__event_type="source_silent", created_at__gte=since).select_related("event", "source")
    for alert in alerts:
        report = SecurityReport.objects.filter(source=alert.source, created_at__gt=alert.created_at).order_by("created_at").first()
        if report and (alert.closed_at is None or alert.closed_at > report.created_at):
            out.append(Candidate(alert, "La sorgente ha ripreso a inviare report nei tempi attesi.",
                                 evidence_ref=f"report #{report.pk} del {timezone.localtime(report.created_at):%d/%m/%Y %H:%M}"))
    return out


# --- vpn_within_limits -----------------------------------------------------------------------

VPN_TYPES = {"watchguard_vpn_many_short_reconnects", "watchguard_vpn_repeated_denied"}


def vpn_days():
    try:
        return max(1, min(30, int(get_setting("autoresolve.vpn_within_limits.giorni", 7))))
    except (TypeError, ValueError):
        return 7


def _vpn_day_ok(alert_payload, source, day):
    """(dati presenti quel giorno, sotto soglia) per l'utente/IP dell'alert."""
    from security.parsers.watchguard.config import (
        VPN_DENIED_THRESHOLD_PER_IP,
        VPN_MANY_SHORT_RECONNECTS_THRESHOLD,
        VPN_SHORT_SESSION_SECONDS,
    )

    day_qs = SecurityVpnAccess.objects.filter(source=source, login_at__date=day)
    if not day_qs.exists():
        return False, False
    user, ip = alert_payload.get("user") or "", alert_payload.get("source_ip") or ""
    subject = day_qs.filter(username__iexact=user) if user else day_qs.filter(source_ip=ip)
    if alert_payload.get("type") == "watchguard_vpn_repeated_denied":
        count = subject.filter(action=SecurityVpnAccess.ACTION_DENIED).count()
        return True, count < VPN_DENIED_THRESHOLD_PER_IP
    count = subject.filter(action=SecurityVpnAccess.ACTION_ALLOWED, duration_seconds__gt=0,
                           duration_seconds__lte=VPN_SHORT_SESSION_SECONDS).count()
    return True, count < VPN_MANY_SHORT_RECONNECTS_THRESHOLD


def _vpn_candidate(alert, today, days=None):
    payload = (alert.event.payload or {}) if alert.event else {}
    if payload.get("type") not in VPN_TYPES or not (payload.get("user") or payload.get("source_ip")):
        return None
    days = days or vpn_days()
    alert_day = timezone.localtime(alert.event.occurred_at).date() if alert.event.occurred_at else None
    window = [today - timedelta(days=offset) for offset in range(1, days + 1)]
    if alert_day is None or min(window) <= alert_day:
        return None  # servono N giorni interi DOPO l'evento
    for day in window:
        has_data, ok = _vpn_day_ok(payload, alert.source, day)
        if not has_data or not ok:
            return None
    who = payload.get("user") or payload.get("source_ip")
    return Candidate(alert, f"VPN di {who} nei limiti per {days} giorni consecutivi (dal {min(window):%d/%m} al {max(window):%d/%m}), "
                            "con dati VPN arrivati ogni giorno.",
                     evidence_ref=f"storico accessi VPN {min(window):%d/%m/%Y}–{max(window):%d/%m/%Y}")


def run_vpn_within_limits(today=None):
    if not rule_enabled("vpn_within_limits"):
        return 0
    today = today or timezone.localdate()
    alerts = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type="watchguard_alert_candidate").select_related("event", "source")
    days = vpn_days()
    return _apply("vpn_within_limits", [c for c in (_vpn_candidate(a, today, days) for a in alerts) if c])


def _simulate_vpn(since):
    found = {}
    today = timezone.localdate()
    days = vpn_days()
    alerts = [
        a for a in SecurityAlert.objects.filter(event__event_type="watchguard_alert_candidate", created_at__gte=since - timedelta(days=days))
        .select_related("event", "source")
        if ((a.event.payload or {}) if a.event else {}).get("type") in VPN_TYPES
    ]
    for offset in range(0, SIMULATION_DAYS + 1, 1):
        day = today - timedelta(days=offset)
        moment = timezone.make_aware(datetime.combine(day, time.min))
        for alert in alerts:
            if alert.pk in found or alert.created_at > moment or (alert.closed_at and alert.closed_at <= moment):
                continue
            candidate = _vpn_candidate(alert, day, days)
            if candidate:
                found[alert.pk] = candidate
    return list(found.values())


# --- cve_patched_inventory -------------------------------------------------------------------

def _cve_candidate(alert, cache=None):
    from security.models import SecurityCveRecord, SoftwareInventoryImport
    from security.services.cve_impact import summary

    payload = (alert.event.payload or {}) if alert.event else {}
    cve_id = str(payload.get("cve") or "").strip().upper()
    if not cve_id or alert.severity == "critical":
        return None
    cache = {} if cache is None else cache
    if cve_id not in cache:
        record = SecurityCveRecord.objects.filter(cve_id=cve_id).first()
        cache[cve_id] = (record, summary(record) if record else None)
    record, info = cache[cve_id]
    if record is None or record.kev or not info:
        return None
    proposable, _why = info["closure"]
    if not proposable or info["not_impacted"] == 0:
        return None  # serve la prova positiva: il prodotto c'è, in versioni non vulnerabili
    last_import = SoftwareInventoryImport.objects.filter(status=SoftwareInventoryImport.STATUS_IMPORTED).order_by("-imported_at").first()
    if not record.impact_computed_at or (last_import and last_import.imported_at and record.impact_computed_at < last_import.imported_at):
        return None  # impatti calcolati prima dell'ultimo inventario: non sono una prova
    try:
        exposed = int(payload.get("exposed_devices") or 0)
    except (TypeError, ValueError):
        return None
    if exposed > info["not_impacted"]:
        return None  # Defender vede più dispositivi esposti di quanti l'inventario ne copra
    return Candidate(
        alert,
        f"{cve_id}: inventario software del {info['inventory_date']:%d/%m/%Y} con {info['not_impacted']} host in versioni non vulnerabili "
        "e nessun host impattato o da verificare.",
        evidence_ref=f"impatto CVE calcolato il {timezone.localtime(record.impact_computed_at):%d/%m/%Y %H:%M}" if record.impact_computed_at else "",
    )


def run_cve_patched_inventory():
    if not rule_enabled("cve_patched_inventory"):
        return 0
    alerts = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type="vulnerability_finding").select_related("event")
    cache = {}
    return _apply("cve_patched_inventory", [c for c in (_cve_candidate(a, cache) for a in alerts) if c])


def _simulate_cve(since):
    # L'inventario non ha storico di versioni per giorno: la simulazione guarda gli alert CVE
    # degli ultimi 30 giorni ancora aperti, con l'inventario e gli impatti di oggi.
    alerts = SecurityAlert.objects.filter(event__event_type="vulnerability_finding", created_at__gte=since,
                                          status__in=ACTIVE_ALERT_STATUSES).select_related("event")
    cache = {}
    return [c for c in (_cve_candidate(a, cache) for a in alerts) if c]


# --- Registro --------------------------------------------------------------------------------

REGISTRY = {
    rule.code: rule
    for rule in (
        RecoveryRule("backup_job", "Backup tornato a buon fine", "Alert «backup fallito»",
                     "Stesso job e stesso dispositivo dell'alert",
                     "Un'esecuzione completata successiva al fallimento (report di backup)",
                     "Chiude l'alert come Risolto con il riferimento all'esecuzione", True, "event", _simulate_backup),
        RecoveryRule("vulnerability_finding", "CVE senza più dispositivi esposti", "Alert CVE critica esposta (Defender)",
                     "Stesso finding: CVE, prodotto, organizzazione",
                     "Report successivo con 0 dispositivi esposti (l'assenza dal report non basta)",
                     "Chiude l'alert come Risolto con il riferimento al report", True, "event", _simulate_vulnerability),
        RecoveryRule("source_silent", "Sorgente di nuovo regolare (heartbeat OK)", "Alert «sorgente silenziosa»",
                     "Stessa sorgente/casella dell'alert",
                     "Report e lettura della casella di nuovo nei tempi attesi",
                     "Chiude l'alert come Risolto", True, "event", _simulate_source),
        RecoveryRule("vpn_within_limits", "VPN tornata nei limiti", "Alert VPN (riconnessioni brevi, accessi negati)",
                     "Stesso utente o IP dell'alert, N giorni interi dopo l'evento (impostazione, default 7)",
                     "Storico accessi VPN: dati presenti ogni giorno e conteggi sotto soglia ogni giorno",
                     "Chiude l'alert come Risolto con il periodo controllato", False, "periodic", _simulate_vpn),
        RecoveryRule("cve_patched_inventory", "CVE con patch installata (inventario)", "Alert CVE non critica",
                     "CVE non in CISA KEV, non critica; inventario software recente",
                     "Impatto CVE: prodotto presente solo in versioni fuori range, nessun host impattato o da verificare",
                     "Chiude l'alert come Risolto con la data dell'inventario", False, "periodic", _simulate_cve),
    )
}


def run_periodic_recoveries():
    """Regole periodiche (ciclo SOC): ognuna isolata, un errore non blocca le altre."""
    result = {}
    for code, runner in (("vpn_within_limits", run_vpn_within_limits), ("cve_patched_inventory", run_cve_patched_inventory)):
        try:
            result[code] = runner()
        except Exception as exc:  # noqa: BLE001 - una regola difettosa non deve fermare il ciclo
            logger.exception("Regola di rientro %s fallita", code)
            result[code] = f"errore: {exc}"[:200]
    return result


def simulate(code, days=SIMULATION_DAYS, actor=None, max_examples=20):
    """Cosa avrebbe chiuso la regola negli ultimi ``days`` giorni. Sola lettura: non chiude nulla."""
    rule = REGISTRY[code]
    since = timezone.now() - timedelta(days=days)
    candidates = rule.simulate_fn(since)
    set_setting(f"autoresolve.{code}.simulata_il", timezone.now().isoformat(), actor=actor, category="automatismi",
                description=f"Ultima simulazione: {rule.label}")
    return {
        "code": code,
        "days": days,
        "would_close": len(candidates),
        "already_closed_by_people": sum(1 for c in candidates if c.alert.status not in ACTIVE_ALERT_STATUSES and c.alert.status != Status.RESOLVED),
        "examples": [
            {"alert_id": c.alert.pk, "title": c.alert.title, "status": c.alert.status, "reason": c.reason,
             "evidence": c.evidence_ref or (f"evento #{c.evidence_event.pk}" if c.evidence_event is not None else "")}
            for c in candidates[:max_examples]
        ],
    }


def registry_rows():
    return [
        {"rule": rule, "enabled": rule_enabled(code), "simulated_at": last_simulation(code)}
        for code, rule in REGISTRY.items()
    ]
