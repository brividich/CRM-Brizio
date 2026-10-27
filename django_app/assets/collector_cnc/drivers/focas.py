"""Driver Fanuc FOCAS (Ethernet) in sola lettura, con la libreria Fwlib via ctypes.

La libreria si carica da ``CNC_FWLIB_PATH`` (file o cartella) o dal nome standard della piattaforma
(``Fwlib64.dll``/``Fwlib32.dll`` su Windows, ``libfwlib32.so`` su Linux); non sta nel repository.
Su Linux ``cnc_startupprocess`` si chiama una volta per processo (e ``cnc_exitprocess`` all'uscita).

Si possono chiamare solo le funzioni di ``FWLIB_AMMESSE``: apertura e chiusura dell'handle, stato
(``cnc_statinfo``), programma in esecuzione, avanzamento e velocità mandrino attuali e la lettura
del parametro 6711 (pezzi lavorati). Qualunque altra funzione della libreria solleva ``PermissionError``.

Codici di ritorno: 0 = ok; -16 (socket) e -8 (handle non valido) = connessione persa -> riconnessione;
-1 (occupato) = riprova al giro dopo; gli altri contano come errore della singola lettura.
"""
from __future__ import annotations

import atexit
import ctypes
import datetime as dt
import logging
import os
import platform
import struct
import sys
import threading
from pathlib import Path
from typing import Any

try:
    from .. import stati   # dentro il portale (assets.collector_cnc.drivers)
except ImportError:
    import stati           # type: ignore[no-redef]  # sul PC dell'officina (drivers è un package di primo livello)
from .base import (
    ErroreConnessione,
    ErroreFunzione,
    FunzioniOpzionali,
    LibreriaAssente,
    Lettura,
    Log,
    ProxySolaLettura,
)

NOME_DRIVER = "focas"
PORTA = 8193
TIMEOUT = 5.0
PARAMETRO_PEZZI = 6711
EW_OK, EW_BUSY, EW_HANDLE, EW_SOCKET = 0, -1, -8, -16
CODICI_CONNESSIONE = frozenset({EW_HANDLE, EW_SOCKET})

FWLIB_AMMESSE = frozenset({"cnc_startupprocess", "cnc_exitprocess", "cnc_allclibhndl3", "cnc_freelibhndl",
                           "cnc_statinfo", "cnc_exeprgname", "cnc_actf", "cnc_acts", "cnc_rdparam"})

c_short, c_ushort, c_long = ctypes.c_short, ctypes.c_ushort, ctypes.c_long


class ODBST(ctypes.Structure):
    """Stato del CNC, serie 30i/0i-D/F (``cnc_statinfo``)."""

    _fields_ = [("hdck", c_short), ("tmmode", c_short), ("aut", c_short), ("run", c_short), ("motion", c_short),
                ("mstb", c_short), ("emergency", c_short), ("alarm", c_short), ("edit", c_short)]


class ODBEXEPRG(ctypes.Structure):
    """Programma in esecuzione (``cnc_exeprgname``)."""

    _fields_ = [("name", ctypes.c_char * 36), ("o_num", c_long)]


class ODBACT(ctypes.Structure):
    """Avanzamento o velocità attuale (``cnc_actf``, ``cnc_acts``)."""

    _fields_ = [("dummy", c_short * 2), ("data", c_long)]


class _DatiParametro(ctypes.Union):
    _fields_ = [("cdata", ctypes.c_char), ("idata", c_short), ("ldata", c_long)]


class IODBPSD(ctypes.Structure):
    """Un parametro non di asse (``cnc_rdparam``)."""

    _anonymous_ = ("u",)
    _fields_ = [("datano", c_short), ("type", c_short), ("u", _DatiParametro)]


