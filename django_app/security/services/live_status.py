"""Barra di stato del SOC: i numeri che contano, in cima a ogni pagina, sempre aggiornati.

Calcolati una volta al minuto per tutti (cache) tranne «i miei», che dipende da chi guarda.
Ogni voce porta alla lista già filtrata. Fail-safe: se un conteggio fallisce, la voce sparisce
invece di rompere la pagina.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_KEY = "soc:live-status:v1"
CACHE_SECONDS = 60


def _shared():
    """I riquadri vengono dal catalogo delle metriche: stessi numeri del menu, della Panoramica e degli elenchi."""
    from security.models import SecurityMailboxMessage
    from security.services import metriche

    items = []
    for fn in (metriche.segnalazioni_urgenti, metriche.scadenze_legali, metriche.pc_backup_ko, metriche.sorgenti_mute):
        try:
            items.append(fn().as_item())
        except Exception:  # noqa: BLE001 - una voce rotta non rompe la barra
            logger.exception("Barra di stato SOC: voce %s non calcolata", fn.__name__)
    last = SecurityMailboxMessage.objects.order_by("-received_at").values_list("received_at", flat=True).first()
    return {"items": items, "last_report": last, "computed_at": timezone.now()}


def live_status(user):
    data = cache.get(CACHE_KEY)
    if data is None:
        data = _shared()
        cache.set(CACHE_KEY, data, CACHE_SECONDS)
    worst = "success"
    for item in data["items"]:
        if item["tone"] == "critical":
            worst = "critical"
        elif item["tone"] == "warning" and worst != "critical":
            worst = "warning"
    return {**data, "worst": worst}
