"""Etichette CN-SGI sulle pagine dei moduli: «SGI · MT CN 451 Rev.2» accanto al sotto-menu."""
from __future__ import annotations

from django import template

register = template.Library()


@register.inclusion_tag("procedure_refresh/components/etichette_modulo.html", takes_context=True)
def cnsgi_etichette(context):
    request = context.get("request")
    if request is None or not getattr(getattr(request, "user", None), "is_authenticated", False):
        return {"procedure": []}
    try:
        from procedure_refresh.collegamenti import MAX_ETICHETTE, procedure_della_pagina

        modulo, procedure = procedure_della_pagina(request.path)
    except Exception:
        return {"procedure": []}
    return {"procedure": procedure[:MAX_ETICHETTE], "altre": max(0, len(procedure) - MAX_ETICHETTE), "modulo": modulo}


@register.filter
def voce(mappa, chiave):
    """``{{ dizionario|voce:chiave }}``: valore di una chiave (stringa vuota se manca)."""
    try:
        return mappa.get(chiave, "")
    except AttributeError:
        return ""
