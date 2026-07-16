"""Organigramma ad albero: gerarchia tra RUOLI, persone come foglie.

La gerarchia è SEMPRE tra :class:`RuoloOperativo` (campo ``riporta_a``), mai tra
persone: i dipendenti che ricoprono un ruolo sono foglie titolari del nodo di
quel ruolo, senza sotto-gerarchia. Le radici sono i ruoli con ``riporta_a IS
NULL``. La costruzione ricorsiva è protetta contro i cicli (difesa: insieme dei
ruoli già visitati lungo il percorso).
"""
from __future__ import annotations

from anagrafica.models import RuoloOperativo
from core.operational_roles import get_anagrafica_ids_for_role


def _nome_map(legacy_ids) -> dict[int, str]:
    """``legacy_anagrafica_id`` → "Cognome Nome" (best-effort dal DB legacy).

    Usa :func:`core.legacy_anagrafica.fetch_anagrafica_rows`; se la tabella
    legacy non è disponibile (es. suite di test) ritorna nomi vuoti senza
    rompere: l'albero resta valido sui soli id.
    """
    ids = sorted({int(i) for i in legacy_ids if i})
    if not ids:
        return {}
    from core.legacy_anagrafica import fetch_anagrafica_rows

    result: dict[int, str] = {}
    for row in fetch_anagrafica_rows(ids=ids):
        try:
            rid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            rid = 0
        if not rid:
            continue
        nome = f"{row.get('cognome') or ''} {row.get('nome') or ''}".strip()
        result[rid] = nome
    return result


def build_ruolo_albero() -> list[dict]:
    """Albero dei ruoli: lista di nodi radice.

    Nodo: ``{"ruolo": RuoloOperativo, "titolari": [{"legacy_id", "nome"}],
    "figli": [nodo...]}``. Radici = ruoli attivi con ``riporta_a IS NULL``.
    """
    ruoli = list(RuoloOperativo.objects.filter(is_active=True).order_by("nome"))

    figli_di: dict[int | None, list[RuoloOperativo]] = {}
    for r in ruoli:
        figli_di.setdefault(r.riporta_a_id, []).append(r)

    titolari_ids: dict[int, list[int]] = {
        r.id: get_anagrafica_ids_for_role(r.id) for r in ruoli
    }
    tutti_ids = {lid for ids in titolari_ids.values() for lid in ids}
    nomi = _nome_map(tutti_ids)

    def _costruisci(ruolo: RuoloOperativo, visitati: frozenset[int]) -> dict | None:
        if ruolo.id in visitati:
            return None  # difesa anti-ciclo
        visitati = visitati | {ruolo.id}
        titolari = [
            {"legacy_id": lid, "nome": nomi.get(lid, "")}
            for lid in titolari_ids.get(ruolo.id, [])
        ]
        figli: list[dict] = []
        for figlio in figli_di.get(ruolo.id, []):
            nodo = _costruisci(figlio, visitati)
            if nodo is not None:
                figli.append(nodo)
        return {"ruolo": ruolo, "titolari": titolari, "figli": figli}

    radici: list[dict] = []
    for r in figli_di.get(None, []):
        nodo = _costruisci(r, frozenset())
        if nodo is not None:
            radici.append(nodo)
    return radici
