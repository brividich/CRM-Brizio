"""F2a — match competenza-macchina MOD.187 → ``assets.Asset`` (sola lettura).

Riusa il *pattern* di normalizzazione di ``gestione_carichi_macchina``
(uppercase, no-spazi) ma resta **self-contained** nell'app ``anagrafica``
(nessun import cross-modulo). Usa un match a **token interi**, che:

- gestisce i codici di sole lettere (STZ, HH, CNV) e quelli con cifra iniziale
  (35S) che la regex "codice-officina" (lettere+cifre) non coprirebbe;
- mantiene la **precisione** DM1 ≠ DM10 ≠ DM11 (confronto su token interi del
  tag/nome, non su substring).

Funzioni pure (nessuna query qui dentro): lavorano su oggetti con attributi
``id``/``asset_tag``/``name`` (``assets.Asset`` reale o qualunque stub).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Confidenze esposte nel report (vocabolario della spec F2a).
CONF_ESATTO = "esatto"
CONF_PARZIALE = "parziale"
CONF_ASSENTE = "assente"

# Strategie di match.
STR_ASSET_TAG = "asset_tag"
STR_NAME = "name"
STR_MANUALE = "manuale"


def normalizza_codice(s: str | None) -> str:
    """Uppercase, senza spazi interni: 'dm 11' -> 'DM11'."""
    return re.sub(r"\s+", "", (s or "")).upper()


def tokenizza(s: str | None) -> list[str]:
    """Spezza su ogni separatore non alfanumerico, uppercase.

    'CNC-DM3-001' -> ['CNC','DM3','001']; 'DM3 - DMG DMC 85' -> ['DM3','DMG','DMC','85'].
    """
    return [t for t in re.split(r"[^0-9A-Za-z]+", (s or "").upper()) if t]


# Tipi asset chiaramente NON-macchina: un match su questi va declassato a
# "parziale" (il codice MOD.187 ha colliso con un tag IT, es. HI -> PCHI).
TIPI_NON_MACCHINA = {
    "PC", "NOTEBOOK", "SERVER", "VM", "FIREWALL", "STAMPANTE", "FONIA", "CCTV",
}


@dataclass
class AssetRef:
    id: object
    asset_tag: str
    name: str
    asset_type: str = ""
    tag_tokens: set = field(default_factory=set)
    name_tokens: set = field(default_factory=set)


@dataclass
class IndiceAssetSkm:
    assets: list
    per_tag_token: dict
    per_name_token: dict

    @classmethod
    def costruisci(cls, assets) -> "IndiceAssetSkm":
        refs: list[AssetRef] = []
        per_tag: dict[str, list[AssetRef]] = {}
        per_name: dict[str, list[AssetRef]] = {}
        for a in assets:
            ref = AssetRef(
                id=getattr(a, "id", None),
                asset_tag=getattr(a, "asset_tag", "") or "",
                name=getattr(a, "name", "") or "",
                asset_type=getattr(a, "asset_type", "") or "",
            )
            ref.tag_tokens = set(tokenizza(ref.asset_tag))
            ref.name_tokens = set(tokenizza(ref.name))
            refs.append(ref)
            for t in ref.tag_tokens:
                per_tag.setdefault(t, []).append(ref)
            for t in ref.name_tokens:
                per_name.setdefault(t, []).append(ref)
        return cls(refs, per_tag, per_name)


@dataclass
class RisultatoMatch:
    confidenza: str
    strategia: str
    asset: object | None
    azione: str


def match_per_codice(codice: str, indice: IndiceAssetSkm) -> RisultatoMatch:
    """Match per codice-officina: tag → esatto, name → parziale, ambiguo → manuale."""
    code = normalizza_codice(codice)
    if not code:
        return RisultatoMatch(CONF_ASSENTE, STR_MANUALE, None, "codice mancante")
    tag_hits = indice.per_tag_token.get(code, [])
    name_hits = indice.per_name_token.get(code, [])
    if len(tag_hits) == 1:
        return RisultatoMatch(CONF_ESATTO, STR_ASSET_TAG, tag_hits[0], "pre-approvato")
    if len(tag_hits) > 1:
        return RisultatoMatch(
            CONF_PARZIALE, STR_MANUALE, None,
            f"ambiguo: {len(tag_hits)} asset col codice nel tag, risolvere a mano",
        )
    if len(name_hits) == 1:
        return RisultatoMatch(CONF_PARZIALE, STR_NAME, name_hits[0], "verificare/confermare match su nome")
    if len(name_hits) > 1:
        return RisultatoMatch(
            CONF_PARZIALE, STR_MANUALE, None,
            f"ambiguo: {len(name_hits)} asset col codice nel nome, risolvere a mano",
        )
    return RisultatoMatch(CONF_ASSENTE, STR_MANUALE, None, "nessun asset: creare alias/asset o escludere")


def match_per_nome(display: str, indice: IndiceAssetSkm, *, min_overlap: int = 2) -> RisultatoMatch:
    """Match sul nome completo (caso ZEISS: codice non univoco).

    Sceglie l'asset con la massima sovrapposizione di token col nome MOD.187.
    Per i ZEISS l'azione resta sempre "confermare a mano" (codice non univoco).
    """
    comp = set(tokenizza(display))
    if not comp:
        return RisultatoMatch(CONF_ASSENTE, STR_MANUALE, None, "nome mancante")
    best: list[AssetRef] = []
    best_score = 0
    for ref in indice.assets:
        score = len(comp & ref.name_tokens)
        if score > best_score:
            best_score, best = score, [ref]
        elif score == best_score and score > 0:
            best.append(ref)
    if best_score < min_overlap or not best:
        return RisultatoMatch(CONF_ASSENTE, STR_MANUALE, None, "nessun asset per nome completo: confermare a mano")
    if len(best) == 1:
        return RisultatoMatch(CONF_PARZIALE, STR_NAME, best[0], "ZEISS/nome: confermare a mano (codice non univoco)")
    return RisultatoMatch(CONF_PARZIALE, STR_MANUALE, None, f"nome: {len(best)} candidati, risolvere a mano")


def match_competenza(codice: str, display: str, indice: IndiceAssetSkm) -> RisultatoMatch:
    """Match completo di una competenza-macchina con declassamento degli "esatto"
    sospetti (= pre-approvati, salterebbero la review):
      - asset di tipo non-macchina (collisione IT, es. tag PC);
      - codice cortissimo (≤2 char) che collide facilmente (es. HI → PCHI,
        asset spesso mistippato OTHER → la regola sul tipo da sola non basta).
    """
    codice = (codice or "").strip()
    display = (display or "").strip()
    r = match_per_codice(codice, indice) if codice else match_per_nome(display, indice)
    if r.asset is not None and r.confidenza == CONF_ESATTO:
        tipo = getattr(r.asset, "asset_type", "")
        if tipo in TIPI_NON_MACCHINA:
            return RisultatoMatch(
                CONF_PARZIALE, r.strategia, r.asset,
                f"tipo asset '{tipo}' non-macchina: verificare (possibile collisione codice)",
            )
        if len(normalizza_codice(codice)) <= 2:
            return RisultatoMatch(
                CONF_PARZIALE, r.strategia, r.asset,
                "codice corto (≤2 char): verificare possibile collisione",
            )
    return r


# Colonne del report (ordine stabile per il CSV).
COLONNE_REPORT = [
    "competenza_key", "nome_mod187", "codice",
    "asset_match_id", "asset_tag", "asset_name",
    "confidenza", "strategia", "azione_suggerita",
]


def costruisci_righe_report(competenze: list[dict], indice: IndiceAssetSkm) -> list[dict]:
    """Per ogni competenza-macchina produce una riga del report (dict).

    ``competenze``: list di dict con chiavi ``competenza_key``, ``display``, ``codice``.
    """
    righe: list[dict] = []
    for c in competenze:
        codice = (c.get("codice") or "").strip()
        display = (c.get("display") or "").strip()
        r = match_competenza(codice, display, indice)
        asset = r.asset
        righe.append({
            "competenza_key": c.get("competenza_key", ""),
            "nome_mod187": display,
            "codice": codice,
            "asset_match_id": asset.id if asset is not None else "",
            "asset_tag": asset.asset_tag if asset is not None else "",
            "asset_name": asset.name if asset is not None else "",
            "confidenza": r.confidenza,
            "strategia": r.strategia,
            "azione_suggerita": r.azione,
        })
    return righe


def riepilogo(righe: list[dict]) -> dict[str, int]:
    """Conteggio per confidenza (esatto/parziale/assente)."""
    out = {CONF_ESATTO: 0, CONF_PARZIALE: 0, CONF_ASSENTE: 0}
    for r in righe:
        out[r["confidenza"]] = out.get(r["confidenza"], 0) + 1
    return out
