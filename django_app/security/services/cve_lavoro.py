"""Dalla CVE all'azione: un caso con un'attività per PC, che si spunta e si chiude da solo con l'inventario.

Il caso è quello normale del SOC (``SecurityRemediationTicket``). Le attività con ``cve_host`` seguono
l'inventario a ogni ricalcolo degli impatti: PC non più esposto = fatta, PC di nuovo esposto = riaperta,
PC nuovo = attività nuova. Quando nessun PC è più esposto il caso si chiude, a meno che qualcuno abbia
aggiunto attività a mano ancora da fare.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from security.models import SecurityAlertActionLog, SecurityCaseTask, SecurityCveImpact, SecurityRemediationTicket, Status
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)
ATTIVI = (Status.NEW, Status.OPEN, Status.IN_PROGRESS)
ATTORE = "system:cve"


def _dedup(source, record):
    return make_hash(source.pk, "cve_lavoro", record.cve_id.upper())


def lavoro_aperto(record):
    return SecurityRemediationTicket.objects.filter(cve=record.cve_id, status__in=ATTIVI, origin=SecurityRemediationTicket.ORIGIN_MANUAL).first()


def _esposti(record):
    """{host: impatto} dei PC che la CVE colpisce oggi."""
    return {i.host: i for i in record.impacts.filter(outcome=SecurityCveImpact.IMPACTS).select_related("installation")}


def _titolo_attivita(impatto):
    inst = impatto.installation
    pc = (inst.host_display if inst and inst.host_display else impatto.host)
    programma = f"{inst.product_raw or inst.product} {inst.version_raw}".strip() if inst else ""
    return f"{pc}: aggiornare {programma}"[:255] if programma else pc[:255]


def apri_lavoro(record, user):
    """Il caso della CVE, con un'attività per PC colpito. Se c'è già un lavoro aperto ritorna quello."""
    from security.services.cve_chiusura import alert_attivo
    from security.services.cve_impact import impact_source
    from security.services.cve_pannello import correzione

    esistente = lavoro_aperto(record)
    if esistente:
        return esistente
    esposti = _esposti(record)
    if not esposti:
        raise ValueError("Nessun PC è colpito da questa CVE.")
    source = impact_source()
    alert = alert_attivo(record)
    cosa = correzione(record)
    descrizione = "\n".join(riga for riga in (
        record.description[:1500] if record.description else "",
        (cosa[:1].upper() + cosa[1:] + ".") if cosa else "Versione corretta non indicata da NVD: controllare l'avviso del produttore.",
        "Le attività dei PC si spuntano da sole quando l'inventario vede la versione corretta o il programma rimosso.",
    ) if riga)
    try:
        with transaction.atomic():
            caso = SecurityRemediationTicket.objects.create(
                source=source, alert=alert, cve=record.cve_id, cve_ids=[record.cve_id],
                title=f"Correggere {record.cve_id} su {len(esposti)} PC"[:255], description=descrizione,
                status=Status.IN_PROGRESS, severity=(alert.severity if alert else (record.severity or "warning").lower()),
                max_cvss=record.cvss or 0, max_exposed_devices=len(esposti), dedup_hash=_dedup(source, record),
                origin=SecurityRemediationTicket.ORIGIN_MANUAL, created_by=user if getattr(user, "pk", None) else None,
                assignee=user if getattr(user, "pk", None) else None,
            )
            if alert:
                caso.linked_alerts.add(alert)
            SecurityCaseTask.objects.bulk_create([
                SecurityCaseTask(ticket=caso, title=_titolo_attivita(imp), cve_host=host[:255], created_by=caso.created_by)
                for host, imp in sorted(esposti.items())
            ], batch_size=100)
            SecurityAlertActionLog.objects.create(ticket=caso, action="cve_lavoro_aperto", actor=getattr(user, "username", "") or "ui",
                                                  details={"cve": record.cve_id, "pc": len(esposti)})
    except IntegrityError:
        # Due clic insieme: il vincolo sul caso attivo ne lascia uno solo.
        return SecurityRemediationTicket.objects.filter(source=source, dedup_hash=_dedup(source, record), status__in=ATTIVI).first()
    return caso


def aggiorna(record):
    """Allinea il lavoro aperto della CVE all'ultimo ricalcolo. Ritorna ``True`` se il caso si è chiuso."""
    caso = lavoro_aperto(record)
    if caso is None:
        return False
    esposti = _esposti(record)
    adesso = timezone.now()
    fatte, riaperte, nuove = [], [], []
    attivita = {t.cve_host: t for t in caso.tasks.exclude(cve_host="")}
    for host, task in attivita.items():
        if host not in esposti and not task.done:
            task.done, task.done_at, task.done_by = True, adesso, None
            task.save(update_fields=["done", "done_at", "done_by"])
            fatte.append(host)
        elif host in esposti and task.done:
            task.done, task.done_at, task.done_by = False, None, None
            task.save(update_fields=["done", "done_at", "done_by"])
            riaperte.append(host)
    for host, imp in esposti.items():
        if host not in attivita:
            SecurityCaseTask.objects.create(ticket=caso, title=_titolo_attivita(imp), cve_host=host[:255])
            nuove.append(host)
    if fatte or riaperte or nuove:
        SecurityAlertActionLog.objects.create(ticket=caso, action="cve_lavoro_aggiornato", actor=ATTORE,
                                              details={"fatti": fatte, "riaperti": riaperte, "nuovi": nuove})
    if esposti or caso.tasks.filter(done=False).exists():
        return False
    return _chiudi(caso)


def _chiudi(caso):
    from security.services import traccia

    vecchio = caso.status
    caso.status = Status.RESOLVED
    caso.closed_at = timezone.now()
    caso.resolution = caso.resolution or "Risolto da solo: l'inventario non vede più nessun PC esposto."
    caso.save(update_fields=["status", "closed_at", "resolution", "updated_at"])
    SecurityAlertActionLog.objects.create(ticket=caso, action="case_auto_resolved", actor=ATTORE,
                                          details={"old_status": vecchio, "new_status": Status.RESOLVED, "reason": caso.resolution})
    traccia.registra(traccia.CASO_AUTO_CHIUSO, {"caso_id": caso.pk, "old_status": vecchio, "new_status": Status.RESOLVED,
                                                "reason": caso.resolution}, oggetto=caso)
    return True


def riepilogo(record):
    """Per la scheda della CVE: il lavoro aperto e a che punto è."""
    caso = lavoro_aperto(record)
    if caso is None:
        return None
    attivita = list(caso.tasks.exclude(cve_host=""))
    return {"caso": caso, "fatti": sum(1 for t in attivita if t.done), "totale": len(attivita)}
