"""{% catalogo_datalist "ATTIVITA" %}: i suggerimenti del catalogo per un campo di testo (list="cat-attivita")."""
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()


@register.simple_tag
def catalogo_datalist(tipo: str):
    from ..services.catalogo import suggerimenti

    voci = suggerimenti(tipo)
    return format_html(
        '<datalist id="cat-{}">{}</datalist>', tipo.lower(), format_html_join("", '<option value="{}">', ((v.testo,) for v in voci)),
    )
