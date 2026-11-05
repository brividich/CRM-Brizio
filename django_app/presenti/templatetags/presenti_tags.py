"""Pallino «In azienda» accanto al nome di una persona.

Uso: ``{% load presenti_tags %}`` poi ``{% pallino_presenza dip.id %}`` con il
legacy id dell'anagrafica. Legge la fotografia condivisa di
``presenti.services.stato()`` (al massimo una query a Solari al minuto per tutto
il server). Se Solari non è configurato o non risponde non mostra nulla: meglio
nessun pallino che un «fuori» sbagliato.
"""
from __future__ import annotations

from django import template
from django.utils.html import format_html

register = template.Library()


_NON_PASSATI = object()


@register.simple_tag
def presenti_ids():
    """``{% presenti_ids as pres_ids %}``: una sola lettura per le pagine con molti pallini
    dentro ``{% include ... only %}`` (es. organigramma), da passare a ``pallino_presenza``."""
    try:
        from presenti.services import ids_presenti

        return ids_presenti()
    except Exception:
        return None


@register.simple_tag(takes_context=True)
def pallino_presenza(context, legacy_id, etichetta: bool = False, ids=_NON_PASSATI, stile: bool = True):
    if not legacy_id:
        return ""
    radice = context.dicts[0] if context.dicts else {}
    if ids is _NON_PASSATI:
        cache_ctx = "_presenti_ids"
        if cache_ctx not in radice:
            radice[cache_ctx] = presenti_ids()
        ids = radice[cache_ctx]
    if ids is None or ids == "":
        return ""
    try:
        dentro = int(legacy_id) in ids
    except (TypeError, ValueError):
        return ""
    testo = "In azienda" if dentro else "Fuori"
    css = ""
    if stile and not radice.get("_presenti_stile"):
        # Lo stile viaggia col primo pallino della pagina: il tag funziona in qualunque template.
        # Negli include «only» ripetuti si passa stile=False e la pagina usa {% pallino_presenza_stile %}.
        radice["_presenti_stile"] = True
        css = _STILE
    return format_html(
        '{}<span class="pres-pallino {}" title="{}" aria-label="{}">{}</span>',
        css, "is-dentro" if dentro else "is-fuori", testo, testo,
        format_html("<i></i>{}", testo) if etichetta else format_html("<i></i>"),
    )


_STILE = format_html(
    "<style>{}</style>",
    ".pres-pallino{display:inline-flex;align-items:center;gap:5px;margin-left:6px;vertical-align:middle;"
    "font-size:11.5px;font-weight:700;color:var(--text-mid)}"
    ".pres-pallino i{display:inline-block;width:9px;height:9px;border-radius:50%;background:#94a3b8;"
    "box-shadow:0 0 0 2px var(--surface,#fff)}"
    ".pres-pallino.is-dentro i{background:#16a34a}"
    ".pres-pallino.is-dentro{color:#15803d}"
    "body.theme-dark .pres-pallino.is-dentro{color:#86efac}",
)


@register.simple_tag
def pallino_presenza_stile():
    """Stile dei pallini, una volta per pagina (per i pallini con ``stile=False``)."""
    return _STILE
