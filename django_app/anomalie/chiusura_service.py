"""Cosa succede dopo che un'anomalia si chiude (a mano o con la regola automatica).

Un solo passaggio, chiamato da tutti i punti che chiudono (pagina, link mail,
decisione qualità, «azione effettuata»):

- **stato finale**: se l'anomalia si chiude con lo stato «In attesa» (o vuoto),
  riprende l'ultima decisione presa (dal registro): KPI e registro non la vedono
  chiusa «senza decisione»; se una decisione non c'è mai stata resta «In attesa»;
- **richieste di informazioni**: quelle ancora aperte si chiudono con la nota
  «Chiusa con l'anomalia», così non restano appese su un'anomalia chiusa.

Mai bloccante: un errore qui non annulla la chiusura.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

NOTA_RICHIESTA_CHIUSA = "Chiusa con l'anomalia: nessuna risposta registrata."
RUOLO_CHIUSURA = "chiusura"
# Valori di new_status nel registro che non sono una decisione del capocommessa.
_NON_DECISIONI = {"", "in attesa", "chiusa", "torna alla qualità", "decisione qualità", "in attesa chiarimenti"}


def dopo_chiusura(anomalia_id, *, chi: str = "") -> None:
    if not anomalia_id:
        return
    try:
        if not _chiusa(int(anomalia_id)):
            return
    except Exception:
        logger.warning("chiusura: stato dell'anomalia non letto id=%s", anomalia_id, exc_info=True)
        return
    try:
        stato_finale(int(anomalia_id))
    except Exception:
        logger.warning("chiusura: stato finale non aggiornato id=%s", anomalia_id, exc_info=True)
    try:
        chiudi_richieste(int(anomalia_id), chi=chi)
    except Exception:
        logger.warning("chiusura: richieste di informazioni non chiuse id=%s", anomalia_id, exc_info=True)


def _chiusa(anomalia_id: int) -> bool:
    from .views import _fetch_all_dict

    righe = _fetch_all_dict("SELECT chiudere FROM anomalie WHERE id = %s", [int(anomalia_id)])
    return bool(righe and righe[0].get("chiudere"))


def ultima_decisione(anomalia_id: int) -> str:
    """Ultimo stato di avanzamento scelto (registro attività), escluse attese libere."""
    from .mail_action_models import AnomaliaActionLog

    for stato in (AnomaliaActionLog.objects.filter(anomalia_id=int(anomalia_id))
                  .exclude(new_status="").order_by("-id").values_list("new_status", flat=True)[:200]):
        testo = str(stato or "").strip()
        if testo.lower() not in _NON_DECISIONI:
            return testo[:255]
    return ""


def stato_finale(anomalia_id: int) -> str:
    """Anomalia chiusa con stato libero: riprende l'ultima decisione. Ritorna lo stato scritto ("" se nulla)."""
    from django.db import connections

    from .controllo_service import _STATI_LIBERI
    from .views import _fetch_all_dict

    righe = _fetch_all_dict("SELECT avanzamento, chiudere FROM anomalie WHERE id = %s", [int(anomalia_id)])
    if not righe or not righe[0].get("chiudere"):
        return ""
    if str(righe[0].get("avanzamento") or "").strip().lower() not in _STATI_LIBERI:
        return ""
    stato = ultima_decisione(anomalia_id)
    if not stato:
        return ""
    with connections["default"].cursor() as cur:
        cur.execute("UPDATE anomalie SET avanzamento = %s WHERE id = %s AND COALESCE(chiudere, 0) = 1",
                    [stato, int(anomalia_id)])
    return stato


def chiudi_richieste(anomalia_id: int, *, chi: str = "") -> int:
    """Chiude le richieste di informazioni ancora aperte. Ritorna quante."""
    from .quality_models import AnomaliaRichiestaInfo

    return AnomaliaRichiestaInfo.objects.filter(anomalia_id=int(anomalia_id), risposta_il__isnull=True).update(
        risposta=NOTA_RICHIESTA_CHIUSA, risposta_da_display=(chi or "")[:200], risposta_ruolo=RUOLO_CHIUSURA,
        risposta_il=timezone.now(),
    )
