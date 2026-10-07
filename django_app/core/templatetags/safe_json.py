"""Filtro ``js_json``: dati dentro un ``<script>`` senza rischio di XSS.

``{{ x_json|safe }}`` dentro uno script e' vulnerabile: ``json.dumps`` non
neutralizza ``</script>``, quindi un nome inserito da un utente (fornitore,
asset, reparto) puo' chiudere lo script e iniettarne un altro.

Uso::

    {% load safe_json %}
    <script>const mappa = {{ mappa_json|js_json }};</script>

Accetta sia una stringa gia' serializzata in JSON sia un oggetto Python
(serializzato qui). ``<``, ``>``, ``&`` e i separatori di riga U+2028/U+2029
diventano escape ``\\uXXXX``: dentro una stringa JSON sono equivalenti, fuori
dalle stringhe in un JSON valido non possono comparire.
"""
from __future__ import annotations

import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

register = template.Library()

_JS_ESCAPES = {
    ord("<"): "\\u003C",
    ord(">"): "\\u003E",
    ord("&"): "\\u0026",
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


@register.filter(name="js_json")
def js_json(value):
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, cls=DjangoJSONEncoder)
    return mark_safe(raw.translate(_JS_ESCAPES))
