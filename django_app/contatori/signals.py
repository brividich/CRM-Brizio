"""Firmware nell'inventario del SOC sempre coerente con il dispositivo.

Il firmware entra nel SOC a ogni interrogazione riuscita (``firmware.invia_al_soc``);
qui si gestisce il resto: dispositivo disattivato, eliminato, con IP cambiato o
collegato a un altro asset. Senza, le righe restavano «rilevate» per sempre e gli
impatti CVE restavano sull'asset sbagliato.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import DispositivoSNMP

logger = logging.getLogger(__name__)


def _soc(funzione, *args):
    def esegui():
        try:
            from security.services import firmware_inventory

            getattr(firmware_inventory, funzione)(*args)
        except Exception:  # noqa: BLE001 - il salvataggio del dispositivo non dipende dal SOC
            logger.exception("Inventario firmware SOC non aggiornato (%s %s)", funzione, args)

    transaction.on_commit(esegui)


@receiver(pre_save, sender=DispositivoSNMP, dispatch_uid="contatori.dispositivo_prima")
def _ricorda_stato(sender, instance, update_fields=None, **kwargs):
    # Il polling salva solo stato e letture: nessuna query in piu' a ogni interrogazione.
    if not instance.pk or (update_fields is not None and not {"host", "attivo", "asset"} & set(update_fields)):
        instance._prima = None
        return
    instance._prima = DispositivoSNMP.objects.filter(pk=instance.pk).values("host", "attivo", "asset_id").first()


@receiver(post_save, sender=DispositivoSNMP, dispatch_uid="contatori.dispositivo_dopo")
def _allinea_soc(sender, instance, created, update_fields=None, **kwargs):
    prima = getattr(instance, "_prima", None)
    if created or not prima:
        return
    if prima["host"] != instance.host:
        _soc("dismetti_host", prima["host"])
    elif prima["attivo"] and not instance.attivo:
        _soc("dismetti_host", instance.host)
    if prima["asset_id"] != instance.asset_id:
        _soc("aggiorna_asset", instance.host, instance.asset_id)


@receiver(post_delete, sender=DispositivoSNMP, dispatch_uid="contatori.dispositivo_eliminato")
def _dispositivo_eliminato(sender, instance, **kwargs):
    _soc("dismetti_host", instance.host)
