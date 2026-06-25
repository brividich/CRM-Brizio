"""Risoluzione codice-officina del foglio (MZ5, DM3...) -> assets.Asset.

I codici del foglio NON hanno un campo unico autorevole sugli asset: stanno parte
in `asset_tag` (`CNC-DM3-12280000463`, `CNC-MZ5153592`), parte nel `name`
(`DM3 - DMG Mori DMC 85`, `MZ2 - MAZAK H-800`), con formati incoerenti. Questa
cascata risolve quel che e' risolvibile con confidenza e lascia il resto a una
tabella alias manuale (vedi modello MacchinaAlias) + report dei non mappati.

Funzioni pure: lavorano su oggetti con attributi `asset_tag`/`name` (Asset reale o
qualunque stub), nessuna query qui dentro.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Codice = 1-4 lettere seguite da 1-3 cifre (DM3, DM11, MZ5, A12...).
_RE_TAG_CODE = re.compile(r"^CNC-([A-Za-z]{1,4}\d{1,3})-")
_RE_NAME_CODE = re.compile(r"^\s*([A-Za-z]{1,4}\d{1,3})\b")

CONF_ALTA = "alta"      # tag e name concordano sullo stesso asset
CONF_MEDIA = "media"    # una sola fonte, univoca
CONF_AMBIGUA = "ambigua"  # piu' asset per lo stesso codice
CONF_ASSENTE = "assente"  # nessun match


def normalizza_codice(s: str) -> str:
    """Uppercase, senza spazi/separatori interni: 'dm 11' -> 'DM11'."""
    return re.sub(r"\s+", "", (s or "")).upper()


# Suffissi di attacco mandrino che nel foglio sono incollati al codice
# (es. "DM3 ISO40", "MK1 HSK"): vanno separati prima del match con l'asset.
_ATTACCHI = {"HSK", "ISO40", "ISO50", "ISO30", "BT40", "BT30", "CAT40"}


def normalizza_codice_attacco(s: str) -> tuple[str, str]:
    """Separa il codice-officina dal suffisso di attacco.

    'DM3 ISO40' -> ('DM3', 'ISO40'); 'MK1 HSK' -> ('MK1', 'HSK'); 'DM10' -> ('DM10', '').
    """
    parts = [p for p in re.split(r"\s+", (s or "").strip()) if p]
    attacco = ""
    if len(parts) >= 2 and parts[-1].upper() in _ATTACCHI:
        attacco = parts[-1].upper()
        parts = parts[:-1]
    return normalizza_codice("".join(parts)), attacco


def _estrai_da_tag(asset_tag: str) -> str | None:
    m = _RE_TAG_CODE.match(asset_tag or "")
    return normalizza_codice(m.group(1)) if m else None


def _estrai_da_name(name: str) -> str | None:
    m = _RE_NAME_CODE.match(name or "")
    return normalizza_codice(m.group(1)) if m else None


@dataclass
class IndiceAsset:
    per_tag: dict[str, list]
    per_name: dict[str, list]

    @classmethod
    def costruisci(cls, assets) -> "IndiceAsset":
        per_tag: dict[str, list] = {}
        per_name: dict[str, list] = {}
        for a in assets:
            c = _estrai_da_tag(getattr(a, "asset_tag", ""))
            if c:
                per_tag.setdefault(c, []).append(a)
            c2 = _estrai_da_name(getattr(a, "name", ""))
            if c2:
                per_name.setdefault(c2, []).append(a)
        return cls(per_tag=per_tag, per_name=per_name)


@dataclass
class Risoluzione:
    codice: str
    asset: object | None
    fonte: str  # asset_tag | name | ""
    confidenza: str
    motivo: str = ""


def risolvi(codice_foglio: str, indice: IndiceAsset) -> Risoluzione:
    code = normalizza_codice(codice_foglio)
    tag_hits = indice.per_tag.get(code, [])
    name_hits = indice.per_name.get(code, [])

    # Il tag descrittivo con seriale (CNC-DM6-000060148189) e' la fonte autorevole:
    # se e' univoco vince anche se esistono omonimi sul `name` (es. "DM6" + "DM6 IoT").
    if len(tag_hits) == 1:
        asset = tag_hits[0]
        tag_val = getattr(asset, "asset_tag", None)
        concorda = any(getattr(a, "asset_tag", None) == tag_val for a in name_hits)
        if name_hits and concorda:
            return Risoluzione(code, asset, "asset_tag", CONF_ALTA, "tag e name concordano")
        return Risoluzione(code, asset, "asset_tag", CONF_MEDIA, "match univoco su asset_tag")
    if len(tag_hits) > 1:
        return Risoluzione(code, None, "", CONF_AMBIGUA,
                           "piu' asset con lo stesso codice nel tag: risolvere a mano")

    # nessun tag: ripiego sul name solo se univoco
    if len(name_hits) == 1:
        return Risoluzione(code, name_hits[0], "name", CONF_MEDIA, "solo da name")
    if len(name_hits) > 1:
        return Risoluzione(code, None, "", CONF_AMBIGUA,
                           "piu' asset con lo stesso codice nel name: risolvere a mano")
    return Risoluzione(code, None, "", CONF_ASSENTE, "nessun asset corrispondente")
