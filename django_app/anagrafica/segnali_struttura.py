"""Struttura della Qualità: la mansione «Responsabilità del reparto» segue il reparto.

Quando un reparto cambia ruolo responsabile, nome o stato, la sua mansione di
responsabilità si crea, si rinomina, cambia ruolo o si spegne da sola: una sola
fonte (il reparto), nessun doppione da tenere allineato a mano.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


def _reparto_salvato(sender, instance=None, raw=False, **kwargs):
    if raw or instance is None:
        return
    from .models import CompetenzaSkm

    # Niente da fare per i reparti mai entrati nella struttura (nessun ruolo, nessuna mansione).
    if not instance.ruolo_responsabile_id and not CompetenzaSkm.objects.filter(
            responsabilita_reparto=instance).exists():
        return
    try:
        from .services.struttura_v8 import assicura_responsabilita

        assicura_responsabilita(instance)
    except Exception:  # la mansione derivata non deve mai bloccare il salvataggio del reparto
        logger.exception("Responsabilità del reparto non allineata per %s", instance.pk)


def collega() -> None:
    from .models import Reparto

    post_save.connect(_reparto_salvato, sender=Reparto, dispatch_uid="anagrafica_responsabilita_reparto")
