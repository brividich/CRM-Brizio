"""Persone escluse dai conteggi dell'organico.

Alcune persone vanno tenute in anagrafica (amministratore delegato, RSPP
esterno, consulenti) ma non devono pesare su persone in forza, turnover,
organico per reparto e indici infortuni. La scelta e' il flag
``DipendenteAnagraficaAziendale.escluso_dai_conteggi``: questo modulo e'
l'unico punto da cui i contatori basati sulle righe legacy lo leggono (la
reportistica lo legge da ``reportistica.dati.Dipendente.escluso_conteggi``).

Le persone escluse restano in elenchi, scadenze, formazione, visite e DPI.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def esclusi_dai_conteggi_ids() -> set[int]:
    """Id legacy delle schede con «Escludi dai conteggi dell'organico»."""
    from ..models import DipendenteAnagraficaAziendale

    try:
        return set(
            DipendenteAnagraficaAziendale.objects.filter(escluso_dai_conteggi=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    except Exception:
        logger.warning("conteggi organico: esclusioni non leggibili", exc_info=True)
        return set()


def _ids_riga(row: dict) -> set[int]:
    ids = {int(row.get("id") or 0)}
    ids |= {int(x or 0) for x in (row.get("_merged_ids") or [])}
    ids.discard(0)
    return ids


def righe_in_organico(rows: list[dict], esclusi: set[int] | None = None) -> list[dict]:
    """Righe anagrafica legacy senza le persone escluse (anche via id fusi)."""
    esclusi = esclusi_dai_conteggi_ids() if esclusi is None else esclusi
    if not esclusi:
        return list(rows)
    return [r for r in rows if not (_ids_riga(r) & esclusi)]
