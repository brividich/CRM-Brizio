"""Simulatori in memoria di pyLSV2 e della libreria Fwlib per i test (nessuna macchina, nessuna rete).

Hanno anche le funzioni di scrittura delle librerie vere: servono a dimostrare che il proxy le blocca.
Ogni simulatore conta aperture e chiusure (per i test sulle perdite di connessioni e handle) e
permette di iniettare guasti: macchina spenta, cavo staccato, login DNC rifiutato, valori malformati,
chiamate che restano appese.
"""
from __future__ import annotations

import ctypes
import threading
from enum import IntEnum
from types import SimpleNamespace
from typing import Any


class ExecState(IntEnum):
    MANUAL = 0
    MDI = 1
    PASS_REFERENCES = 2
    SINGLE_STEP = 3
    AUTOMATIC = 4
    UNDEFINED = 5


class PgmState(IntEnum):
    STARTED = 0
    STOPPED = 1
    FINISHED = 2
    CANCELLED = 3
    INTERRUPTED = 4
    ERROR = 5
    ERROR_CLEARED = 6
    IDLE = 7
    UNDEFINED = 8


class LSV2StateException(Exception):
    pass


class _Dati(SimpleNamespace):
    _finto_lsv2 = True


class StatoLsv2:
    """Stato condiviso del controllo Heidenhain simulato (lo cambia il test)."""

    def __init__(self) -> None:
        self.acceso = True
        self.dnc = True
        self.esecuzione = ExecState.AUTOMATIC
        self.programma = PgmState.IDLE
        self.main = "TNC:\\nc_prog\\PEZZO_A.h"
        self.current = "TNC:\\nc_prog\\SUB.h"
        self.riga = 10
        self.override = (100.0, 100.0, 100.0)   # feed, spindle, rapid
        self.messaggi: list[tuple[int, int, int, str]] = []
        self.guasto_lettura: Exception | None = None     # alla prossima lettura (una volta)
        self.override_rotto = False                       # override_state solleva sempre
        self.blocca: threading.Event | None = None        # le letture aspettano questo evento
        self.connessioni = 0
        self.disconnessioni = 0          # chiusure di connessioni aperte
        self.disconnect_tentate = 0      # tutte le chiamate a disconnect
        self.chiamate: list[str] = []
        self.lock = threading.Lock()


