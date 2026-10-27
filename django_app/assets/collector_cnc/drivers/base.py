"""Base comune dei driver: proxy di sola lettura a whitelist e registro «spia» delle chiamate.

``ProxySolaLettura`` avvolge un oggetto di libreria (client OPC UA, nodo, connessione LSV2, libreria
Fwlib) e lascia passare solo i nomi della whitelist del driver (``frozenset``). Leggere, scrivere o
cancellare qualunque altro attributo solleva ``PermissionError``. I risultati delle chiamate passano
da ``avvolgi``: così anche gli oggetti derivati (es. i nodi restituiti da ``get_node``) restano dietro
la loro whitelist.

``spia()`` registra ogni accesso che passa da un proxy: i test lo usano per dimostrare che in
un'esecuzione completa il collector ha chiamato solo nomi della whitelist.
"""
from __future__ import annotations

import contextlib
import inspect
import threading
from collections.abc import Callable, Iterator
from typing import Any

_spie: list[list[tuple[str, str]]] = []
_spie_lock = threading.Lock()


@contextlib.contextmanager
def spia() -> Iterator[list[tuple[str, str]]]:
    """Registra ``(driver, nome)`` di ogni accesso a un proxy finché il blocco è aperto."""
    registro: list[tuple[str, str]] = []
    with _spie_lock:
        _spie.append(registro)
    try:
        yield registro
    finally:
        with _spie_lock:
            _spie.remove(registro)


def _annota(driver: str, nome: str) -> None:
    if _spie:
        with _spie_lock:
            for registro in _spie:
                registro.append((driver, nome))


def _identita(valore: Any) -> Any:
    return valore


class ProxySolaLettura:
    """Espone di ``bersaglio`` solo i nomi in ``ammessi``; il resto solleva ``PermissionError``."""

    __slots__ = ("_bersaglio", "_ammessi", "_driver", "_avvolgi")

    def __init__(self, bersaglio: Any, ammessi: frozenset[str], driver: str,
                 avvolgi: Callable[[Any], Any] | None = None) -> None:
        object.__setattr__(self, "_bersaglio", bersaglio)
        object.__setattr__(self, "_ammessi", ammessi)
        object.__setattr__(self, "_driver", driver)
        object.__setattr__(self, "_avvolgi", avvolgi or _identita)

    def __getattr__(self, nome: str) -> Any:
        driver: str = object.__getattribute__(self, "_driver")
        if nome not in object.__getattribute__(self, "_ammessi"):
            raise PermissionError(f"{driver}: «{nome}» non è nella whitelist di sola lettura")
        _annota(driver, nome)
        valore = getattr(object.__getattribute__(self, "_bersaglio"), nome)
        avvolgi: Callable[[Any], Any] = object.__getattribute__(self, "_avvolgi")
        if not callable(valore):
            return avvolgi(valore)

        def chiamata(*args: Any, **kwargs: Any) -> Any:
            esito = valore(*args, **kwargs)
            if inspect.isawaitable(esito):
                return _attendi_e_avvolgi(esito, avvolgi)
            return avvolgi(esito)

        return chiamata

    def __setattr__(self, nome: str, valore: Any) -> None:
        raise PermissionError(f"{object.__getattribute__(self, '_driver')}: «{nome}» non si imposta da un proxy di sola lettura")

    def __delattr__(self, nome: str) -> None:
        raise PermissionError(f"{object.__getattribute__(self, '_driver')}: «{nome}» non si cancella da un proxy di sola lettura")

    def __repr__(self) -> str:
        return f"<sola lettura {object.__getattribute__(self, '_driver')}: {object.__getattribute__(self, '_bersaglio')!r}>"


async def _attendi_e_avvolgi(esito: Any, avvolgi: Callable[[Any], Any]) -> Any:
    return avvolgi(await esito)
