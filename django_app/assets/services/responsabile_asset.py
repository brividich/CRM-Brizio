"""Responsabile di un asset: la persona assegnata o, per gli asset non IT, il caporeparto.

Regola (27/10/2026): un asset non IT (macchine, impianti, carroponti, compressori...)
senza una persona assegnata ha come responsabile il capo del reparto in cui è
installato, «salvo diverse indicazioni». Il capo
si legge dalle copie che ``anagrafica`` tiene allineate al Mansionario
(``AreaAziendale.responsabile_legacy_id``, altrimenti
``Reparto.caporeparto_legacy_id``); il campo ``Asset.reparto`` è testo e si
confronta col nome dell'area o del reparto, senza badare a maiuscole.

Non scrive niente: se cambia il caporeparto cambia anche il responsabile.
Gli asset IT restano come sono, li assegna l'IT a mano. I tipi che rispondono al
reparto sono il complemento dei tipi IT: un tipo nuovo ci rientra da solo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import IT_DEVICE_TYPES, Asset

logger = logging.getLogger(__name__)

TIPI_REPARTO = frozenset(v for v, _label in Asset.TYPE_CHOICES if v not in IT_DEVICE_TYPES)
PREFISSO_REPARTO = "Reparto "  # assegnazione «a un reparto» del form asset


@dataclass(frozen=True)
class Responsabile:
    nome: str
    sotto: str = ""
    da_caporeparto: bool = False
    anagrafica_id: int | None = None


def _norm(testo) -> str:
    return " ".join(str(testo or "").split()).casefold()


def _unita() -> dict[str, tuple[int | None, set[int]]]:
    """Nome di area o reparto, o testo collegato (normalizzato) → (capo, co-capi) come id anagrafica.

    L'area con un responsabile proprio vince sul reparto omonimo; senza segue il
    capo del reparto (e ne eredita i co-capi). Un testo collegato a mano
    (``RepartoAssetCollegato``, Impostazioni › Reparti e capi) vince su tutto.
    """
    from anagrafica.models import AreaAziendale, Reparto

    from ..models import RepartoAssetCollegato

    co_rep: dict[int, set[int]] = {}
    for rid, pid in Reparto.objects.filter(is_active=True, responsabili__isnull=False).values_list(
        "pk", "responsabili"
    ):
        co_rep.setdefault(rid, set()).add(int(pid))
    co_area: dict[int, set[int]] = {}
    for aid, pid in AreaAziendale.objects.filter(is_active=True, responsabili__isnull=False).values_list(
        "pk", "responsabili"
    ):
        co_area.setdefault(aid, set()).add(int(pid))

    per_reparto: dict[int, tuple[int | None, set[int]]] = {}
    risultato: dict[str, tuple[int | None, set[int]]] = {}
    for rid, nome, capo in Reparto.objects.filter(is_active=True).values_list("pk", "nome", "caporeparto_legacy_id"):
        per_reparto[rid] = (int(capo) if capo else None, co_rep.get(rid, set()))
        risultato[_norm(nome)] = per_reparto[rid]
    per_area: dict[int, tuple[int | None, set[int]]] = {}
    for aid, nome, resp, rid in AreaAziendale.objects.filter(is_active=True).values_list(
        "pk", "nome", "responsabile_legacy_id", "reparto_id"
    ):
        if resp:
            per_area[aid] = (int(resp), co_area.get(aid, set()))
        else:
            capo, co = per_reparto.get(rid, (None, set()))
            per_area[aid] = (capo, co | co_area.get(aid, set()))
        risultato[_norm(nome)] = per_area[aid]
    for chiave, rid, aid in RepartoAssetCollegato.objects.values_list("chiave", "reparto_id", "area_id"):
        unita = per_area.get(aid) if aid else per_reparto.get(rid)
        if unita is not None:
            risultato[chiave] = unita
    return risultato


def capi_per_reparto() -> dict[str, tuple[int, str]]:
    """Nome di area o reparto, o testo collegato (normalizzato) → (id anagrafica, nome) del capo."""
    try:
        ids = {chiave: capo for chiave, (capo, _co) in _unita().items() if capo}
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


def persone_per_reparto() -> dict[str, set[int]]:
    """Come :func:`capi_per_reparto`, ma con capo e co-capi (id anagrafica): chi vede le macchine del reparto."""
    try:
        return {
            chiave: ({capo} if capo else set()) | co
            for chiave, (capo, co) in _unita().items()
            if capo or co
        }
    except Exception:
        logger.debug("Capi e co-capi per reparto non risolti", exc_info=True)
        return {}


def chiave_reparto(testo) -> str:
    """Il testo di un reparto come lo confrontano capi e collegamenti."""
    return _norm(testo)


def _assegnato_a_persona(asset: Asset) -> bool:
    nome = (asset.assignment_to or "").strip()
    return bool(asset.assigned_legacy_user_id) or bool(nome and not nome.startswith(PREFISSO_REPARTO))


def responsabile(asset: Asset, capi: dict[str, tuple[int, str]] | None = None) -> Responsabile | None:
    """Chi risponde dell'asset, o ``None`` se nessuno."""
    if _assegnato_a_persona(asset) or asset.asset_type not in TIPI_REPARTO:
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


def utenti_responsabili(asset: Asset) -> set[int]:
    """``utenti.id`` di capo e co-capi del reparto di un asset non IT senza persona.

    Per i permessi «propri»: i co-capi (Persone › Reparti, aree e capi) vedono le
    macchine del reparto come il capo. Vuoto se l'asset è di una persona o è IT.
    """
    if _assegnato_a_persona(asset) or asset.asset_type not in TIPI_REPARTO:
        return set()
    reparto = (asset.reparto or asset.assignment_reparto or "").strip()
    persone = persone_per_reparto().get(_norm(reparto), set()) if reparto else set()
    if not persone:
        return set()
    try:
        from core.legacy_models import AnagraficaDipendente

        utenti = AnagraficaDipendente.objects.filter(id__in=persone).values_list("utente_id", flat=True)
        return {int(u) for u in utenti if u}
    except Exception:
        logger.debug("Utenti dei capi del reparto non risolti", exc_info=True)
        return set()


def applica(assets) -> None:
    """Mette ``asset.responsabile`` su ogni asset della pagina (una sola lettura dei capi)."""
    assets = list(assets)
    capi = capi_per_reparto() if any(a.asset_type in TIPI_REPARTO for a in assets) else {}
    for asset in assets:
        asset.responsabile = responsabile(asset, capi)
