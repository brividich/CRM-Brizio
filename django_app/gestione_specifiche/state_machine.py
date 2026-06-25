"""Audit centralizzato della macchina a stati (§6).

Collega il signal `post_transition` di django-fsm: ad ogni transizione di
`Specifica.stato` crea ESATTAMENTE un `EventoSpecifica` immutabile, con snapshot
dei metadati nel payload (ricostruzione punto-nel-tempo) e gli extra preparati
dalla transizione via `Specifica._prep_evento`.
"""
from __future__ import annotations

from django.dispatch import receiver
from django_fsm.signals import post_transition

from .models import EventoSpecifica, Specifica


@receiver(post_transition, sender=Specifica)
def audit_post_transition(sender, instance, name, source, target, **kwargs):
    attore = getattr(instance, "_evento_attore", None)
    extra = getattr(instance, "_evento_payload", None) or {}

    payload = {"snapshot": instance.snapshot_metadati()}
    if extra:
        payload.update(extra)

    EventoSpecifica.objects.create(
        specifica=instance,
        stato_da=source or "",
        # instance.stato è già il nuovo valore (robusto anche per GET_STATE).
        stato_a=instance.stato,
        attore=attore,
        trigger=name,
        payload=payload,
    )

    # reset dei transient per non sporcare transizioni successive
    instance._evento_attore = None
    instance._evento_payload = {}
