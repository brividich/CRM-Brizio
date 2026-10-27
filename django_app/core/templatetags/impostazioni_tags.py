"""Voce «Impostazioni» nelle subnav dei moduli.

``{% impostazioni_visibili "dpi" is_gestore as mostra_impostazioni %}``: con il sistema
dei ruoli acceso decide l'azione «impostazioni» della matrice, spento resta la
condizione storica passata come secondo argomento.
"""
from django import template

from core.permessi.impostazioni import impostazioni_consentite

register = template.Library()


@register.simple_tag(takes_context=True)
def impostazioni_visibili(context, chiave_modulo, storico=True):
    request = context.get("request")
    esito = impostazioni_consentite(request, chiave_modulo) if request is not None else None
    return bool(storico) if esito is None else esito