_P = ctypes.c_void_p
_FIRME: dict[str, tuple[list[Any], Any]] = {
    "cnc_startupprocess": ([c_long, ctypes.c_char_p], c_short),
    "cnc_exitprocess": ([], c_short),
    "cnc_allclibhndl3": ([ctypes.c_char_p, c_ushort, c_long, ctypes.POINTER(c_ushort)], c_short),
    "cnc_freelibhndl": ([c_ushort], c_short),
    "cnc_statinfo": ([c_ushort, ctypes.POINTER(ODBST)], c_short),
    "cnc_exeprgname": ([c_ushort, ctypes.POINTER(ODBEXEPRG)], c_short),
    "cnc_actf": ([c_ushort, ctypes.POINTER(ODBACT)], c_short),
    "cnc_acts": ([c_ushort, ctypes.POINTER(ODBACT)], c_short),
    "cnc_rdparam": ([c_ushort, c_short, c_short, c_short, ctypes.POINTER(IODBPSD)], c_short),
}

_libreria: Any = None
_libreria_lock = threading.Lock()


def nome_standard() -> str:
    if sys.platform.startswith("win"):
        return "Fwlib64.dll" if struct.calcsize("P") == 8 else "Fwlib32.dll"
    return "libfwlib32.so"


def percorso_libreria(percorso: str | None = None) -> str:
    """File della libreria: ``percorso`` o ``CNC_FWLIB_PATH`` (file o cartella), altrimenti il nome standard."""
    scelto = (percorso or os.environ.get("CNC_FWLIB_PATH", "")).strip()
    if not scelto:
        return nome_standard()
    p = Path(scelto)
    return str(p / nome_standard()) if p.is_dir() else str(p)


def _configura(raw: Any) -> None:
    """Firme ctypes delle sole funzioni ammesse (lunghezze e tipi coerenti con la piattaforma)."""
    for nome in FWLIB_AMMESSE:
        funzione = getattr(raw, nome, None)
        if funzione is None or not hasattr(funzione, "argtypes"):
            continue
        funzione.argtypes, funzione.restype = _FIRME[nome]


def carica_fwlib(percorso: str | None = None, raw: Any = None) -> ProxySolaLettura:
    """La libreria Fwlib (una per processo) dietro la whitelist; ``raw`` per i test (libreria finta)."""
    global _libreria
    with _libreria_lock:
        if raw is None and _libreria is not None:
            return ProxySolaLettura(_libreria, FWLIB_AMMESSE, NOME_DRIVER)
        if raw is None:
            file = percorso_libreria(percorso)
            if os.path.sep in file and not os.path.exists(file):
                raise LibreriaAssente(f"libreria Fwlib non trovata: {file} (imposta CNC_FWLIB_PATH)")
            try:
                raw = ctypes.WinDLL(file) if sys.platform.startswith("win") else ctypes.CDLL(file)  # type: ignore[attr-defined,unused-ignore]
            except OSError as e:
                raise LibreriaAssente(f"libreria Fwlib non caricata ({file}): {e} (imposta CNC_FWLIB_PATH)") from e
            _configura(raw)
            _libreria = raw
        lib = ProxySolaLettura(raw, FWLIB_AMMESSE, NOME_DRIVER)
        if platform.system() == "Linux" and hasattr(raw, "cnc_startupprocess") and raw is _libreria:
            lib.cnc_startupprocess(0, b"focas.log")
            atexit.register(lambda: lib.cnc_exitprocess())
        return lib


