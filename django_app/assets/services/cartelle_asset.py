"""Scelte sulle cartelle documento di un singolo asset.

Le cartelle di categoria valgono per tutti gli asset della categoria; qui si
registra, per un asset, cosa cambia rispetto a quella regola:

- ``senza_categoria``: l'asset non usa le cartelle della categoria (solo le 3 di
  base, le sue e quelle aggiunte una per una);
- ``tolte``: cartelle di categoria tolte da questo asset;
- ``aggiunte``: cartelle di categoria aggiunte a questo asset (le facoltative,
  o tutte quando ``senza_categoria``).

Una cartella che contiene documenti resta sempre visibile: nessun file sparisce
dalla scheda. Le scelte stanno in ``Asset.extra_columns[CHIAVE]``.
"""
from __future__ import annotations

CHIAVE = "_cartelle_documenti"


def scelte(asset) -> dict:
    extra = asset.extra_columns if isinstance(getattr(asset, "extra_columns", None), dict) else {}
    raw = extra.get(CHIAVE) if isinstance(extra.get(CHIAVE), dict) else {}
    return {
        "senza_categoria": bool(raw.get("senza_categoria")),
        "tolte": {str(s) for s in raw.get("tolte") or [] if s},
        "aggiunte": {str(s) for s in raw.get("aggiunte") or [] if s},
    }


def con_scelte(extra: dict | None, valori: dict) -> dict:
    """``extra_columns`` aggiornato con ``valori`` (vuoto = chiave tolta)."""
    nuovo = dict(extra or {})
    pulito = {
        "senza_categoria": bool(valori.get("senza_categoria")),
        "tolte": sorted(valori.get("tolte") or []),
        "aggiunte": sorted(valori.get("aggiunte") or []),
    }
    if not pulito["senza_categoria"] and not pulito["tolte"] and not pulito["aggiunte"]:
        nuovo.pop(CHIAVE, None)
    else:
        nuovo[CHIAVE] = pulito
    return nuovo


def salva(asset, valori: dict) -> None:
    from ..models import Asset

    asset.extra_columns = con_scelte(asset.extra_columns if isinstance(asset.extra_columns, dict) else {}, valori)
    Asset.objects.filter(pk=asset.pk).update(extra_columns=asset.extra_columns)


def visibile(folder, sc: dict, usata: bool) -> bool:
    """La cartella di categoria compare sull'asset?"""
    if usata or folder.slug in sc["aggiunte"]:
        return True
    if folder.slug in sc["tolte"] or sc["senza_categoria"] or folder.facoltativa:
        return False
    return True


def motivo_nascosta(folder, sc: dict) -> str:
    if folder.slug in sc["tolte"]:
        return "tolta da questo asset"
    if sc["senza_categoria"]:
        return "l'asset non usa le cartelle della categoria"
    return "facoltativa"
