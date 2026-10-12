"""Collegamento «Guida di questa pagina» per audit interni e Registro OFI."""
from django import template
from django.urls import NoReverseMatch
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def sg_guida_link(context):
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if not match:
        return ""
    from sistema_gestione.guida import link_pagina

    try:
        url = link_pagina(match.view_name)
    except NoReverseMatch:
        return ""
    if not url:
        return ""
    return format_html(
        '<p class="sg-guida-link"><a href="{}" target="_blank" rel="noopener" '
        'title="Apre in una nuova scheda il capitolo della guida che spiega questa pagina">'
        '<span aria-hidden="true">?</span> Guida di questa pagina</a></p>', url)
