from __future__ import annotations

from django import template

from dpi.models import normalizza_icona_dpi

register = template.Library()


@register.filter
def dpi_icon_key(valore: str) -> str:
    """Normalizza icona_emoji (chiave nuova o emoji legacy) su una chiave valida."""
    return normalizza_icona_dpi(valore)


@register.filter
def dpi_filetype(nome: str) -> str:
    """Famiglia del file dal nome (pdf/doc/xls/img/file), per il badge nell'elenco documenti."""
    ext = (nome or "").rsplit(".", 1)[-1].lower() if "." in (nome or "") else ""
    if ext == "pdf":
        return "pdf"
    if ext in {"doc", "docx"}:
        return "doc"
    if ext in {"xls", "xlsx"}:
        return "xls"
    if ext in {"jpg", "jpeg", "png"}:
        return "img"
    return "file"
