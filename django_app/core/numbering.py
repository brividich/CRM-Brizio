"""Numerazione incrementale condivisa (§5.3 del remediation-plan).

Funzioni PURE (nessun accesso DB): il chiamante passa i valori/codici esistenti
(tipicamente un ``values_list``). La sicurezza in concorrenza è responsabilità del
chiamante (transazione + lock dove serve); qui c'è solo la logica "prossimo numero".

Usato da:
- assets: ``Asset.internal_number`` progressivo (punto 3.3);
- anagrafica: codice corso ``<codice piano>-<N>`` (punto 1.7).
"""
from __future__ import annotations

from typing import Iterable


def max_numeric(values: Iterable) -> int:
    """Massimo dei valori **interamente numerici** in ``values`` (0 se nessuno).

    Ignora i valori non numerici (es. matricole/numeri interni alfanumerici legacy),
    così un progressivo numerico non viene confuso da codici storici testuali.
    """
    best = 0
    for v in values:
        s = str(v or "").strip()
        if s.isdigit():
            n = int(s)
            if n > best:
                best = n
    return best


def next_numeric(values: Iterable) -> int:
    """Prossimo intero progressivo: ``max_numeric(values) + 1`` (parte da 1)."""
    return max_numeric(values) + 1


def next_suffix(codes: Iterable, prefix: str, sep: str = "-") -> int:
    """Prossimo N tale che ``f'{prefix}{sep}{N}'`` sia libero, guardando i ``codes``
    che iniziano con ``f'{prefix}{sep}'`` e hanno coda numerica. Ritorna 1 se nessuno.

    ``sep`` è configurabile (default ``'-'`` per retro-compatibilità); es. ``sep='.'``
    per la convenzione asset ``Int.NNN``.

    Es. prefix='SIC', codes=['SIC-1','SIC-3','ALTRO-9'] -> 4.
    """
    best = 0
    p = f"{prefix}{sep}"
    for c in codes:
        s = str(c or "").strip()
        if s.startswith(p):
            tail = s[len(p):]
            if tail.isdigit():
                n = int(tail)
                if n > best:
                    best = n
    return best + 1


def next_code(codes: Iterable, prefix: str, sep: str = "-", pad: int = 0) -> str:
    """Codice completo ``f'{prefix}{sep}{N}'`` col prossimo N libero per quel prefix.

    ``pad`` zero-riempie N a larghezza minima (default 0 = nessun padding); es.
    ``sep='.', pad=3`` -> ``'Int.002'``.
    """
    return f"{prefix}{sep}{next_suffix(codes, prefix, sep):0{pad}d}"


def next_prefixed(values: Iterable, prefix: str, sep: str = "-", pad: int = 0) -> str:
    """Prossimo codice ``f'{prefix}{sep}{N:0{pad}d}'`` per una sequenza mista.

    Considera come un'unica sequenza numerica sia i codici già prefissati (coda
    numerica dopo ``prefix+sep``) sia i valori **interamente numerici** senza prefisso
    (legacy). Ignora le code non interamente numeriche (es. ``'Int.188A'``). Emette
    **sempre** il prefisso, così i valori nudi legacy non vengono mai riproposti nudi.

    Es. prefix='Int', sep='.', pad=3, values=['196','197','Int.262','Int.188A']
    -> 'Int.263' (262 è il massimo; 196/197 sono sotto; '188A' ignorato).
    """
    best = 0
    head = f"{prefix}{sep}"
    for v in values:
        s = str(v or "").strip()
        n = None
        if s.startswith(head):
            tail = s[len(head):]
            if tail.isdigit():
                n = int(tail)
        elif s.isdigit():
            n = int(s)
        if n is not None and n > best:
            best = n
    return f"{prefix}{sep}{best + 1:0{pad}d}"
