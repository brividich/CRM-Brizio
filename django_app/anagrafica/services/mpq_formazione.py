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
    out = set()
    if proc_ids:
        out = {
            int(lid) for lid in AbilitazioneProcesso.objects
            .filter(processo_id__in=proc_ids, stato=AbilitazioneProcesso.STATO_ATTIVA)
            .exclude(legacy_anagrafica_id=0)
            .values_list("legacy_anagrafica_id", flat=True)
        }
    # Requisiti persona per ruolo (13/11): il corso vale solo per i ruoli indicati.
    out |= {lid for lid, _c in _coppie_da_requisiti_persona(corso_id=corso_id)}
    return out


def _coppie_da_requisiti_persona(*, corso_id=None, legacy_id=None):
    """(legacy_id, TrainingCourse) dai requisiti persona bloccanti di tipo corso."""
    from ..models_mpq import AbilitazioneProcesso, RequisitoPersona
    from .mpq_persone import corsi_visite_richiesti

    reqs = (RequisitoPersona.objects
            .filter(attivo=True, bloccante=True, tipo=RequisitoPersona.TIPO_CORSO,
                    corso__isnull=False)
            .select_related("corso").prefetch_related("ruoli"))
    if corso_id is not None:
        reqs = reqs.filter(corso_id=corso_id)
    per_processo: dict[int, list] = {}
    for r in reqs:
        per_processo.setdefault(r.processo_id, []).append(r)
    out = []
    if not per_processo:
        return out
    abil = (AbilitazioneProcesso.objects
            .filter(processo_id__in=list(per_processo), stato=AbilitazioneProcesso.STATO_ATTIVA)
            .exclude(legacy_anagrafica_id=0).prefetch_related("ruoli_processo"))
    if legacy_id is not None:
        abil = abil.filter(legacy_anagrafica_id=legacy_id)
    for ab in abil:
        corsi, _visite = corsi_visite_richiesti(ab, per_processo[ab.processo_id])
        for c in corsi:
            out.append((int(ab.legacy_anagrafica_id), c))
    return out


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
    gia = {(lid, c.pk) for lid, c in out}
    for lid, c in _coppie_da_requisiti_persona(corso_id=corso_id, legacy_id=legacy_id):
        if (lid, c.pk) not in gia:
            gia.add((lid, c.pk))
            out.append((lid, c))
    return out
