"""Elenchi a caricamento passo passo.

Un elenco che finisce in una tabella non si taglia più con ``[:200]`` (le righe
oltre il limite sparivano senza avviso): si pagina con :func:`pagina_elenco` e
il template mette sotto la tabella il pager condiviso
``core/components/_pager_passo_passo.html``. Nel browser ``fm-table-enhanced.js``
nasconde il pager e carica le pagine successive mentre si scorre (o tutte, se
si filtra o si cerca); senza JavaScript resta un normale pager a link.
"""
from __future__ import annotations

from django.core.paginator import Paginator

PER_PAGINA = 100


def pagina_elenco(request, elenco, per_pagina: int = PER_PAGINA, param: str = "page"):
    """Pagina ``elenco`` (queryset ordinato o lista) leggendo ``request.GET[param]``."""
    return Paginator(elenco, per_pagina).get_page(request.GET.get(param, 1))
