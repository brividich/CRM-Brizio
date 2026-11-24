"""Calcoli ripetuti nella stessa richiesta di sola lettura: una volta sola.

Usa la memoria delle richieste GET/HEAD aperta da ``ACLMiddleware``
(``core.acl_resolver.memo_permessi``): fuori da quel blocco (POST, comandi, task) la
funzione decorata si comporta esattamente come prima. Va messo solo su funzioni di
lettura con argomenti semplici (date, numeri, stringhe): con argomenti non hashabili
la chiamata passa diretta. Restituisce una copia superficiale di liste e dizionari,
così chi riordina o aggiunge chiavi non cambia il risultato degli altri chiamanti.
"""
from __future__ import annotations

import functools


def per_richiesta(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from core.acl_resolver import memo_attiva

        memo = memo_attiva()
        if memo is None:
            return fn(*args, **kwargs)
        try:
            chiave = ("per_richiesta", fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
            hash(chiave)
        except TypeError:
            return fn(*args, **kwargs)
        if chiave not in memo:
            memo[chiave] = fn(*args, **kwargs)
        valore = memo[chiave]
        if isinstance(valore, dict):
            return dict(valore)
        if isinstance(valore, list):
            return list(valore)
        return valore

    return wrapper
