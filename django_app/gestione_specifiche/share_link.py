"""Validazione dei percorsi UNC "collegati" (modalità share = single source of truth).

Il portale non copia il PDF: la `Specifica` memorizza il percorso sulla share e la view
protetta lo serve on-demand. Qui la **guardia di sicurezza** (hardened dopo review
avversariale): si servono SOLO file **dentro una radice allowlist**
(`GESTIONE_SPECIFICHE_SHARE_ROOTS`). NON basta un check lessicale su ".." perché la
semantica Windows apre percorsi che una blacklist non vede:

- `..` seguito da spazio/punto finale (`.. `, `..  `, `.. .`) → Windows lo strippa e risale;
- Alternate Data Stream / drive-relative via `:` (`a.pdf:secret`, `a.pdf::$DATA`);
- junction/symlink create SOTTO la radice che puntano fuori (seguite da open/isfile);
- spazi/punti finali nei nomi (match non-canonico).

Difesa a strati: (1) canonicalizzazione lessicale che rifiuta i pattern sopra; (2)
**risoluzione reale** (`os.path.realpath`, segue i reparse point) e confronto con la radice
**anch'essa risolta** via `os.path.commonpath` — così si valida sulla stessa forma che userà
`open()`. `path_consentito`/`risolvi_consentito` ritornano il path canonico da servire.
`ntpath` per il parsing (path Windows) in modo deterministico.
"""
from __future__ import annotations

import ntpath
import os

from django.conf import settings


def radici_consentite() -> list[str]:
    return [str(r) for r in getattr(settings, "GESTIONE_SPECIFICHE_SHARE_ROOTS", []) if r]


def _segmenti_esclusi() -> set[str]:
    """Nomi cartella (lower) da escludere dall'indice per-nome (es. '_superato')."""
    return {str(s).strip().lower() for s in getattr(settings, "GESTIONE_SPECIFICHE_SHARE_EXCLUDE", []) if str(s).strip()}


def costruisci_indice_nomi() -> dict[str, list[str]]:
    """Indice ``{nomefile.lower(): [percorso, ...]}`` dei PDF sotto le radici consentite,
    **escluse** le cartelle di supersessione (`GESTIONE_SPECIFICHE_SHARE_EXCLUDE`, a qualsiasi
    livello). Una sola scansione ricorsiva; serve al fallback "collega per nome".
    """
    esclusi = _segmenti_esclusi()
    indice: dict[str, list[str]] = {}
    for root in radici_consentite():
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in esclusi]  # non discendere nelle escluse
            for fn in filenames:
                if fn.lower().endswith(".pdf"):
                    indice.setdefault(fn.lower(), []).append(os.path.join(dirpath, fn))
    return indice


def _canonicalizza(path: str) -> str | None:
    """Path assoluto e "pulito" a livello lessicale, o None se sospetto.

    Rifiuta: non assoluti; ':' oltre alla lettera di drive (ADS / drive-relative); segmenti
    con spazio o punto finale (che Windows striperebbe) o pari a '.'/'..' dopo lo strip.
    NON tocca il filesystem (fatto dopo, in risolvi_consentito).
    """
    raw = str(path or "").replace("/", "\\")
    if not raw or not ntpath.isabs(raw):
        return None
    _drive, rest = ntpath.splitdrive(raw)
    if ":" in rest:  # ADS (a.pdf:stream / ::$DATA) o drive-relative
        return None
    norm = ntpath.normpath(raw)
    _drive2, rest2 = ntpath.splitdrive(norm)
    for seg in rest2.split("\\"):
        if seg == "":
            continue
        stripped = seg.rstrip(" .")
        if stripped != seg or stripped in ("", ".", ".."):
            return None
    return norm


def _real_nc(p: str) -> str | None:
    """os.path.realpath normalizzato-case (segue junction/symlink), o None se non risolvibile."""
    try:
        return os.path.normcase(os.path.realpath(p))
    except (OSError, ValueError):
        return None


def risolvi_consentito(path: str) -> str | None:
    """Ritorna il path REALE da servire se è dentro una radice allowlist, altrimenti None.

    Risolve i reparse point sia del percorso sia delle radici e confronta con
    `os.path.commonpath` (stessa canonicalizzazione di `open()`), battendo junction/symlink.
    """
    canon = _canonicalizza(path)
    if canon is None:
        return None
    real = os.path.realpath(canon)
    real_nc = _real_nc(canon)
    if real_nc is None:
        return None
    for root in radici_consentite():
        root_nc = _real_nc(root)
        if not root_nc:
            continue
        try:
            if os.path.commonpath([real_nc, root_nc]) == root_nc:
                return real
        except ValueError:  # drive/share diversi
            continue
    return None


def path_consentito(path: str) -> bool:
    """True se `path` è servibile (dentro una radice allowlist, dopo canonicalizzazione reale)."""
    return risolvi_consentito(path) is not None


def collega_specifica(spec, path: str, *, forza: bool = False, apply: bool = False, indice=None) -> str:
    """Collega la `Specifica` al PDF sulla share (imposta `percorso_esterno`).

    Prova il path esatto; se `indice` è fornito (fallback per-nome) e il file esatto manca,
    cerca il PDF **per nome** nell'indice (già privo delle cartelle superate) e collega SOLO
    se c'è **un unico** candidato consentito (mai indovinare tra più file → 'ambiguo').

    Esiti: 'gia_collegato' | 'ambiguo' | 'path_non_consentito' | 'file_mancante' |
    'da_collegare'/'da_collegare_nome' (dry-run) | 'collegato'/'collegato_nome' (--apply).
    Idempotente (salta chi è già collegato salvo `forza`); collega solo file realmente
    presenti; usa `update()` (niente FSM/auto_now).
    """
    from .models import Specifica

    if getattr(spec, "percorso_esterno", "") and not forza:
        return "gia_collegato"

    target, via_nome = None, False
    reale = risolvi_consentito(path)
    if reale is not None and os.path.isfile(reale):
        target = path  # esatto: memorizza il percorso REGISTRATO (fedele all'export)
    elif indice is not None:
        base = ntpath.basename(str(path or "")).lower()
        cand: list[str] = []
        visti: set[str] = set()  # dedup per file reale (junction / doppie radici)
        for c in indice.get(base, []):
            r = risolvi_consentito(c)
            if r and os.path.isfile(r) and r not in visti:
                visti.add(r)
                cand.append(c)  # memorizza il percorso TROVATO sotto la radice
        if len(cand) == 1:
            target, via_nome = cand[0], True
        elif len(cand) > 1:
            return "ambiguo"

    if target is None:
        return "path_non_consentito" if reale is None else "file_mancante"
    if not apply:
        return "da_collegare_nome" if via_nome else "da_collegare"
    Specifica.objects.filter(pk=spec.pk).update(percorso_esterno=target)
    return "collegato_nome" if via_nome else "collegato"
