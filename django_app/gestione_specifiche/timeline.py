"""Timeline eventi 'umanizzata' per le viste utente (dettaglio, scheda storico).

Nasconde il marcatore interno `auto_approvazione` (resta nelle viste admin) e, sulla riga
di approvazione, mostra la data di record `mod.data_approvazione` invece del timestamp reale
dell'evento immutabile. Non modifica il database: annota solo un attributo di comodo
`ts_display` (senza underscore iniziale, richiesto dai template Django).
"""
from __future__ import annotations

from . import constants as C

TRIGGER_AUTO = "auto_approvazione"
TRIGGER_APPROVAZIONE = "approva_flow_down"


def eventi_umanizzati(spec, mod=None, *, limit=None):
    """Eventi della specifica per la timeline utente.

    - esclude gli eventi `auto_approvazione` (traccia interna, solo admin);
    - annota `ts_display`: per la riga di approvazione (`approva_flow_down` verso
      `in_validita`) = `mod.data_approvazione`; per gli altri = `timestamp` reale.
    """
    qs = spec.eventi.exclude(trigger=TRIGGER_AUTO)
    eventi = list(qs[:limit] if limit else qs)
    data_appr = getattr(mod, "data_approvazione", None) if mod is not None else None
    for e in eventi:
        if data_appr and e.trigger == TRIGGER_APPROVAZIONE and e.stato_a == C.STATO_IN_VALIDITA:
            e.ts_display = data_appr
        else:
            e.ts_display = e.timestamp
    return eventi