class LSV2Finto:
    """Stessa interfaccia (pubblica) di ``pyLSV2.LSV2`` 1.x, comprese le funzioni che non si devono usare."""

    stato: StatoLsv2

    def __init__(self, hostname: str, port: int = 0, timeout: float = 15.0, safe_mode: bool = True,
                 compatibility_mode: bool = False) -> None:
        self.hostname, self.port, self.timeout = hostname, port, timeout
        self.safe_mode, self.compatibility_mode = safe_mode, compatibility_mode
        self.aperta = False

    def _usa(self, nome: str) -> None:
        s = self.stato
        s.chiamate.append(nome)
        if s.blocca is not None:
            s.blocca.wait()
        if not self.aperta:
            raise LSV2StateException("connection is not open!")
        if not s.acceso:
            raise ConnectionResetError("connessione chiusa dal controllo")
        if s.guasto_lettura is not None:
            e, s.guasto_lettura = s.guasto_lettura, None
            raise e

    # connessione
    def connect(self) -> None:
        s = self.stato
        s.chiamate.append("connect")
        if not s.acceso:
            raise ConnectionRefusedError("controllo spento")
        self.aperta = True
        with s.lock:
            s.connessioni += 1

    def disconnect(self) -> None:
        s = self.stato
        s.chiamate.append("disconnect")
        was_open, self.aperta = self.aperta, False
        with s.lock:
            s.disconnect_tentate += 1
            s.disconnessioni += 1 if was_open else 0
        if not was_open:
            raise LSV2StateException("connection is not open!")

    @property
    def versions(self) -> _Dati:
        return _Dati(control="TNC640", nc_sw="340595 10 SP2", type=1, release="")

    # letture di stato
    def execution_state(self) -> ExecState:
        self._usa("execution_state")
        return self.stato.esecuzione if self.stato.dnc else ExecState.UNDEFINED

    def program_status(self) -> PgmState:
        self._usa("program_status")
        return self.stato.programma if self.stato.dnc else PgmState.UNDEFINED

    def program_stack(self) -> _Dati | None:
        self._usa("program_stack")
        s = self.stato
        return _Dati(main=s.main, current=s.current, line_no=s.riga) if s.dnc else None

    def override_state(self) -> _Dati | None:
        self._usa("override_state")
        s = self.stato
        if s.override_rotto:
            raise ValueError("risposta override non decodificabile")
        return _Dati(feed=s.override[0], spindle=s.override[1], rapid=s.override[2]) if s.dnc else None

    def get_error_messages(self) -> list[_Dati]:
        self._usa("get_error_messages")
        return [_Dati(e_class=c, e_group=g, e_number=n, e_text=t, dnc=True) for c, g, n, t in self.stato.messaggi]

    # funzioni che il collector non deve mai poter chiamare
    def send_file(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("send_file chiamata")

    def recive_file(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("recive_file chiamata")

    def delete_file(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("delete_file chiamata")

    def set_machine_parameter(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("set_machine_parameter chiamata")

    def send_key_code(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("send_key_code chiamata")

    def login(self, *a: Any, **k: Any) -> bool:
        raise AssertionError("login chiamata direttamente")


def modulo_lsv2(stato: StatoLsv2) -> SimpleNamespace:
    """Un «modulo pyLSV2» il cui ``LSV2`` usa lo stato condiviso dato."""
    classe = type("LSV2", (LSV2Finto,), {"stato": stato})
    return SimpleNamespace(LSV2=classe, ExecState=ExecState, PgmState=PgmState)


# --- Fwlib -----------------------------------------------------------------------------------------
class FwlibFinta:
    """Libreria Fwlib in memoria: le funzioni ricevono gli argomenti di ctypes come quella vera."""

    def __init__(self) -> None:
        self.acceso = True
        self.aut, self.run, self.emergency, self.alarm = 1, 0, 0, 0
        self.programma = b"O1234"
        self.o_num = 1234
        self.feed, self.speed = 1200, 8000
        self.pezzi = 100
        self.codici: dict[str, int] = {}          # funzione -> codice di ritorno forzato
        self.blocca: threading.Event | None = None
        self.handle_aperti: set[int] = set()
        self.handle_liberati: list[int] = []
        self._prossimo = 1
        self.chiamate: list[str] = []
        self.lock = threading.Lock()

    def _ret(self, nome: str) -> int | None:
        self.chiamate.append(nome)
        if self.blocca is not None and nome != "cnc_freelibhndl":
            self.blocca.wait()
        if nome in self.codici:
            return self.codici[nome]
        return None

    def cnc_allclibhndl3(self, ip: bytes, porta: int, timeout: int, handle: Any) -> int:
        forzato = self._ret("cnc_allclibhndl3")
        if forzato is not None:
            return forzato
        if not self.acceso:
            return -16
        with self.lock:
            h = self._prossimo
            self._prossimo += 1
            self.handle_aperti.add(h)
        handle._obj.value = h
        return 0

    def cnc_freelibhndl(self, h: int) -> int:
        self._ret("cnc_freelibhndl")
        with self.lock:
            self.handle_aperti.discard(h)
            self.handle_liberati.append(h)
        return 0

    def _lettura(self, nome: str, h: int) -> int | None:
        forzato = self._ret(nome)
        if forzato is not None:
            return forzato
        if not self.acceso:
            return -16
        if h not in self.handle_aperti:
            return -8
        return None

    def cnc_statinfo(self, h: int, st: Any) -> int:
        r = self._lettura("cnc_statinfo", h)
        if r is not None:
            return r
        o = st._obj
        o.aut, o.run, o.emergency, o.alarm = self.aut, self.run, self.emergency, self.alarm
        return 0

    def cnc_exeprgname(self, h: int, prg: Any) -> int:
        r = self._lettura("cnc_exeprgname", h)
        if r is not None:
            return r
        prg._obj.name = self.programma
        prg._obj.o_num = self.o_num
        return 0

    def cnc_actf(self, h: int, act: Any) -> int:
        r = self._lettura("cnc_actf", h)
        if r is not None:
            return r
        act._obj.data = self.feed
        return 0

    def cnc_acts(self, h: int, act: Any) -> int:
        r = self._lettura("cnc_acts", h)
        if r is not None:
            return r
        act._obj.data = self.speed
        return 0

    def cnc_rdparam(self, h: int, numero: int, asse: int, lunghezza: int, par: Any) -> int:
        r = self._lettura("cnc_rdparam", h)
        if r is not None:
            return r
        assert numero == 6711 and lunghezza == ctypes.sizeof(par._obj), (numero, lunghezza)
        par._obj.datano = numero
        par._obj.ldata = self.pezzi
        return 0

    # funzioni che il collector non deve mai poter chiamare
    def cnc_wrparam(self, *a: Any) -> int:
        raise AssertionError("cnc_wrparam chiamata")

    def pmc_wrpmcrng(self, *a: Any) -> int:
        raise AssertionError("pmc_wrpmcrng chiamata")

    def cnc_dwnstart3(self, *a: Any) -> int:
        raise AssertionError("cnc_dwnstart3 chiamata")

    def cnc_reset(self, *a: Any) -> int:
        raise AssertionError("cnc_reset chiamata")
