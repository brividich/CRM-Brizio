"""Risoluzione Cliente -> cartella reale sulla share (mappatura persistente + ricerca).

- ``risolvi(cliente)``  -> (path_reale, fonte): usa la mappatura CONFERMATA (``ClienteCartellaShare``)
  e la valida contro l'allowlist; ritorna None se la cartella non e' (piu') valida o non c'e' mappatura.
- ``suggerisci(cliente)`` -> lista di etichette-cartella candidate (match lessicale con le cartelle
  REALI della share): per i clienti NUOVI, da confermare prima di salvare la mappatura.

Le cartelle "vere" vengono da ``share_write.elenca_cartelle_consentite`` (dir reali sotto le radici
consentite, escluse le _SUPERATO). La ``cartella`` in mappatura e' l'etichetta relativa alla radice.
"""
from __future__ import annotations

import re

from .models import ClienteCartellaShare
from .share_write import elenca_cartelle_consentite, valida_cartella_destinazione


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _label_to_path() -> dict[str, str]:
    """Mappa {etichetta (1o livello) -> path reale} delle cartelle consentite sulla share."""
    out: dict[str, str] = {}
    for c in elenca_cartelle_consentite(max_depth=1):
        lbl = c.get("label")
        if lbl and lbl != "(radice)":
            out[lbl] = c["path"]
    return out


def cartelle_disponibili() -> list[str]:
    """Etichette delle cartelle di 1o livello reali sulla share (ordinate)."""
    return sorted(_label_to_path().keys())


def risolvi(cliente: str) -> tuple[str | None, str]:
    """(path_reale, fonte). fonte: 'mappatura' se confermata ed esistente; 'cartella_mancante' se
    mappata ma la cartella non c'e' piu'; 'nessuna' se non mappata."""
    cli = (cliente or "").strip()
    if not cli:
        return None, "nessuna"
    m = ClienteCartellaShare.objects.filter(cliente__iexact=cli, attivo=True).first()
    if m is None:
        return None, "nessuna"
    path = _label_to_path().get(m.cartella)
    if path and valida_cartella_destinazione(path):
        return path, "mappatura"
    return None, "cartella_mancante"


def suggerisci(cliente: str, *, max_n: int = 3) -> list[str]:
    """Etichette-cartella candidate per un cliente (match lessicale coi nomi reali), best-first."""
    cli_tok = set(_norm(cliente).split())
    if not cli_tok:
        return []
    scored: list[tuple[float, str]] = []
    for lbl in cartelle_disponibili():
        f_tok = set(_norm(lbl).split())
        if not f_tok:
            continue
        inter = cli_tok & f_tok
        if not inter:
            continue
        score = len(inter) / len(cli_tok | f_tok)  # Jaccard sui token
        scored.append((score, lbl))
    scored.sort(key=lambda t: (t[0], -len(t[1])), reverse=True)
    return [lbl for _, lbl in scored[:max_n]]


def salva_mappatura(cliente: str, cartella_label: str, *, note: str = "") -> ClienteCartellaShare:
    """Salva/aggiorna (conferma) la mappatura cliente -> etichetta cartella."""
    obj, _ = ClienteCartellaShare.objects.update_or_create(
        cliente=(cliente or "").strip(),
        defaults={"cartella": cartella_label, "attivo": True, "note": note},
    )
    return obj
