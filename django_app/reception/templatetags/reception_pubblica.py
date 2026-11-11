"""Aspetto della pagina pubblica «Richiesta di visita»: titolo, testo, colore e logo da Reception → Impostazioni."""
from django import template

register = template.Library()


@register.simple_tag
def pagina_pubblica() -> dict:
    from fornitori import chiosco

    from ..personalizza import pagina

    dati = pagina()
    dati["logo_versione"] = chiosco.logo_versione() if chiosco.logo_percorso() else ""
    return dati
