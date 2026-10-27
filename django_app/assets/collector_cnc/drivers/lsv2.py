"""Driver Heidenhain LSV2 (iTNC 530, TNC 640) in sola lettura, con pyLSV2 1.x.

``safe_mode=False`` serve perché pyLSV2 in modalità sicura blocca il login DNC, senza il quale stato
di esecuzione, programma e override non si leggono. La sicurezza la dà la whitelist: il proxy lascia
chiamare solo ``LSV2_AMMESSI`` (connessione e letture di stato); trasferimento file, selezione ed
esecuzione di programmi, parametri macchina, tasti e PLC non sono raggiungibili. Anche gli oggetti
restituiti (versioni, stack del programma, override, messaggi) passano da un proxy di sola lettura.

Note su pyLSV2:
- ``connect()`` fa da sé il login INSPECT (sola lettura) e FILETRANSFER (diritto di sessione, nessun
  file viene trasferito: le funzioni di file non sono nella whitelist). Con ``compatibility_mode``
  non manda i comandi di sistema per buffer e invio file sicuro.
- se il controllo rifiuta il login DNC, le letture di stato tornano ``UNDEFINED``: la macchina va in
  ``NON_LEGGIBILE`` con il messaggio «serve l'opzione software #18».
"""
from __future__ import annotations

import datetime as dt
import importlib
import inspect
import logging
import threading
from enum import Enum
from types import ModuleType
from typing import Any

try:
    from .. import stati   # dentro il portale (assets.collector_cnc.drivers)
except ImportError:
    import stati           # type: ignore[no-redef]  # sul PC dell'officina (drivers è un package di primo livello)
from .base import (
    ErroreConnessione,
    FunzioniOpzionali,
    LibreriaAssente,
    Lettura,
    Log,
    LoginRifiutato,
    Messaggio,
    ProxySolaLettura,
)

NOME_DRIVER = "lsv2"
PORTA = 19000
TIMEOUT = 5.0

LSV2_AMMESSI = frozenset({"connect", "disconnect", "versions", "execution_state", "program_status",
                          "program_stack", "override_state", "get_error_messages"})
# Attributi leggibili degli oggetti restituiti (VersionInfo, StackState, OverrideState, NCErrorMessage, enum)
DATI_AMMESSI = frozenset({"control", "nc_sw", "type", "release", "main", "current", "line_no", "feed",
                          "rapid", "spindle", "e_class", "e_group", "e_number", "e_text", "dnc", "name", "value"})
MSG_OPZIONE_18 = ("login DNC rifiutato: su questa macchina serve l'opzione software #18 "
                  "(LSV2 DNC) per leggere stato, programma e override")
_ECCEZIONI_CONNESSIONE = frozenset({"LSV2StateException", "LSV2ProtocolException"})


def errore_di_connessione(e: BaseException) -> bool:
    """Socket chiuso, timeout, protocollo fuori sincronia: si riconnette."""
    return isinstance(e, (OSError, EOFError)) or type(e).__name__ in _ECCEZIONI_CONNESSIONE


def _avvolgi_dati(esito: Any) -> Any:
    if isinstance(esito, list):
        return [_avvolgi_dati(x) for x in esito]
    if isinstance(esito, Enum) or esito is None or isinstance(esito, (str, int, float, bool)):
        return esito
    if type(esito).__module__.startswith("pyLSV2") or getattr(esito, "_finto_lsv2", False):
        return ProxySolaLettura(esito, DATI_AMMESSI, NOME_DRIVER, _avvolgi_dati)
    return esito


def _nome(v: Any) -> str | None:
    """Nome di un enum di pyLSV2 (``ExecState.AUTOMATIC`` -> ``AUTOMATIC``), None se manca."""
    if v is None:
        return None
    nome = getattr(v, "name", None)
    return str(nome) if nome is not None else str(v)


def carica_pylsv2() -> ModuleType:
    try:
        return importlib.import_module("pyLSV2")
    except ImportError as e:
        raise LibreriaAssente("libreria pyLSV2 non installata: pip install -r requirements.txt") from e