class DriverFocas:
    """Un handle FOCAS persistente, usato solo dal thread che l'ha aperto."""

    nome_driver = NOME_DRIVER

    def __init__(self, nome: str, host: str, porta: int = PORTA, timeout: float = TIMEOUT, log: Log | None = None,
                 pezzi_totali: int = 0, pezzi_ultimo_grezzo: int | None = None, percorso: str | None = None,
                 raw: Any = None) -> None:
        self.nome = nome
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self.log: Log = log or logging.getLogger("collector")
        self._percorso = percorso
        self._raw = raw
        self._lib: Any = None
        self._handle: int | None = None
        self._lock = threading.Lock()
        self.funzioni = FunzioniOpzionali(self.log, lambda e: False)
        self.pulitore = stati.Pulitore(self.log)
        self.pezzi = stati.ContatorePezzi(pezzi_totali, pezzi_ultimo_grezzo)
        self.azzeramenti = 0

    def connetti(self) -> None:
        self._lib = carica_fwlib(self._percorso, self._raw)
        handle = c_ushort(0)
        ret = self._lib.cnc_allclibhndl3(self.host.encode("ascii"), self.porta, max(1, int(self.timeout)),
                                         ctypes.byref(handle))
        if ret != EW_OK:
            raise ErroreConnessione(f"cnc_allclibhndl3 = {ret}")
        with self._lock:
            self._handle = int(handle.value)

    def _h(self) -> int:
        h = self._handle
        if h is None:
            raise ErroreConnessione("handle FOCAS chiuso")
        return h

    def _leggi(self, nome: str, struttura: Any, *prima: Any) -> Any:
        """Chiama ``nome(handle, *prima, &struttura)``; errori di connessione -> ``ErroreConnessione``."""
        ret = getattr(self._lib, nome)(self._h(), *prima, ctypes.byref(struttura))
        if ret == EW_OK:
            return struttura
        if ret in CODICI_CONNESSIONE:
            raise ErroreConnessione(f"{nome} = {ret}: connessione persa")
        if ret == EW_BUSY:
            return None
        raise ErroreFunzione(f"{nome} = {ret}")

    def leggi(self) -> Lettura:
        f, p = self.funzioni, self.pulitore
        st = f.chiama("cnc_statinfo", lambda: self._leggi("cnc_statinfo", ODBST()), essenziale=True)
        if st is None:
            stato, esecuzione, modo = stati.FERMA, "UNKNOWN", "UNKNOWN"
            raw: dict[str, Any] = {}
        else:
            stato, esecuzione, modo = stati.stato_fanuc(st.aut, st.run, st.emergency, st.alarm)
            raw = {k: getattr(st, k) for k, _t in ODBST._fields_}
        prg = f.chiama("cnc_exeprgname", lambda: self._leggi("cnc_exeprgname", ODBEXEPRG()))
        actf = f.chiama("cnc_actf", lambda: self._leggi("cnc_actf", ODBACT()))
        acts = f.chiama("cnc_acts", lambda: self._leggi("cnc_acts", ODBACT()))
        par = f.chiama("cnc_rdparam", lambda: self._leggi("cnc_rdparam", IODBPSD(), PARAMETRO_PEZZI, 0,
                                                            ctypes.sizeof(IODBPSD)))
        grezzo = p.intero("part_count", par.ldata) if par is not None else None
        if grezzo is not None:
            esito = self.pezzi.aggiorna(grezzo)
            if esito.azzerato:
                self.azzeramenti += 1
                self.log.info("contapezzi (parametro %d) azzerato sulla CNC: riparto da %d", PARAMETRO_PEZZI, grezzo)
        return Lettura(
            ts=dt.datetime.now(dt.timezone.utc), machine=self.nome, driver=NOME_DRIVER, online=True,
            stato=stato, mode=modo, execution=esecuzione,
            program=p.testo("program", prg.name) if prg is not None else None,
            alarm=stato in (stati.ALLARME, stati.EMERGENZA),
            part_count=grezzo,
            parts_total=self.pezzi.totale if self.pezzi.ultimo_grezzo is not None else None,
            feed=p.numero("feed", actf.data) if actf is not None else None,
            speed=p.numero("speed", acts.data) if acts is not None else None,
            raw={**raw, "o_num": int(prg.o_num) if prg is not None else None},
        )

    def chiudi(self) -> None:
        """Libera l'handle; idempotente. Va chiamata dal thread che l'ha aperto."""
        with self._lock:
            h, self._handle = self._handle, None
        if h is None or self._lib is None:
            return
        ret = self._lib.cnc_freelibhndl(h)
        if ret != EW_OK:
            self.log.debug("cnc_freelibhndl = %s", ret)

    def interrompi(self) -> None:
        """Niente da fare da un altro thread: l'handle FOCAS appartiene al thread che l'ha aperto.

        Il thread bloccato viene abbandonato dal sorvegliante; quando la chiamata torna (Fwlib ha il suo
        timeout) libera da sé l'handle uscendo.
        """
