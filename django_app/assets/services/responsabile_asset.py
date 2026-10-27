"""Responsabile di un asset: la persona assegnata o, per le macchine di produzione, il caporeparto.

Regola (27/10/2026): una macchina CNC o di lavoro senza una persona assegnata ha
come responsabile il capo del suo reparto, «salvo diverse indicazioni». Il capo
si legge dalle copie che ``anagrafica`` tiene allineate al Mansionario
(``AreaAziendale.responsabile_legacy_id``, altrimenti
``Reparto.caporeparto_legacy_id``); il campo ``Asset.reparto`` è testo e si
confronta col nome dell'area o del reparto, senza badare a maiuscole.

Non scrive niente: se cambia il caporeparto cambia anche il responsabile.
Gli asset IT restano come sono, li assegna l'IT a mano.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import Asset

logger = logging.getLogger(__name__)

TIPI_PRODUZIONE = {Asset.TYPE_CNC, Asset.TYPE_WORK_MACHINE}
PREFISSO_REPARTO = "Reparto "  # assegnazione «a un reparto» del form asset


@dataclass(frozen=True)
class Responsabile:
    nome: str
    sotto: str = ""
    da_caporeparto: bool = False
    anagrafica_id: int | None = None


def _norm(testo) -> str:
    return " ".join(str(testo or "").split()).casefold()


def capi_per_reparto() -> dict[str, tuple[int, str]]:
    """Nome di area o reparto (normalizzato) → (id anagrafica, nome) del capo."""
    try:
        from anagrafica.models import AreaAziendale, Reparto

        ids: dict[str, int] = {}
        capi_rep: dict[int, int] = {}
        for rid, nome, capo in Reparto.objects.filter(is_active=True).values_list(
            "pk", "nome", "caporeparto_legacy_id"
        ):
            if capo:
                capi_rep[rid] = int(capo)
                ids[_norm(nome)] = int(capo)
        # L'area vince sul reparto omonimo; senza responsabile proprio segue il reparto.
        for nome, resp, rid in AreaAziendale.objects.filter(is_active=True).values_list(
            "nome", "responsabile_legacy_id", "reparto_id"
        ):
            capo = int(resp) if resp else capi_rep.get(rid)
            if capo:
                ids[_norm(nome)] = capo
        if not ids:
            return {}
        from core import naming
        from core.legacy_anagrafica import fetch_anagrafica_rows

        nomi = {
            int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=sorted(set(ids.values())))
        }
        return {chiave: (pid, nomi[pid]) for chiave, pid in ids.items() if nomi.get(pid)}
    except Exception:  # tabelle legacy: senza capo si mostra «Non assegnato», mai un 500
        logger.debug("Capi per reparto non risolti", exc_info=True)
        return {}


def _assegnato_a_persona(asset: Asset) -> bool:
    nome = (asset.assignment_to or "").strip()
    return bool(asset.assigned_legacy_user_id) or bool(nome and not nome.startswith(PREFISSO_REPARTO))


def responsabile(asset: Asset, capi: dict[str, tuple[int, str]] | None = None) -> Responsabile | None:
    """Chi risponde dell'asset, o ``None`` se nessuno."""
    if _assegnato_a_persona(asset) or asset.asset_type not in TIPI_PRODUZIONE:
        if asset.assignment_to:
            return Responsabile(asset.assignment_to.strip(), (asset.assignment_reparto or "").strip())
        return None
    reparto = (asset.reparto or asset.assignment_reparto or "").strip()
    capo = (capi if capi is not None else capi_per_reparto()).get(_norm(reparto)) if reparto else None
    if capo:
        return Responsabile(capo[1], f"Caporeparto {reparto}", True, capo[0])
    if asset.assignment_to:
        return Responsabile(asset.assignment_to.strip(), (asset.assignment_reparto or "").strip())
    return None


def utente_responsabile(asset: Asset) -> int | None:
    """``utenti.id`` del caporeparto che risponde dell'asset (per i permessi «propri/team»)."""
    resp = responsabile(asset)
    if resp is None or not resp.da_caporeparto:
        return None
    try:
        from core.legacy_models import AnagraficaDipendente

        utente = (
            AnagraficaDipendente.objects.filter(id=resp.anagrafica_id)
            .values_list("utente_id", flat=True).first()
        )
    except Exception:
        logger.debug("Utente del caporeparto non risolto", exc_info=True)
        return None
    return int(utente) if utente else None


def applica(assets) -> None:
    """Mette ``asset.responsabile`` su ogni asset della pagina (una sola lettura dei capi)."""
    assets = list(assets)
    capi = capi_per_reparto() if any(a.asset_type in TIPI_PRODUZIONE for a in assets) else {}
    for asset in assets:
        asset.responsabile = responsabile(asset, capi)
