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
