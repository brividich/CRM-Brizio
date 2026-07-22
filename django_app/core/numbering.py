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


def next_suffix(codes: Iterable, prefix: str) -> int:
    """Prossimo N tale che ``f'{prefix}-{N}'`` sia libero, guardando i ``codes`` che
    iniziano con ``f'{prefix}-'`` e hanno coda numerica. Ritorna 1 se nessuno.

    Es. prefix='SIC', codes=['SIC-1','SIC-3','ALTRO-9'] -> 4.
    """
    best = 0
    p = f"{prefix}-"
    for c in codes:
        s = str(c or "").strip()
        if s.startswith(p):
            tail = s[len(p):]
            if tail.isdigit():
                n = int(tail)
                if n > best:
                    best = n
    return best + 1


def next_code(codes: Iterable, prefix: str) -> str:
    """Codice completo ``f'{prefix}-{N}'`` col prossimo N libero per quel prefix."""
    return f"{prefix}-{next_suffix(codes, prefix)}"