class DriverLsv2:
    """Una connessione LSV2 persistente; ``leggi()`` dà un ``Lettura`` normalizzato."""

    nome_driver = NOME_DRIVER

    def __init__(self, nome: str, host: str, porta: int = PORTA, timeout: float = TIMEOUT, log: Log | None = None,
                 cicli_iniziali: int = 0, modulo: ModuleType | Any | None = None) -> None:
        self.nome = nome
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self.log: Log = log or logging.getLogger("collector")
        self._modulo = modulo
        self._client: Any = None
        self._lock = threading.Lock()
        self.funzioni = FunzioniOpzionali(self.log, errore_di_connessione)
        self.pulitore = stati.Pulitore(self.log)
        self.cicli = stati.ContatoreCicli(cicli_iniziali)
        self.versione = ""
        self._prima = True

    def _crea(self) -> Any:
        modulo = self._modulo or carica_pylsv2()
        classe = modulo.LSV2
        opzioni: dict[str, Any] = {"port": self.porta, "timeout": self.timeout, "safe_mode": False}
        try:
            if "compatibility_mode" in inspect.signature(classe).parameters:
                opzioni["compatibility_mode"] = True
        except (TypeError, ValueError):   # classe senza firma introspezionabile
            pass
        return ProxySolaLettura(classe(self.host, **opzioni), LSV2_AMMESSI, NOME_DRIVER, _avvolgi_dati)

    def connetti(self) -> None:
        client = self._crea()
        with self._lock:
            self._client = client
        try:
            client.connect()
        except Exception as e:  # noqa: BLE001 - qualunque errore all'apertura: si chiude e si riprova più tardi
            self.chiudi()
            raise ErroreConnessione(f"connessione LSV2 non riuscita: {type(e).__name__}: {e}") from e
        versioni = client.versions
        self.versione = " ".join(x for x in (str(getattr(versioni, "control", "") or ""),
                                             str(getattr(versioni, "nc_sw", "") or "")) if x)
        self._prima = True
        self.cicli.rebase()

    def _attuale(self) -> Any:
        client = self._client
        if client is None:
            raise ErroreConnessione("connessione LSV2 chiusa")
        return client

    def leggi(self) -> Lettura:
        c = self._attuale()
        f = self.funzioni
        esec = _nome(f.chiama("execution_state", c.execution_state, essenziale=True))
        pgm = _nome(f.chiama("program_status", c.program_status, essenziale=True))
        if esec in (None, "UNDEFINED") and pgm in (None, "UNDEFINED"):
            # Con il login DNC rifiutato pyLSV2 risponde UNDEFINED a tutte le letture di stato.
            raise LoginRifiutato(MSG_OPZIONE_18)
        self._prima = False
        stato, esecuzione, modo = stati.stato_heidenhain(esec, pgm)
        stack = f.chiama("program_stack", c.program_stack)
        ovr = f.chiama("override_state", c.override_state)
        msgs = f.chiama("get_error_messages", c.get_error_messages) or []
        p = self.pulitore
        messaggi = []
        for m in msgs:
            testo = p.testo("messaggio", getattr(m, "e_text", None)) or ""
            codice = "-".join(str(getattr(m, k, "")) for k in ("e_class", "e_group", "e_number"))
            messaggi.append(Messaggio(codice=codice, testo=testo, severita=None))
        self.cicli.aggiorna(esec, pgm)
        line = getattr(stack, "line_no", None) if stack is not None else None
        return Lettura(
            ts=dt.datetime.now(dt.timezone.utc), machine=self.nome, driver=NOME_DRIVER, online=True,
            stato=stato, mode=modo, execution=esecuzione,
            program=p.testo("program", getattr(stack, "main", None)) if stack is not None else None,
            subprogram=p.testo("subprogram", getattr(stack, "current", None)) if stack is not None else None,
            feed_ovr=p.override("feed_ovr", getattr(ovr, "feed", None)) if ovr is not None else None,
            spindle_ovr=p.override("spindle_ovr", getattr(ovr, "spindle", None)) if ovr is not None else None,
            rapid_ovr=p.override("rapid_ovr", getattr(ovr, "rapid", None)) if ovr is not None else None,
            alarm=stato == stati.ALLARME,
            alarm_text=messaggi[0].testo if messaggi else None,
            parts_total=self.cicli.totale,
            messaggi=messaggi,
            line=p.intero("line", line) if isinstance(line, int) and line >= 0 else None,
            raw={"execution_state": esec, "program_status": pgm, "versione": self.versione},
        )

    def chiudi(self) -> None:
        """Logout e chiusura del socket; idempotente, sicuro anche da un altro thread."""
        with self._lock:
            client, self._client = self._client, None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception as e:  # noqa: BLE001 - socket già chiuso o macchina sparita: la connessione è comunque abbandonata
            self.log.debug("disconnessione LSV2 non pulita: %s: %s", type(e).__name__, e)

    def interrompi(self) -> None:
        """Dal sorvegliante, con il thread bloccato in una lettura: chiudere il socket la sblocca."""
        self.chiudi()
