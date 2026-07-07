"""MOD.128 MPQ — requisiti di processo nell'idoneità unificata.

Espone, per un insieme di dipendenti, i requisiti (DPI / visite / corsi) derivati
dai **processi qualificati** cui sono abilitati (stato ATTIVA). Serve a estendere
il resolver di idoneità esistente (``conformita._idoneita_batch``) così che i
requisiti dichiarati sul processo si sommino a quelli della mansione di rischio —
in particolare rende i **DPI** richiesti dal processo un obbligo reale nel
semaforo idoneità (oltre a rinforzare visite/corsi). Sola lettura sui modelli MPQ.
"""
from __future__ import annotations


def requisiti_processo_per_legacy(legacy_ids) -> dict[int, dict[str, list]]:
    """``{legacy_id: {"dpi": [...], "visite": [...], "corsi": [...]}}`` dai processi
    a cui la persona è abilitata (ATTIVA, interna)."""
    from ..models_mpq import AbilitazioneProcesso

    out: dict[int, dict[str, list]] = {}
    if not legacy_ids:
        return out
    abil = (
        AbilitazioneProcesso.objects
        .filter(legacy_anagrafica_id__in=list(legacy_ids),
                stato=AbilitazioneProcesso.STATO_ATTIVA)
        .exclude(legacy_anagrafica_id=0)
        .select_related("processo")
        .prefetch_related("processo__dpi_richiesti",
                          "processo__visite_richieste",
                          "processo__corsi_richiesti")
    )
    for ab in abil:
        d = out.setdefault(ab.legacy_anagrafica_id,
                           {"dpi": [], "visite": [], "corsi": []})
        p = ab.processo
        d["dpi"].extend(p.dpi_richiesti.all())
        d["visite"].extend(p.visite_richieste.all())
        d["corsi"].extend(p.corsi_richiesti.all())
    return out
