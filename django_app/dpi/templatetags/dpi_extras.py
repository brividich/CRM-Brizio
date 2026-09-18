from __future__ import annotations

from django import template

from dpi.models import normalizza_icona_dpi

register = template.Library()


@register.filter
def dpi_icon_key(valore: str) -> str:
    """Normalizza icona_emoji (chiave nuova o emoji legacy) su una chiave valida."""
    return normalizza_icona_dpi(valore)
