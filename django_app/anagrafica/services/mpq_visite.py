"""MOD.128 MPQ — bidirezionalità con le Visite mediche.

Rende le visite dichiarate come **requisito** su un ``ProcessoQualificato`` un
**obbligo reale**: chi è abilitato (stato ATTIVA) a un processo che richiede una
visita è tenuto a quella visita, quindi essa entra nel suo **scadenzario/stato
visite** (``services.visite.tipi_visita_richiesti_per_dipendente``) accanto a
quelle derivate dai ruoli operativi. Sola lettura sui modelli MPQ.
"""
from __future__ import annotations


def tipi_visita_richiesti_da_processo(legacy_id) -> set[int]:
    """id dei ``TipoVisitaMedica`` richiesti dai processi cui la persona è
    abilitata (stato ATTIVA)."""
    from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato

    proc_ids = list(
        AbilitazioneProcesso.objects
        .filter(legacy_anagrafica_id=legacy_id, stato=AbilitazioneProcesso.STATO_ATTIVA)
        .values_list("processo_id", flat=True)
    )
    if not proc_ids:
        return set()
    ids = (
        ProcessoQualificato.objects
        .filter(id__in=proc_ids)
        .values_list("visite_richieste__id", flat=True)
    )
    return {int(i) for i in ids if i is not None}
