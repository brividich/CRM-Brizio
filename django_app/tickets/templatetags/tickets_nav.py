"""Voci della subnav dei ticket che dipendono dalla persona."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def vede_altri_ticket(context):
    """Mostra la sezione «Ticket» (ticket di altri) a chi il ruolo li fa vedere."""
    request = context.get("request")
    if request is None:
        return False
    from tickets.views import puo_vedere_altri_ticket

    return puo_vedere_altri_ticket(request)


_CACHE_CATEGORIA_HUB = "tickets:categoria_hub_codice"


def _codice_categoria_hub() -> str:
    """Codice della categoria IT attiva con «hub» nel codice o nell'etichetta ('' se manca)."""
    from django.core.cache import cache

    codice = cache.get(_CACHE_CATEGORIA_HUB)
    if codice is None:
        from django.db.models import Q

        from tickets.models import CategoriaTicket, TipoTicket

        cat = (
            CategoriaTicket.objects.filter(tipo=TipoTicket.IT, attivo=True)
            .filter(Q(codice__icontains="hub") | Q(etichetta__icontains="hub"))
            .order_by("ordine", "etichetta")
            .values_list("codice", flat=True)
            .first()
        )
        codice = cat or ""
        cache.set(_CACHE_CATEGORIA_HUB, codice, 300)
    return codice


@register.simple_tag(takes_context=True)
def link_segnala_hub(context):
    """Link «Segnalazione NOVICROM HUB»: nuovo ticket IT con la categoria HUB e la pagina di partenza.

    Solo precompilazione del form (nessun ticket nasce da un GET); permessi quelli di «Nuovo ticket».
    """
    from urllib.parse import urlencode

    from django.urls import reverse

    params = {"tipo": "IT", "asset_libero": "NOVICROM HUB"}
    codice = _codice_categoria_hub()
    if codice:
        params["categoria"] = codice
    request = context.get("request")
    if request is not None and not request.path.startswith("/tickets/nuovo"):
        params["descrizione"] = f"Pagina: {request.get_full_path()[:300]}\n\n"
    return f"{reverse('tickets:nuovo')}?{urlencode(params)}"