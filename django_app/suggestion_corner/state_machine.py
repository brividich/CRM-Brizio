"""Audit centralizzato della macchina a stati (§2).

Collega il signal `post_transition` di django-fsm: ad ogni transizione di
`SuggestionCorner.stato` crea ESATTAMENTE una voce `SuggestionCornerStorico`,
con attore/payload preparati dalla transizione via `_prep_evento`.
"""
from __future__ import annotations

from django.dispatch import receiver
from django_fsm.signals import post_transition

from .models import SuggestionCorner, SuggestionCornerStorico


@receiver(post_transition, sender=SuggestionCorner)
def audit_post_transition(sender, instance, name, source, target, **kwargs):
    attore = getattr(instance, "_evento_attore", None)

    SuggestionCornerStorico.objects.create(
        segnalazione=instance,
        stato_precedente=source or "",
        # instance.stato è già il nuovo valore.
        stato_nuovo=instance.stato,
        autore=attore,
    )

    # reset dei transient per non sporcare transizioni successive
    instance._evento_attore = None
    instance._evento_payload = {}
