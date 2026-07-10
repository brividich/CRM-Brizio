"""Template tag del modulo Suggestion Corner.

`pdca_immagine`: mappa lo stato FSM di una segnalazione sull'immagine del ciclo
PDCA (cerchio Plan-Do-Check-Act che si colora per fase completata). Le immagini
stanno in `static/suggestion_corner/pdca/`.
"""
from __future__ import annotations

from django import template

register = template.Library()

# Stato FSM -> file immagine (percorso relativo agli static).
# off = nessuna fase completata; P = Plan; PDC = Plan+Do+Check;
# PDCA = ciclo completo. (PDA disponibile per combinazioni legacy P+D+Act.)
_MAPPA = {
    "INSERITA": "off.png",
    "DA_CLASSIFICARE": "off.png",
    "CLASSIFICATA": "off.png",
    "PLAN_DEFINITO": "P.png",
    "DO_IN_CORSO": "P.png",
    "DO_COMPLETATO": "P.png",
    "CHECK_IN_CORSO": "P.png",
    "CHECK_COMPLETATO": "PDC.png",
    "ACT_INSERITO": "PDCA-Circle-Color.png",
    "CHIUSA": "PDCA-Circle-Color.png",
}

_BASE = "suggestion_corner/pdca/"


@register.filter
def pdca_immagine(stato: str) -> str:
    """Percorso static dell'immagine PDCA per lo stato dato (fallback: off)."""
    return _BASE + _MAPPA.get(str(stato or ""), "off.png")


@register.filter
def pdca_alt(stato: str) -> str:
    """Testo alternativo/descrizione della fase PDCA raggiunta."""
    file = _MAPPA.get(str(stato or ""), "off.png")
    return {
        "off.png": "PDCA: non avviato",
        "P.png": "PDCA: Plan",
        "PDC.png": "PDCA: Plan-Do-Check",
        "PDA.png": "PDCA: Plan-Do-Act",
        "PDCA-Circle-Color.png": "PDCA: ciclo completo",
    }.get(file, "PDCA")
