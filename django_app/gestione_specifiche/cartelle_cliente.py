"""Risoluzione Cliente -> cartella reale sulla share (mappatura persistente + ricerca).

- ``risolvi(cliente)``  -> (path_reale, fonte): usa la mappatura CONFERMATA (``ClienteCartellaShare``)
  e la valida contro l'allowlist; ritorna None se la cartella non e' (piu') valida o non c'e' mappatura.
- ``suggerisci(cliente)`` -> lista di etichette-cartella candidate (match lessicale con le cartelle
  REALI della share): per i clienti NUOVI, da confermare prima di salvare la mappatura.

Le cartelle "vere" vengono da ``share_write.elenca_cartelle_consentite`` (dir reali sotto le radici
consentite, escluse le _SUPERATO). La ``cartella`` in mappatura e' l'etichetta relativa alla radice.
"""
from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.core.cache import cache

from .models import ClienteCartellaShare
from .share_link import radici_consentite
from .share_write import elenca_cartelle_consentite, valida_cartella_destinazione


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _max_depth() -> int:
    """Profondità cartelle incluse: 1=solo clienti, 2=clienti+sotto-cartelle (default), 3=due livelli."""
    return int(getattr(settings, "GESTIONE_SPECIFICHE_SHARE_MAX_DEPTH", 2) or 2)


def _cache_ttl() -> int:
    return int(getattr(settings, "GESTIONE_SPECIFICHE_SHARE_CACHE_TTL", 600) or 600)


def _cache_key(depth: int) -> str:
    # La chiave include le radici: correttezza in prod e isolamento fra test (radici diverse).
    h = hashlib.md5((";".join(radici_consentite())).encode("utf-8")).hexdigest()[:10]
    return f"gs:cartelle_share:{depth}:{h}"


def _label_to_path() -> dict[str, str]:
    """Mappa {etichetta relativa (cliente o cliente\\sottocartella) -> path reale}, cache-ata.

    Le etichette a più segmenti (es. ``FERRARI - FERRARI GES\\Motori``) rappresentano le
    sotto-cartelle. Il camminamento della share è cache-ato (TTL) per non ripeterlo a ogni ricerca.
    """
    depth = _max_depth()
    key = _cache_key(depth)
    cached = cache.get(key)
    if cached is not None:
        return cached
    out: dict[str, str] = {}
    for c in elenca_cartelle_consentite(max_depth=depth):
        lbl = c.get("label")
        if lbl and lbl != "(radice)":
            out[lbl] = c["path"]
    cache.set(key, out, _cache_ttl())
    return out


def invalida_cache_cartelle() -> None:
    """Invalida la cache delle cartelle (dopo aver aggiunto una cartella nuova sulla share)."""
    for d in (1, 2, 3, 4):
        cache.delete(_cache_key(d))


def cartelle_disponibili() -> list[str]:
    """Etichette delle cartelle reali sulla share (clienti + sotto-cartelle), ordinate."""
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
