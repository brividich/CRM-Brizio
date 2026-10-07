"""Scadenza delle consegne DPI allineata alla vita utile di categoria e modello.

``ConsegnaDPI.data_scadenza_stimata`` si calcola alla consegna (data + vita utile
del modello, o della categoria). Se poi la vita utile cambia, le consegne ancora
in uso restavano con la scadenza vecchia. Qui, quando cambia la vita utile, si
ricalcolano le consegne **attive** (non sostituite) la cui scadenza e' ancora
quella automatica: una scadenza messa a mano alla consegna non si tocca.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models.signals import post_save, pre_save

logger = logging.getLogger(__name__)


def _vita_prima(sender, instance, raw=False, **kwargs):
    if raw or instance.pk is None:
        instance._vita_prima = None
        return
    instance._vita_prima = sender._default_manager.filter(pk=instance.pk).values_list(
        "vita_utile_giorni", flat=True).first()


def _riallinea(consegne, vita_vecchia_di, vita_nuova_di) -> int:
    from .models import ConsegnaDPI

    n = 0
    for c in consegne:
        vecchia, nuova = vita_vecchia_di(c), vita_nuova_di(c)
        automatica = c.data_consegna + timedelta(days=vecchia) if vecchia else None
        if c.data_scadenza_stimata != automatica:
            continue  # scadenza inserita a mano: resta
        attesa = c.data_consegna + timedelta(days=nuova) if nuova else None
        if attesa != c.data_scadenza_stimata:
            ConsegnaDPI.objects.filter(pk=c.pk).update(data_scadenza_stimata=attesa)
            n += 1
    return n


def _categoria_salvata(sender, instance, created=False, raw=False, **kwargs):
    if raw or created or instance._vita_prima == instance.vita_utile_giorni:
        return
    from .models import ConsegnaDPI

    vecchia, nuova = instance._vita_prima, instance.vita_utile_giorni
    attive = ConsegnaDPI.objects.filter(sostituita_da__isnull=True).select_related(
        "richiesta__modello_dpi__tipo__categoria")
    # Senza modello vale la categoria della richiesta; col modello, la sua categoria se non ha vita propria.
    senza_modello = attive.filter(richiesta__modello_dpi__isnull=True, richiesta__categoria=instance)
    ereditano = attive.filter(richiesta__modello_dpi__tipo__categoria=instance,
                              richiesta__modello_dpi__vita_utile_giorni__isnull=True)
    n = _riallinea(list(senza_modello) + list(ereditano), lambda c: vecchia, lambda c: nuova)
    if n:
        logger.info("DPI: vita utile categoria %s %s→%s gg, %d consegne riallineate", instance.pk, vecchia, nuova, n)


def _modello_salvato(sender, instance, created=False, raw=False, **kwargs):
    if raw or created or instance._vita_prima == instance.vita_utile_giorni:
        return
    from .models import ConsegnaDPI

    cat = instance.tipo.categoria.vita_utile_giorni
    vecchia, nuova = instance._vita_prima or cat, instance.vita_utile_giorni or cat
    attive = ConsegnaDPI.objects.filter(sostituita_da__isnull=True, richiesta__modello_dpi=instance)
    n = _riallinea(attive, lambda c: vecchia, lambda c: nuova)
    if n:
        logger.info("DPI: vita utile modello %s %s→%s gg, %d consegne riallineate", instance.pk, vecchia, nuova, n)


def collega() -> None:
    from .models import CategoriaDPI, ModelloDPI

    for modello, handler in ((CategoriaDPI, _categoria_salvata), (ModelloDPI, _modello_salvato)):
        pre_save.connect(_vita_prima, sender=modello, dispatch_uid=f"dpi_scadenze_pre_{modello.__name__}")
        post_save.connect(handler, sender=modello, dispatch_uid=f"dpi_scadenze_save_{modello.__name__}")
