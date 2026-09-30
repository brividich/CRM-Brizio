"""Risoluzione legacy_anagrafica_id -> nominativo/reparto per i report.

Una query per report (non una per riga). Fail-soft: se la tabella legacy non e'
raggiungibile il report resta leggibile con l'identificativo al posto del nome.
Nessun dato oltre nominativo e reparto: minimizzazione (GDPR).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Persona:
    legacy_id: int
    nominativo: str
    reparto: str
    cessato: bool = False


def persone(legacy_ids: Iterable[int | None], *, today: date | None = None) -> dict[int, Persona]:
    ids = sorted({int(x) for x in legacy_ids if x})
    if not ids:
        return {}
    nomi: dict[int, tuple[str, str]] = {}
    try:
        from core.legacy_models import AnagraficaDipendente

        for row in AnagraficaDipendente.objects.filter(pk__in=ids).values("id", "nome", "cognome", "reparto"):
            nominativo = f"{(row.get('cognome') or '').strip()} {(row.get('nome') or '').strip()}".strip()
            nomi[int(row["id"])] = (nominativo, (row.get("reparto") or "").strip())
    except Exception:
        logger.warning("report_conformita: anagrafica legacy non leggibile", exc_info=True)

    cessati: set[int] = set()
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale

        qs = DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id__in=ids, data_cessazione__isnull=False
        )
        if today is not None:
            qs = qs.filter(data_cessazione__lt=today)
        cessati = {int(x) for x in qs.values_list("legacy_anagrafica_id", flat=True)}
    except Exception:
        logger.warning("report_conformita: dati aziendali non leggibili", exc_info=True)

    out: dict[int, Persona] = {}
    for legacy_id in ids:
        nominativo, reparto = nomi.get(legacy_id, ("", ""))
        out[legacy_id] = Persona(
            legacy_id=legacy_id,
            nominativo=nominativo or f"Dipendente #{legacy_id}",
            reparto=reparto,
            cessato=legacy_id in cessati,
        )
    return out


def cessati_ids(today: date) -> set[int]:
    """legacy_anagrafica_id dei dipendenti cessati (data_cessazione <= oggi)."""
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale

        return {
            int(x)
            for x in DipendenteAnagraficaAziendale.objects.filter(
                data_cessazione__isnull=False, data_cessazione__lte=today
            ).values_list("legacy_anagrafica_id", flat=True)
            if x
        }
    except Exception:
        logger.warning("report_conformita: cessati non leggibili", exc_info=True)
        return set()
