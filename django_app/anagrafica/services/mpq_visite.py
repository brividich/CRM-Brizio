"""MOD.128 MPQ — bidirezionalità con le Visite mediche.

Le visite richieste da un processo («Cosa serve a una persona», tipo visita,
bloccante, per i ruoli della persona) sono un **obbligo reale**: entrano nello
scadenzario/stato visite (``services.visite``) accanto a quelle dei ruoli operativi.
Fonte unica: :func:`mpq_idoneita.requisiti_processo_dettaglio`.
"""
from __future__ import annotations


def tipi_visita_richiesti_da_processo(legacy_id) -> set[int]:
    """id dei ``TipoVisitaMedica`` richiesti dai processi cui la persona è abilitata (ATTIVA)."""
    from .mpq_idoneita import requisiti_processo_dettaglio

    dato = requisiti_processo_dettaglio([legacy_id]).get(legacy_id)
    if not dato:
        return set()
    return {int(t.pk) for t in dato["requisiti"]["visite"]}


def legacy_ids_per_visita(tipo_visita) -> tuple[bool, set[int]]:
    """(il tipo è chiesto da almeno un processo, persone tenute a farlo).

    Persone = abilitazioni ATTIVE di interni i cui ruoli rientrano in un requisito
    persona bloccante di tipo visita su quel tipo (vuoto = tutti i ruoli).
    """
    from ..models_mpq import AbilitazioneProcesso, RequisitoPersona
    from .mpq_persone import obblighi_richiesti

    reqs = list(RequisitoPersona.objects
                .filter(attivo=True, bloccante=True, gruppo_alternativo="", tipo=RequisitoPersona.TIPO_VISITA,
                        tipo_visita=tipo_visita)
                .select_related("tipo_visita").prefetch_related("ruoli"))
    if not reqs:
        return False, set()
    per_processo: dict[int, list] = {}
    for r in reqs:
        per_processo.setdefault(r.processo_id, []).append(r)
    out: set[int] = set()
    for ab in (AbilitazioneProcesso.objects
               .filter(processo_id__in=list(per_processo), stato=AbilitazioneProcesso.STATO_ATTIVA)
               .exclude(legacy_anagrafica_id=0).prefetch_related("ruoli_processo")):
        if obblighi_richiesti(ab, per_processo[ab.processo_id])["visite"]:
            out.add(int(ab.legacy_anagrafica_id))
    return True, out
