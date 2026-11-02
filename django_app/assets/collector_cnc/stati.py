"""Tabelle di mappatura degli stati delle CNC e pulizia dei valori letti: un unico modulo per tutti i driver.

Stati del collector (le parole dell'officina, uguali a quelle del portale e di DMG MORI Messenger):
``LAVORO``, ``SETUP``, ``INTERROTTA``, ``FERMA``, ``ALLARME``, ``EMERGENZA``, ``OFFLINE`` e
``NON_LEGGIBILE`` (la macchina risponde ma non dà lo stato: es. Heidenhain senza opzione #18).

Esecuzione normalizzata (``norm_execution``): ``RUNNING``, ``INTERRUPTED``, ``IDLE``, ``ALARM``,
``OFFLINE``, ``UNKNOWN``. Modalità normalizzata: ``AUTO``, ``MDI``, ``MANUAL``, ``SINGLE_STEP``, ``REF``,
``EDIT``, ``UNKNOWN``.

Le tabelle Heidenhain e Fanuc sono quelle decise per il collaudo (requisito D); i test le coprono
riga per riga. I contatori dei cicli (LSV2) e dei pezzi (FOCAS) stanno qui perché sono logica di
dato, non di libreria.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

# --- stati del collector -------------------------------------------------------------------------
OFFLINE: Final = "OFFLINE"
EMERGENZA: Final = "EMERGENZA"
ALLARME: Final = "ALLARME"
LAVORO: Final = "LAVORO"
SETUP: Final = "SETUP"
INTERROTTA: Final = "INTERROTTA"
FERMA: Final = "FERMA"
NON_LEGGIBILE: Final = "NON_LEGGIBILE"
STATI: Final = frozenset({OFFLINE, EMERGENZA, ALLARME, LAVORO, SETUP, INTERROTTA, FERMA, NON_LEGGIBILE})

ESECUZIONI: Final = frozenset({"RUNNING", "INTERRUPTED", "IDLE", "ALARM", "OFFLINE", "UNKNOWN"})

# --- esecuzione generica -------------------------------------------------------------------------
_ESECUZIONE_TESTO: Final[Mapping[str, str]] = {
    "RUNNING": "RUNNING", "ACTIVE": "RUNNING", "STARTED": "RUNNING", "START": "RUNNING", "EXECUTING": "RUNNING",
    "INTERRUPTED": "INTERRUPTED", "STOPPED": "INTERRUPTED", "STOP": "INTERRUPTED", "HOLD": "INTERRUPTED",
    "FEED_HOLD": "INTERRUPTED", "OPTIONAL_STOP": "INTERRUPTED", "PROGRAM_STOPPED": "INTERRUPTED",
    "IDLE": "IDLE", "READY": "IDLE", "RESET": "IDLE", "FINISHED": "IDLE", "CANCELLED": "IDLE",
    "PROGRAM_COMPLETED": "IDLE", "ERROR_CLEARED": "IDLE",
    "ALARM": "ALARM", "ERROR": "ALARM", "FAULT": "ALARM",
    "OFFLINE": "OFFLINE", "UNAVAILABLE": "OFFLINE",
}


def norm_execution(value: Any, custom_map: Mapping[Any, str] | None = None) -> str:
    """Stato di esecuzione eterogeneo -> una voce di ``ESECUZIONI``.

    ``custom_map`` (da configurazione) traduce i codici numerici o testuali di una macchina: vince
    sulla tabella generica. Un valore che non si riconosce dà ``UNKNOWN``, mai un'eccezione.
    """
    if custom_map:
        for chiave in (value, str(value)):
            try:
                tradotto = custom_map.get(chiave)
            except TypeError:   # chiave non hashable (es. una lista letta per errore)
                tradotto = None
            if tradotto is not None:
                tradotto = str(tradotto).strip().upper()
                return tradotto if tradotto in ESECUZIONI else "UNKNOWN"
    if isinstance(value, bool) or value is None:
        return "UNKNOWN"
    nome = getattr(value, "name", value)   # enum (es. pyLSV2.PgmState) -> nome
    return _ESECUZIONE_TESTO.get(str(nome).strip().upper().replace(" ", "_"), "UNKNOWN")


# --- Heidenhain (LSV2) ---------------------------------------------------------------------------
# ExecState: MANUAL, MDI, PASS_REFERENCES, SINGLE_STEP, AUTOMATIC, UNDEFINED
HEIDENHAIN_MODO: Final[Mapping[str, str]] = {
    "AUTOMATIC": "AUTO", "MANUAL": "MANUAL", "MDI": "MDI", "SINGLE_STEP": "SINGLE_STEP",
    "PASS_REFERENCES": "REF", "UNDEFINED": "UNKNOWN",
}
# PgmState -> (stato del collector, esecuzione) per i casi che non dipendono dalla modalità
HEIDENHAIN_PROGRAMMA: Final[Mapping[str, tuple[str, str]]] = {
    "ERROR": (ALLARME, "ALARM"),
    "STOPPED": (INTERROTTA, "INTERRUPTED"),
    "INTERRUPTED": (INTERROTTA, "INTERRUPTED"),
    "IDLE": (FERMA, "IDLE"),
    "FINISHED": (FERMA, "IDLE"),
    "CANCELLED": (FERMA, "IDLE"),
    "ERROR_CLEARED": (FERMA, "IDLE"),
    "UNDEFINED": (FERMA, "UNKNOWN"),
}


def stato_heidenhain(esecuzione: str | None, programma: str | None) -> tuple[str, str, str]:
    """``(stato, esecuzione normalizzata, modalità)`` da ExecState e PgmState (nomi degli enum).

    STARTED + AUTOMATIC = LAVORO; STARTED in MANUAL, MDI, SINGLE_STEP, PASS_REFERENCES (o modalità
    non definita) = SETUP; STOPPED/INTERRUPTED = INTERROTTA; ERROR = ALLARME; IDLE, FINISHED,
    CANCELLED, ERROR_CLEARED = FERMA.
    """
    modo = HEIDENHAIN_MODO.get(str(esecuzione or "UNDEFINED"), "UNKNOWN")
    pgm = str(programma or "UNDEFINED")
    if pgm == "STARTED":
        return (LAVORO if modo == "AUTO" else SETUP), "RUNNING", modo
    stato, esec = HEIDENHAIN_PROGRAMMA.get(pgm, (FERMA, "UNKNOWN"))
    return stato, esec, modo


class ContatoreCicli:
    """Cicli Heidenhain: +1 sul fronte verso FINISHED, una volta sola, se la macchina era in AUTOMATIC.

    La prima lettura (anche dopo una riconnessione) è solo la base: un FINISHED già presente non conta.
    """

    def __init__(self, totale: int = 0) -> None:
        self.totale = totale
        self._programma: str | None = None
        self._esecuzione: str | None = None
        self._base = False

    def rebase(self) -> None:
        """Dopo una riconnessione: la prossima lettura è di nuovo solo la base."""
        self._base = False

    def aggiorna(self, esecuzione: str | None, programma: str | None) -> bool:
        """True se questa lettura chiude un ciclo."""
        contato = False
        if self._base and programma == "FINISHED" and self._programma != "FINISHED":
            if (self._esecuzione or esecuzione) == "AUTOMATIC":
                self.totale += 1
                contato = True
        self._programma, self._esecuzione, self._base = programma, esecuzione, True
        return contato


# --- Fanuc (FOCAS, struttura ODBST serie 30i/0i-D/F) -----------------------------------------------
FANUC_AUT: Final[Mapping[int, str]] = {
    0: "MDI", 1: "AUTO", 2: "UNKNOWN", 3: "EDIT", 4: "MANUAL", 5: "MANUAL", 6: "MANUAL", 7: "MANUAL",
    8: "MANUAL", 9: "REF", 10: "AUTO",
}
FANUC_AUT_LAVORO: Final = frozenset({1, 10})          # MEM, RMT
FANUC_AUT_SETUP: Final = frozenset({0, 4, 5, 8, 9})   # MDI, HND, JOG, INC, REF
FANUC_RUN_RESET, FANUC_RUN_STOP, FANUC_RUN_HOLD, FANUC_RUN_START, FANUC_RUN_MSTR = 0, 1, 2, 3, 4


def stato_fanuc(aut: int, run: int, emergency: int, alarm: int) -> tuple[str, str, str]:
    """``(stato, esecuzione normalizzata, modalità)`` da ``cnc_statinfo``.

    emergency != 0 = EMERGENZA (priorità massima); alarm != 0 = ALLARME; run START (o MSTR) in
    MEM/RMT = LAVORO, in MDI/JOG/HND/INC/REF (o altre modalità) = SETUP; run STOP/HOLD = INTERROTTA;
    run RESET = FERMA.
    """
    modo = FANUC_AUT.get(aut, "UNKNOWN")
    if emergency != 0:
        return EMERGENZA, "ALARM", modo
    if alarm != 0:
        return ALLARME, "ALARM", modo
    if run in (FANUC_RUN_START, FANUC_RUN_MSTR):
        return (LAVORO if aut in FANUC_AUT_LAVORO else SETUP), "RUNNING", modo
    if run in (FANUC_RUN_STOP, FANUC_RUN_HOLD):
        return INTERROTTA, "INTERRUPTED", modo
    if run == FANUC_RUN_RESET:
        return FERMA, "IDLE", modo
    return FERMA, "UNKNOWN", modo


@dataclass
class EsitoPezzi:
    delta: int
    azzerato: bool


class ContatorePezzi:
    """Pezzi Fanuc (parametro 6711, cumulativo e azzerabile dall'operatore).

    Primo valore = base; poi si somma la differenza. Una differenza negativa è un azzeramento: non si
    sottrae niente e il nuovo valore diventa la base. ``ultimo_grezzo`` può arrivare da machines.db:
    così i pezzi fatti mentre il collector era fermo non si perdono.
    """

    def __init__(self, totale: int = 0, ultimo_grezzo: int | None = None) -> None:
        self.totale = totale
        self.ultimo_grezzo = ultimo_grezzo

    def aggiorna(self, grezzo: int) -> EsitoPezzi:
        precedente, self.ultimo_grezzo = self.ultimo_grezzo, grezzo
        if precedente is None:
            return EsitoPezzi(0, False)
        if grezzo < precedente:
            return EsitoPezzi(0, True)
        self.totale += grezzo - precedente
        return EsitoPezzi(grezzo - precedente, False)


# --- pulizia dei valori --------------------------------------------------------------------------
OVERRIDE_MIN, OVERRIDE_MAX = 0.0, 200.0
CONTATORE_MAX = 10**12
TESTO_MAX = 200


class LogLimitato:
    """Un messaggio per chiave al massimo ogni ``intervallo`` secondi, con quanti ne sono stati taciuti."""

    def __init__(self, log: logging.Logger | logging.LoggerAdapter[logging.Logger], intervallo: float = 300.0) -> None:
        self.log = log
        self.intervallo = intervallo
        self._ultimo: dict[str, float] = {}
        self._taciuti: dict[str, int] = {}

    def warning(self, chiave: str, msg: str, *args: Any) -> bool:
        ora = time.monotonic()
        ultimo = self._ultimo.get(chiave)
        if ultimo is not None and ora - ultimo < self.intervallo:
            self._taciuti[chiave] = self._taciuti.get(chiave, 0) + 1
            return False
        taciuti = self._taciuti.pop(chiave, 0)
        self._ultimo[chiave] = ora
        self.log.warning(msg + (f" (altri {taciuti} uguali taciuti)" if taciuti else ""), *args)
        return True


class Pulitore:
    """Scarta i valori anomali (NaN, override fuori 0–200 %, stringhe vuote, tipi inattesi) con log limitato."""

    def __init__(self, log: logging.Logger | logging.LoggerAdapter[logging.Logger]) -> None:
        self.avvisi = LogLimitato(log)
        self.scartati = 0

    def _scarta(self, campo: str, valore: Any, motivo: str) -> None:
        self.scartati += 1
        self.avvisi.warning(f"{campo}:{motivo}", "valore scartato per %s: %r (%s)", campo, valore, motivo)

    def numero(self, campo: str, valore: Any, minimo: float = 0.0, massimo: float = float(CONTATORE_MAX)) -> float | None:
        if valore is None:
            return None
        if isinstance(valore, bool) or not isinstance(valore, (int, float)):
            self._scarta(campo, valore, "tipo inatteso")
            return None
        if not math.isfinite(valore):
            self._scarta(campo, valore, "non finito")
            return None
        if not minimo <= valore <= massimo:
            self._scarta(campo, valore, f"fuori da {minimo:g}–{massimo:g}")
            return None
        return float(valore)

    def override(self, campo: str, valore: Any) -> float | None:
        return self.numero(campo, valore, OVERRIDE_MIN, OVERRIDE_MAX)

    def intero(self, campo: str, valore: Any) -> int | None:
        numero = self.numero(campo, valore)
        if numero is None:
            return None
        if not numero.is_integer():
            self._scarta(campo, valore, "non intero")
            return None
        return int(numero)

    def testo(self, campo: str, valore: Any, vuoto_ammesso: bool = True) -> str | None:
        """Testo ripulito; ``""`` resta ``""`` solo se ammesso (es. nessun programma selezionato)."""
        if valore is None:
            return None
        if isinstance(valore, bytes):
            valore = valore.split(b"\0", 1)[0].decode("latin-1", errors="replace")
        if not isinstance(valore, str):
            self._scarta(campo, valore, "tipo inatteso")
            return None
        pulito = "".join(c for c in valore if c.isprintable()).strip()[:TESTO_MAX]
        if not pulito and not vuoto_ammesso:
            self._scarta(campo, valore, "vuoto")
            return None
        return pulito
