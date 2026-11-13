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
    return {
        legacy_id: dato["requisiti"]
        for legacy_id, dato in requisiti_processo_dettaglio(legacy_ids).items()
    }


def requisiti_processo_dettaglio(legacy_ids) -> dict[int, dict]:
    """Come sopra, ma con l'**origine** di ogni requisito (nome del processo).

    ``{legacy_id: {"requisiti": {...}, "origini": {(dominio, pk): [etichetta]}}}``.
    Serve al libretto sanitario, che deve dire perché un obbligo è dovuto.
    """
    from ..models_mpq import AbilitazioneProcesso

    out: dict[int, dict] = {}
    if not legacy_ids:
        return out
    abil = (
        AbilitazioneProcesso.objects
        .filter(legacy_anagrafica_id__in=list(legacy_ids),
                stato=AbilitazioneProcesso.STATO_ATTIVA)
        .exclude(legacy_anagrafica_id=0)
        .select_related("processo")
        .prefetch_related("ruoli_processo")
    )
    from .mpq_persone import _RELATED, frequenze_corsi, obblighi_richiesti

    req_cache: dict[int, list] = {}
    for ab in abil:
        dato = out.setdefault(ab.legacy_anagrafica_id, {
            "requisiti": {"dpi": [], "visite": [], "corsi": []},
            "origini": {},
            "frequenze_corsi": {},
        })
        d = dato["requisiti"]
        p = ab.processo
        etichetta = f"Processo «{p}»"
        if p.pk not in req_cache:
            req_cache[p.pk] = list(
                p.requisiti_persona.filter(attivo=True)
                .select_related(*_RELATED).prefetch_related("ruoli")
            )
        obblighi = obblighi_richiesti(ab, req_cache[p.pk])
        # Frequenza più stretta chiesta dai processi per ogni corso (motore Formazione).
        for corso_id, freq in frequenze_corsi(ab, req_cache[p.pk]).items():
            att = dato["frequenze_corsi"].get(corso_id)
            if att is None or freq[0] < att[0]:
                dato["frequenze_corsi"][corso_id] = freq
        for dominio in ("dpi", "visite", "corsi"):
            voci = obblighi[dominio]
            for obj in voci:
                if obj not in d[dominio]:
                    d[dominio].append(obj)
                origine = dato["origini"].setdefault((dominio, obj.pk), [])
                if etichetta not in origine:
                    origine.append(etichetta)
    return out
