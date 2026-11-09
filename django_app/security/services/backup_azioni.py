"""Azioni della pagina Backup su job e PC selezionati: alert aperti, presa in carico, chiusura, ticket.

Gli alert di backup nascono per job (``event_type = backup_job``, ``payload.job_name``): gli alert
di un PC sono quelli dei job che lo hanno protetto nel periodo. Un job condiviso (es. Veeam con
più server) ha un alert solo, che vale per tutti i suoi dispositivi.
"""
import uuid
from datetime import timedelta

from django.utils import timezone

from security.models import BackupJobRecord, SecurityAlert, Severity, Status
from security.services import backup_center as svc
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.alert_simili import ESITI

MAX_ITEMS = 100


def _job_of(alert):
    return str(((alert.event.payload if alert.event_id else None) or {}).get("job_name") or "").strip()


def alert_aperti(jobs):
    """Alert di backup ancora aperti dei job indicati, dal più recente."""
    keys = {str(j).strip().casefold() for j in jobs if str(j).strip()}
    if not keys:
        return []
    qs = (
        SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type="backup_job")
        .select_related("event", "source").order_by("-created_at")
    )
    return [a for a in qs if _job_of(a).casefold() in keys]


def jobs_dei_pc(names, days=90):
    """Job che hanno protetto i PC indicati negli ultimi ``days`` giorni."""
    keys = {str(n).strip().casefold() for n in names if str(n).strip()}
    jobs = set()
    if not keys:
        return jobs
    for record in svc._records(timezone.now() - timedelta(days=days)):
        if any(run["device"].casefold() in keys for run in svc.device_runs(record)):
            jobs.add(record.job_name)
    return jobs


def prendi_in_carico(alerts, user):
    from security.services.alert_lifecycle import acknowledge_alert
    from security.services.cases import actor_name

    actor = actor_name(user)
    fatti = 0
    for alert in alerts:
        if alert.status in (Status.NEW, Status.OPEN):
            acknowledge_alert(alert, actor=actor, reason="Presa in carico dalla pagina Backup")
            fatti += 1
    return fatti


def chiudi(alerts, *, esito, motivo, user):
    """Chiude gli alert a nome della persona; i ticket di backup rimasti senza alert aperti si risolvono.

    Un'azione conta una volta sola per la soppressione appresa (stesso ``batch``).
    """
    from security.services.alert_gruppi import _chiudi_uno

    if esito not in dict(ESITI):
        raise ValueError("esito non valido")
    if not motivo:
        raise ValueError("motivo obbligatorio")
    actor = getattr(user, "username", "") or "ui"
    batch = f"backup-{uuid.uuid4().hex[:20]}"
    fatti = 0
    for alert in alerts:
        if alert.status in ACTIVE_ALERT_STATUSES:
            _chiudi_uno(alert, esito, actor, motivo, batch, user)
            fatti += 1
    return fatti


def apri_ticket(*, jobs=(), devices=(), user, title=""):
    """Un ticket con un'attività per job o PC selezionato; gli alert aperti di quei job entrano nel ticket.

    Ritorna il ticket, o None se non c'è nessun report di backup a cui collegarlo.
    """
    from security.services.cases import add_alerts_to_case, open_manual_case

    jobs, devices = list(jobs)[:MAX_ITEMS], list(devices)[:MAX_ITEMS]
    last = BackupJobRecord.objects.select_related("source").order_by("-created_at").first()
    if last is None:
        return None
    if devices:
        cosa, nomi = "PC", devices
        tasks = [f"Verificare e ripristinare il backup di {n}" for n in devices]
        alerts = alert_aperti(jobs_dei_pc(devices))
    else:
        cosa, nomi = "job", jobs
        tasks = [f"Verificare e sistemare il job «{n}»" for n in jobs]
        alerts = alert_aperti(jobs)
    title = title.strip() or (f"Backup da sistemare: {nomi[0]}" if len(nomi) == 1 else f"Backup da sistemare su {len(nomi)} {cosa}")
    case = open_manual_case(
        source=last.source, title=title, user=user, assignee=user, severity=Severity.WARNING,
        description=f"{cosa} selezionati dalla pagina Backup: " + ", ".join(nomi), tasks=tasks,
    )
    if alerts:
        add_alerts_to_case(case, alerts, user=user)
    return case


def job_detail(name, days=30, now=None):
    """Dati del pannello laterale di un job: esecuzioni, dispositivi, alert aperti e ticket."""
    now = now or timezone.now()
    data = svc.overview(days, now=now)
    row = next((j for j in data["jobs"] if j["name"] == name), None)
    if row is None:
        return None
    runs = sorted(
        (r for r in svc._records(now - timedelta(days=days)) if r.job_name == name), key=svc.when,
    )
    strip = [{"tone": svc.STATUS_TONES.get(r.status, "muted"), "label": svc.STATUS_LABELS.get(r.status, r.status), "at": svc.when(r)}
             for r in runs[-svc.STRIP_RUNS:]]
    devices = sorted({run["device"] for r in runs for run in svc.device_runs(r)}, key=str.casefold)
    alerts = alert_aperti([name])
    tickets = []
    for alert in alerts:
        for case in list(alert.linked_remediation_tickets.all()) + list(alert.tickets.all()):
            if case not in tickets:
                tickets.append(case)
    return {**row, "strip": strip, "devices_list": devices, "alerts": alerts, "tickets": tickets[:5], "days": days}
