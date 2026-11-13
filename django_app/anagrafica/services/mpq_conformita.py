"""MOD.128 MPQ — requisiti del processo uguali per tutti (contratto, audit, certificato…).

Sono attestazioni a livello **processo** (``RequisitoQualifica``): stato e scadenza
del requisito valgono per tutti gli abilitati. I requisiti **per persona** (corsi,
visite, qualifiche, DPI, test visivi…) sono in «Cosa serve a una persona» e li
valuta :func:`mpq_persone.stato_persona`, che include anche questi: è l'unica
funzione da usare per dire se una persona è qualificata sul processo.
"""
from __future__ import annotations

from django.utils import timezone

# Stessa soglia di «In scadenza» delle persone (mpq_persone.SOGLIA_IN_SCADENZA).
_SOGLIA_WARN = 30


def verifica_requisiti(processo, legacy_id: int, *, oggi=None) -> dict:
    """Requisiti del processo uguali per tutti, letti per una persona (legacy_anagrafica_id).

    Ritorna ``{"esito", "voci": [{"tipo","nome","stato"}], "n_mancanti"}`` dove
    ``stato`` ∈ {ok, in_scadenza, scaduto, mancante, na} e ``esito`` ∈
    {ok, warn, incompleto, ko, nessuno}.
    """
    oggi = oggi or timezone.localdate()
    voci: list[dict] = []

    # Requisiti generici tipizzati (1.14): a livello processo, stato/scadenza propri.
    # Sono valutati sul requisito (uguale per tutti gli abilitati), non per-persona.
    from ..models import RequisitoQualifica
    for req in processo.requisiti.filter(attivo=True):
        scaduto = (
            req.stato == RequisitoQualifica.STATO_SCADUTO
            or (req.data_scadenza is not None and req.data_scadenza < oggi)
        )
        if req.stato == RequisitoQualifica.STATO_NON_APPLICABILE:
            stato = "na"
        elif scaduto:
            stato = "scaduto"
        elif req.stato == RequisitoQualifica.STATO_SODDISFATTO:
            if req.data_scadenza is not None and (req.data_scadenza - oggi).days <= _SOGLIA_WARN:
                stato = "in_scadenza"
            else:
                stato = "ok"
        else:  # DA_VERIFICARE
            stato = "mancante"
        voci.append({
            "tipo": req.get_tipo_display(), "nome": req.descrizione,
            "stato": stato, "obbligatorio": req.obbligatorio,
        })

    # Le voci non obbligatorie sono informative: compaiono ma non degradano l'esito.
    stati_obbl = [v["stato"] for v in voci if v.get("obbligatorio", True)]
    if not voci:
        esito = "nessuno"
    elif "scaduto" in stati_obbl:
        esito = "ko"
    elif "mancante" in stati_obbl:
        esito = "incompleto"
    elif "in_scadenza" in stati_obbl:
        esito = "warn"
    else:
        esito = "ok"
    n_mancanti = sum(
        1 for v in voci if v.get("obbligatorio", True) and v["stato"] in ("scaduto", "mancante")
    )
    return {"esito": esito, "voci": voci, "n_mancanti": n_mancanti}
