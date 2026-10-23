"""Il ruolo in azienda di un utente del portale, per mostrarlo accanto agli accessi.

Una persona ha un ruolo solo: quello in azienda (organigramma, ``RuoloOperativo``).
I ruoli del portale sono gli «accessi» che quel ruolo concede. Le pagine che
mostravano il ruolo del portale come «Ruolo» usano questa funzione per dire
«Ruolo in azienda: CAR · Caporeparto · accessi: Caporeparto».

Conta il ruolo principale in corso; senza principale, il primo ruolo in corso
che alimenta la scheda. Gli id sono ``utenti.id``.
"""
from __future__ import annotations

import logging

from django.db import DatabaseError

logger = logging.getLogger(__name__)


def ruoli_in_azienda(utenti_ids) -> dict[int, str]:
    """{utenti.id: etichetta del ruolo in azienda} (vuoto se la persona non ne ha)."""
    from core.legacy_models import AnagraficaDipendente
    from core.permessi.team import _assegnazioni_attive

    ids = [int(u) for u in utenti_ids or [] if u]
    if not ids:
        return {}
    try:
        utente_per_anagrafica = dict(AnagraficaDipendente.objects.filter(utente_id__in=ids)
                                     .values_list("id", "utente_id"))
        if not utente_per_anagrafica:
            return {}
        assegnazioni = list(_assegnazioni_attive().filter(legacy_anagrafica_id__in=list(utente_per_anagrafica))
                            .select_related("ruolo", "ruolo__ambito"))
    except DatabaseError:
        logger.warning("ruolo in azienda non leggibile", exc_info=True)
        return {}
    scelto: dict[int, tuple[int, str]] = {}
    for a in assegnazioni:
        if not a.ruolo.alimenta_ruolo_principale:
            continue  # incarichi e altri organigrammi (45001, 27001) non sono «il ruolo»
        uid = utente_per_anagrafica.get(a.legacy_anagrafica_id)
        if not uid:
            continue
        peso = 0 if a.tipologia == "PRINCIPALE" else 1
        if uid not in scelto or peso < scelto[uid][0]:
            scelto[uid] = (peso, a.ruolo.etichetta)
    return {uid: etichetta for uid, (_peso, etichetta) in scelto.items()}
