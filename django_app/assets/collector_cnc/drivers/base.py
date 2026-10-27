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
import datetime as dt
import inspect
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
Log = logging.Logger | logging.LoggerAdapter[logging.Logger]


# --- errori comuni ---------------------------------------------------------------------------------
class ErroreConnessione(Exception):
    """La connessione con la macchina è persa o non si apre: il collector chiude e si riconnette."""


class LoginRifiutato(ErroreConnessione):
    """La macchina risponde ma rifiuta l'accesso che serve per leggere lo stato (es. login DNC)."""


class LibreriaAssente(ErroreConnessione):
    """La libreria del driver (pyLSV2, Fwlib) non c'è o non si carica: la macchina non è leggibile."""


class ErroreFunzione(Exception):
    """Una singola lettura non è riuscita (funzione non supportata, opzione mancante, dato non valido)."""


# --- record normalizzato ---------------------------------------------------------------------------
@dataclass
class Messaggio:
    codice: str
    testo: str
    severita: int | None = None


VOLATILI = frozenset({"ts", "line", "feed", "speed", "raw"})


@dataclass
class Lettura:
    """Un record uguale per tutti i driver. ``line``, ``feed``, ``speed`` e ``raw`` sono volatili:
    si salvano ma non contano per decidere se la macchina «è cambiata»."""

    ts: dt.datetime
    machine: str
    driver: str
    online: bool
    stato: str
    mode: str = "UNKNOWN"
    execution: str = "UNKNOWN"
    program: str | None = None
    subprogram: str | None = None
    feed_ovr: float | None = None
    spindle_ovr: float | None = None
    rapid_ovr: float | None = None
    alarm: bool = False
    alarm_text: str | None = None
    part_count: int | None = None      # contatore grezzo della CNC (se c'è)
    parts_total: int | None = None     # pezzi/cicli cumulati dal collector (non scende mai)
    errore: str = ""                   # perché OFFLINE / NON_LEGGIBILE
    messaggi: list[Messaggio] = field(default_factory=list)
    line: int | None = None
    feed: float | None = None
    speed: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def come_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d

    def stabile(self) -> dict[str, Any]:
        """I campi che contano per il confronto «è cambiato?»."""
        return {k: v for k, v in self.come_dict().items() if k not in VOLATILI}


class DriverSincrono(Protocol):
    """Driver bloccante (LSV2, FOCAS): lo usa un solo thread, con una connessione persistente."""

    nome_driver: str
    timeout: float

    def connetti(self) -> None: ...
    def leggi(self) -> Lettura: ...
    def chiudi(self) -> None: ...
    def interrompi(self) -> None: ...


class FunzioniOpzionali:
    """Dopo ``SOGLIA`` errori consecutivi una lettura non si chiama più su quella macchina (log una volta).

    Gli errori di connessione non contano: passano come ``ErroreConnessione`` e fanno riconnettere.
    Per le letture essenziali (senza le quali lo stato non si conosce) la soglia fa riconnettere
    invece di disattivare.
    """

    SOGLIA = 3

    def __init__(self, log: Log, connessione: Callable[[BaseException], bool]) -> None:
        self.log = log
        self.connessione = connessione
        self.errori: dict[str, int] = {}
        self.disattivate: set[str] = set()

    def attiva(self, nome: str) -> bool:
        return nome not in self.disattivate

    def chiama(self, nome: str, fn: Callable[[], T], essenziale: bool = False) -> T | None:
        if nome in self.disattivate:
            return None
        try:
            esito = fn()
        except ErroreConnessione:
            raise
        except Exception as e:  # noqa: BLE001 - classificato qui sotto: connessione -> rilancio, altro -> conteggio
            if self.connessione(e):
                raise ErroreConnessione(f"{nome}: {type(e).__name__}: {e}") from e
            n = self.errori.get(nome, 0) + 1
            self.errori[nome] = n
            if n < self.SOGLIA:
                self.log.debug("%s non riuscita (%d/%d): %s", nome, n, self.SOGLIA, e)
                return None
            if essenziale:
                self.errori[nome] = 0
                raise ErroreConnessione(f"{nome} fallita {n} volte di seguito: {type(e).__name__}: {e}") from e
            self.disattivate.add(nome)
            self.log.warning("%s disattivata su questa macchina dopo %d errori consecutivi (%s: %s)",
                             nome, n, type(e).__name__, e)
            return None
        self.errori[nome] = 0
        return esito


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
