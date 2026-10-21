"""Tag ``url_pagina``: link a un'altra pagina di un elenco, filtri compresi.

Serve al pager condiviso ``core/components/_pager_passo_passo.html``: tiene
tutta la querystring corrente (filtri a scelta multipla compresi) e cambia
solo il parametro di pagina, che può avere un nome proprio quando nella
stessa pagina convivono più elenchi paginati.

Uso::

    {% load paginazione %}
    <a href="{% url_pagina 'log_page' 3 %}">3</a>
"""
from __future__ import annotations

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_pagina(context, param, numero):
    request = context.get("request")
    query = request.GET.copy() if request is not None else None
    if query is None:
        return f"?{param}={numero}"
    query[str(param or "page")] = str(numero)
    return "?" + query.urlencode()
