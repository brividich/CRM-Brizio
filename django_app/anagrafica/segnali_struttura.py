"""Struttura della Qualità: la mansione «Responsabilità del reparto» segue il reparto,
quella «Responsabilità dell'area» segue l'area (27/10/2026).

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


def _area_salvata(sender, instance=None, raw=False, **kwargs):
    if raw or instance is None:
        return
    from .models import CompetenzaSkm

    if not instance.ruolo_responsabile_id and not CompetenzaSkm.objects.filter(
            responsabilita_area=instance).exists():
        return
    try:
        from .services.struttura_v8 import assicura_responsabilita_area

        assicura_responsabilita_area(instance)
    except Exception:  # la mansione derivata non deve mai bloccare il salvataggio dell'area
        logger.exception("Responsabilità dell'area non allineata per %s", instance.pk)


def _reparto_salvato_aree(sender, instance=None, raw=False, **kwargs):
    # Rinomina del reparto: un'area può iniziare o smettere di coincidere col reparto.
    if raw or instance is None:
        return
    for area in instance.aree_aziendali.all():
        _area_salvata(sender, instance=area)


def collega() -> None:
    from .models import AreaAziendale, Reparto

    post_save.connect(_reparto_salvato, sender=Reparto, dispatch_uid="anagrafica_responsabilita_reparto")
    post_save.connect(_reparto_salvato_aree, sender=Reparto, dispatch_uid="anagrafica_responsabilita_aree_reparto")
    post_save.connect(_area_salvata, sender=AreaAziendale, dispatch_uid="anagrafica_responsabilita_area")
