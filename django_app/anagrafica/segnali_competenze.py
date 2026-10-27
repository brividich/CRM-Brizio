"""Ricalcolo dei livelli sulle mansioni con competenze quando cambia ciò da cui dipendono.

Il grosso arriva già da ``segnali_scadenze``: corsi, abilitazioni MOD.128, persone
in lista passano da ``scadenze.ricalcola_tutto``, che in coda riallinea i livelli
(``services.competenze_ricalcolo``). Qui il resto, sempre a transazione conclusa:

- competenze della mansione (aggiunta, livello minimo, bloccante, requisito, spenta):
  le persone in lista su quella mansione;
- regola di calcolo e soglia del Mansionario: tutti;
- qualifiche della persona (patentini): la persona, come per i corsi.
"""
from __future__ import annotations

import logging

from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)

_UID = "anagrafica_competenze_"


def _dopo_commit(**kwargs) -> None:
    def esegui():
        from anagrafica.services.competenze_ricalcolo import ricalcola

        try:
            ricalcola(**kwargs)
        except Exception:
            # Il ricalcolo non deve mai impedire il salvataggio: lo riprende la notte.
            logger.exception("ricalcolo livelli competenze fallito (%s)", kwargs.get("motivo"))

    transaction.on_commit(esegui)


def _voce(sender, instance, raw=False, **kwargs):
    if not raw and instance.mansione_id:
        _dopo_commit(mansioni_ids=[instance.mansione_id], motivo="competenze della mansione cambiate")


def _config(sender, instance, raw=False, **kwargs):
    if not raw:
        _dopo_commit(motivo="regole del Mansionario cambiate")


def _qualifica(sender, instance, raw=False, **kwargs):
    if not raw and instance.legacy_anagrafica_id:
        _dopo_commit(legacy_ids=[instance.legacy_anagrafica_id], motivo="qualifiche della persona cambiate")


def collega() -> None:
    """Registra i segnali (idempotente: dispatch_uid)."""
    for nome, handler in (("VoceMacchinaCatalogo", _voce), ("SkillMatrixConfig", _config),
                          ("DipendenteQualifica", _qualifica)):
        m = apps.get_model("anagrafica", nome)
        post_save.connect(handler, sender=m, dispatch_uid=f"{_UID}save_{nome}")
        post_delete.connect(handler, sender=m, dispatch_uid=f"{_UID}del_{nome}")
