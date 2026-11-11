"""Alert doppi: un problema sullo stesso soggetto è un alert solo, non uno per ogni mail.

* **Report via mail con un soggetto** (Endpoint Security «N devices blocked su PC», backup di un job):
  ogni mail è un evento a sé, ma l'alert si apre una volta per (sorgente, tipo, PC o job). Le mail
  successive aggiornano lo stesso alert (titolo con il conteggio nuovo, evento più recente) finché
  qualcuno lo chiude o il rientro lo chiude. La chiave è ``chiave_alert``.
* **CVE dalla mail di Defender e dall'inventario**: la mail apre «Vulnerabilità critica esposta CVE-X»,
  l'inventario apre gli alert PC per PC (versione vulnerabile, oltre il termine). Quando la CVE è già
  seguita PC per PC l'alert della mail è un doppione: non si apre, e quello già aperto si chiude come
  doppione (``chiudi_cve_doppie``), con il rimando agli alert dell'inventario.
* ``unisci_doppioni`` sistema gli alert già aperti prima di questa regola (comando
  ``security_unisci_doppioni``): tiene il più recente di ogni gruppo e chiude gli altri come «unito».

Nessuna chiusura qui dice «risolto»: un doppione chiuso rimanda sempre all'alert che resta aperto.
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, SecurityEventRecord, Status
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

AUTO_ACTOR = "system"
TIPI_PER_SOGGETTO = ("watchguard_alert_candidate", "backup_job")
TIPI_CVE_INVENTARIO = ("cve_impact_confirmed", "cve_sla_scaduta")
_NUMERI = re.compile(r"\d+(?:[.,]\d+)*")
_CVE = re.compile(r"CVE-\d{4}-\d{4,}", re.I)


def _norm(valore) -> str:
    return str(valore or "").strip().lower()


def chiave_alert(event) -> str:
    """Chiave dell'alert per gli eventi che hanno un soggetto; vuota = vale l'impronta dell'evento."""
    payload = event.payload or {}
    if event.event_type == "backup_job":
        job = _norm(payload.get("job_name"))
        if not job:
            return ""
        return make_hash(event.source_id, "alert", "backup_job", job, _norm(payload.get("device_name")))
    if event.event_type == "watchguard_alert_candidate":
        tipo = _norm(payload.get("type"))
        soggetto = _norm(payload.get("computer"))
        if not soggetto:
            # Senza PC: il titolo senza i numeri («Endpoint Security: # devices blocked su computer non indicato»).
            soggetto = _NUMERI.sub("#", _norm(payload.get("title")))
        if not (tipo or soggetto):
            return ""
        return make_hash(event.source_id, "alert", "watchguard_alert_candidate", tipo, soggetto)
    return ""


def eventi_collegati_ids(alert) -> list[int]:
    """Gli eventi passati da questo alert (l'impronta dell'evento non basta più quando la chiave è il soggetto)."""
    ids = set()
    for details in SecurityAlertActionLog.objects.filter(
            alert=alert, action__in=("alert_created", "alert_reused", "alert_merged")).values_list("details", flat=True):
        if isinstance(details, dict):
            for chiave in ("event_id",):
                if isinstance(details.get(chiave), int):
                    ids.add(details[chiave])
            for valore in details.get("event_ids") or []:
                if isinstance(valore, int):
                    ids.add(valore)
    if alert.event_id:
        ids.add(alert.event_id)
    return sorted(ids)


def occorrenze(alert):
    """Eventi dello stesso alert: stessa impronta oppure passati dall'alert (chiave per soggetto)."""
    filtro = Q(pk__in=eventi_collegati_ids(alert))
    if alert.dedup_hash:
        filtro |= Q(dedup_hash=alert.dedup_hash)
    return SecurityEventRecord.objects.filter(filtro)


# --- CVE: mail di Defender e inventario -----------------------------------------------------

def alert_inventario_per_cve(cve: str):
    """Alert aperti dell'inventario (PC per PC) su questa CVE."""
    cve = (cve or "").upper()
    if not cve:
        return []
    candidati = (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type__in=TIPI_CVE_INVENTARIO,
                                              title__icontains=cve)
                 .select_related("event"))
    return [a for a in candidati if str((a.event.payload or {}).get("cve") or "").upper() == cve]


