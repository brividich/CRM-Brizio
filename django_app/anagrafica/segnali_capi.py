"""Capo e team: cache azzerata e schede riallineate quando cambiano i dati.

La regola unica (``services.capo_team``) dipende da schede aziendali, reparti,
aree, ruoli e assegnazioni. A ogni modifica la cache si azzera; con la regola
accesa, a transazione conclusa, il «Caporeparto» delle schede si riallinea una
volta sola per transazione (un import di 100 schede non ricalcola 100 volte).
"""
from __future__ import annotations

import logging
import threading

from django.db import transaction
from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)
_UID = "anagrafica_capi_"
_stato = threading.local()

MODELLI = ("DipendenteAnagraficaAziendale", "Reparto", "AreaAziendale", "DipendenteRuoloOperativo", "RuoloOperativo")


def _riallinea_dopo_commit(generazione: int):
    # Più modifiche nella stessa transazione registrano più callback: lavora
    # solo l'ultima. Un rollback li scarta tutti e la generazione dopo riparte.
    if generazione != getattr(_stato, "generazione", 0):
        return
    try:
        from .services import capo_team

        capo_team.invalida_cache()
        if capo_team.regola_unica_attiva():
            capo_team.riallinea_tutte_le_schede()
    except Exception:
        logger.warning("capi: riallineamento non riuscito", exc_info=True)


def _cambiato(sender, instance=None, update_fields=None, **kwargs):
    # Il riallineamento stesso scrive solo caporeparto_legacy_id con update():
    # niente segnali, niente giri a vuoto. Un save() che tocca solo quel campo
    # (da _sync_aziendale_from_reparto) non cambia la regola.
    if update_fields is not None and set(update_fields) <= {"caporeparto_legacy_id", "updated_by", "updated_at"}:
        return
    try:
        from .services import capo_team

        capo_team.invalida_cache()
    except Exception:
        pass
    _stato.generazione = getattr(_stato, "generazione", 0) + 1
    generazione = _stato.generazione
    transaction.on_commit(lambda: _riallinea_dopo_commit(generazione))


def collega() -> None:
    from django.apps import apps

    for nome in MODELLI:
        try:
            m = apps.get_model("anagrafica", nome)
        except LookupError:
            continue
        post_save.connect(_cambiato, sender=m, dispatch_uid=f"{_UID}save_{nome}")
        post_delete.connect(_cambiato, sender=m, dispatch_uid=f"{_UID}del_{nome}")
