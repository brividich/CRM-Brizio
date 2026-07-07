"""MOD.128 MPQ — bidirezionalità con la Formazione.

Rende i corsi dichiarati come **requisito** su un ``ProcessoQualificato`` un
**obbligo reale** nel motore formazione: chi è abilitato (stato ATTIVA, dipendente
interno) a un processo che richiede un corso è "tenuto" a quel corso — quindi
compare nella **copertura/gap** (``training_eligibility.candidati_corso``) e nel
**cache scadenze** (``training_deadline_service.refresh_deadlines``), esattamente
come se ci fosse una ``TrainingRequirementRule``.

Helper condiviso, iniettato nei due consumatori esistenti (nessuna logica
duplicata). Sola lettura sui modelli MPQ.
"""
from __future__ import annotations


def legacy_ids_richiesti_da_processo(corso_id) -> set[int]:
    """``legacy_id`` (interni, abilitazione ATTIVA) tenuti al corso via MOD.128."""
    from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato

    proc_ids = list(
        ProcessoQualificato.objects
        .filter(corsi_richiesti__id=corso_id)
        .values_list("id", flat=True)
    )
    if not proc_ids:
        return set()
    return {
        int(lid) for lid in AbilitazioneProcesso.objects
        .filter(processo_id__in=proc_ids, stato=AbilitazioneProcesso.STATO_ATTIVA)
        .exclude(legacy_anagrafica_id=0)
        .values_list("legacy_anagrafica_id", flat=True)
    }


def coppie_richieste_da_processo(*, corso_id=None, legacy_id=None):
    """Lista di ``(legacy_id, TrainingCourse)`` richiesti dai processi.

    Per ``refresh_deadlines``: opzionalmente ristretta a un corso/dipendente
    (rebuild parziale). Solo abilitazioni ATTIVA di dipendenti interni.
    """
    from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato

    out = []
    procs = (ProcessoQualificato.objects
             .exclude(corsi_richiesti=None)
             .prefetch_related("corsi_richiesti"))
    for p in procs:
        corsi = [c for c in p.corsi_richiesti.all()
                 if corso_id is None or c.pk == corso_id]
        if not corsi:
            continue
        ab_qs = (p.abilitazioni
                 .filter(stato=AbilitazioneProcesso.STATO_ATTIVA)
                 .exclude(legacy_anagrafica_id=0))
        if legacy_id is not None:
            ab_qs = ab_qs.filter(legacy_anagrafica_id=legacy_id)
        for lid in set(ab_qs.values_list("legacy_anagrafica_id", flat=True)):
            for c in corsi:
                out.append((int(lid), c))
    return out
