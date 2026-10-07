"""Barra di stato del SOC: i numeri che contano, in cima a ogni pagina, sempre aggiornati.

Calcolati una volta al minuto per tutti (cache) tranne «i miei», che dipende da chi guarda.
Ogni voce porta alla lista già filtrata. Fail-safe: se un conteggio fallisce, la voce sparisce
invece di rompere la pagina.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_KEY = "soc:live-status:v1"
CACHE_SECONDS = 60


def _shared():
    from security.models import SecurityAlert, SecurityIncident, SecurityMailboxMessage, SecurityRemediationTicket, Severity
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
    from security.services.cases import ACTIVE_CASE_STATUSES

    items = []

    def add(key, fn):
        try:
            items.append(fn())
        except Exception:  # noqa: BLE001 - una voce rotta non rompe la barra
            logger.exception("Barra di stato SOC: voce %s non calcolata", key)

    def alerts():
        n = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity__in=[Severity.CRITICAL, Severity.HIGH]).count()
        return {"key": "alerts", "label": "critici e alti", "value": n, "tone": "critical" if n else "success",
                "url": reverse("security:alerts_list") + "?status=active&severity=critical&severity=high",
                "title": "Alert critici o alti ancora aperti"}

    def deadlines():
        from security.services.incidents import urgent_incidents

        rows = urgent_incidents()
        overdue = sum(1 for r in rows if r["deadline"]["state"] == "overdue")
        return {"key": "nis2", "label": "scadenze NIS2", "value": len(rows), "tone": "critical" if overdue else ("warning" if rows else "success"),
                "url": reverse("security:incidents"), "title": f"Notifiche scadute ({overdue}) o in scadenza entro 12 ore"}

    def backups():
        from security.services.backup_center import FAIL, overview

        devices = overview(7)["devices"]
        bad = sum(1 for d in devices if d["stale"] or d["last_status"] == FAIL)
        return {"key": "backup", "label": "PC backup ko", "value": bad, "tone": "warning" if bad else "success",
                "url": reverse("security:backup") + "?giorni=7#pc", "title": "PC con ultimo backup fallito o senza backup riuscito oltre la soglia"}

    def silent():
        from security.services.source_heartbeat import source_status_rows

        n = sum(1 for r in source_status_rows() if r["state"] in ("high", "warning"))
        return {"key": "sources", "label": "sorgenti mute", "value": n, "tone": "warning" if n else "success",
                "url": reverse("security:admin_mailbox_sources_list"), "title": "Sorgenti di report che non mandano dati da troppo"}

    def unassigned():
        n = SecurityRemediationTicket.objects.filter(assignee__isnull=True, status__in=ACTIVE_CASE_STATUSES).count()
        n += SecurityIncident.objects.filter(owner__isnull=True, status__in=["open", "contained"]).count()
        return {"key": "unassigned", "label": "senza responsabile", "value": n, "tone": "warning" if n else "success",
                "url": reverse("security:tickets_list") + "?assignee=none", "title": "Ticket e incidenti aperti senza responsabile"}

    for key, fn in (("alerts", alerts), ("nis2", deadlines), ("backup", backups), ("sources", silent), ("unassigned", unassigned)):
        add(key, fn)
    last = SecurityMailboxMessage.objects.order_by("-received_at").values_list("received_at", flat=True).first()
    return {"items": items, "last_report": last, "computed_at": timezone.now()}


def live_status(user):
    data = cache.get(CACHE_KEY)
    if data is None:
        data = _shared()
        cache.set(CACHE_KEY, data, CACHE_SECONDS)
    mine = 0
    try:
        from security.models import SecurityIncident, SecurityRemediationTicket
        from security.services.cases import ACTIVE_CASE_STATUSES

        if getattr(user, "is_authenticated", False):
            mine = SecurityRemediationTicket.objects.filter(assignee=user, status__in=ACTIVE_CASE_STATUSES).count()
            mine += SecurityIncident.objects.filter(owner=user, status__in=["open", "contained"]).count()
    except Exception:  # noqa: BLE001
        logger.exception("Barra di stato SOC: «i miei» non calcolato")
    worst = "success"
    for item in data["items"]:
        if item["tone"] == "critical":
            worst = "critical"
        elif item["tone"] == "warning" and worst != "critical":
            worst = "warning"
    return {**data, "mine": mine, "worst": worst}
