"""Aspetto della pagina pubblica «Richiesta di visita»: titolo, testo e colore da Reception → Impostazioni."""
from django import template

register = template.Library()


@register.simple_tag
def pagina_pubblica() -> dict:
    from ..personalizza import pagina

    return pagina()