def _chiudi_come_doppione(alert, motivo: str, verso=None, azione="alert_merged", event_ids=None):
    vecchio = alert.status
    alert.status = Status.CLOSED
    alert.status_reason = motivo[:2000]
    alert.closed_at = timezone.now()
    alert.snoozed_until = None
    alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
    dettagli = {"old_status": vecchio, "new_status": Status.CLOSED, "reason": motivo, "actor": AUTO_ACTOR}
    if verso is not None:
        dettagli["unito_a"] = verso.pk
    SecurityAlertActionLog.objects.create(alert=alert, action="closed_as_duplicate", actor=AUTO_ACTOR, details=dettagli)
    if verso is not None:
        SecurityAlertActionLog.objects.create(alert=verso, action=azione, actor=AUTO_ACTOR,
                                              details={"da_alert": alert.pk, "event_ids": list(event_ids or []),
                                                       "reason": motivo})
    from security.services import traccia

    traccia.registra(traccia.ALERT_AUTO_RISOLTO, {"alert_id": alert.pk, "titolo": alert.title, "rule": "doppione", **dettagli},
                     oggetto=alert, attore=AUTO_ACTOR)


def chiudi_cve_doppie(apply: bool = True) -> list[dict]:
    """Alert «Vulnerabilità critica esposta» (mail di Defender) la cui CVE è seguita PC per PC dall'inventario."""
    out = []
    for alert in (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type="vulnerability_finding")
                  .select_related("event")):
        cve = str((alert.event.payload or {}).get("cve") or "").upper() or next(iter(_CVE.findall(alert.title or "")), "").upper()
        inventario = alert_inventario_per_cve(cve)
        if not inventario:
            continue
        motivo = (f"Doppione: {cve} è seguita PC per PC dall'inventario ({len(inventario)} alert aperti, "
                  f"es. #{inventario[0].pk} «{inventario[0].title[:80]}»). Si chiude lì, PC per PC.")
        out.append({"alert": alert.pk, "titolo": alert.title, "cve": cve, "inventario": len(inventario)})
        if apply:
            with transaction.atomic():
                _chiudi_come_doppione(alert, motivo, verso=inventario[0], azione="cve_doppione_unito",
                                      event_ids=[alert.event_id] if alert.event_id else [])
    return out


# --- Alert già aperti, uno per mail ---------------------------------------------------------

def unisci_doppioni(apply: bool = False) -> list[dict]:
    """Per ogni (sorgente, PC o job) tiene l'alert aperto più recente e chiude gli altri come uniti a quello.

    L'alert tenuto prende la chiave per soggetto, così le mail successive lo aggiornano invece di aprirne uno nuovo.
    """
    gruppi = defaultdict(list)
    for alert in (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type__in=TIPI_PER_SOGGETTO)
                  .select_related("event").order_by("created_at")):
        chiave = chiave_alert(alert.event)
        if chiave:
            gruppi[(alert.source_id, chiave)].append(alert)
    out = []
    for (_source, chiave), alerts in gruppi.items():
        if len(alerts) == 1 and alerts[0].dedup_hash == chiave:
            continue
        def _quando(a):
            return (a.event.occurred_at or a.created_at, a.created_at, a.pk)
        alerts.sort(key=_quando)
        tenuto, altri = alerts[-1], alerts[:-1]
        out.append({"tenuto": tenuto.pk, "titolo": tenuto.title, "uniti": [a.pk for a in altri]})
        if not apply:
            continue
        with transaction.atomic():
            for alert in altri:
                motivo = (f"Unito all'alert #{tenuto.pk} «{tenuto.title[:80]}»: stesso problema sullo stesso "
                          f"{'job' if alert.event.event_type == 'backup_job' else 'PC'}, segnalato da un'altra mail.")
                _chiudi_come_doppione(alert, motivo, verso=tenuto, event_ids=[alert.event_id] if alert.event_id else [])
            if tenuto.dedup_hash != chiave:
                tenuto.dedup_hash = chiave
                tenuto.save(update_fields=["dedup_hash", "updated_at"])
    return out
