"""Un thread per macchina per i driver bloccanti (LSV2, FOCAS), con sorvegliante e ritmo di lettura.

- ``Ritmo``: polling di default 5 s, mai sotto ``POLL_MINIMO`` (2 s) anche se la configurazione dice
  meno, jitter ±5 %, avvio scaglionato a caso, backoff esponenziale da ``poll`` fino a 300 s.
- ``Lavoratore`` (``threading.Thread``): una sola connessione persistente, riusata a ogni lettura;
  consegna i record con ``consegna`` (in produzione: la coda del ciclo asincrono). Lo stop è un
  ``threading.Event``: le attese si interrompono subito e la connessione si chiude sempre.
- ``Sorvegliante``: se una chiamata alla libreria dura più di 3 volte il timeout il thread è
  considerato bloccato: la connessione viene interrotta, il thread abbandonato (i suoi record non
  passano più) e ne parte uno nuovo con un driver nuovo. L'evento è loggato e contato.
- ``Orologio``: avvisa se l'orologio di sistema salta di oltre 60 s rispetto a quello monotono.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

try:
    from .drivers.base import DriverSincrono, ErroreConnessione, LibreriaAssente, Lettura, Log, LoginRifiutato
    from .stati import NON_LEGGIBILE, OFFLINE
except ImportError:   # sul PC dell'officina (py collector.py)
    from drivers.base import (  # type: ignore[no-redef]
        DriverSincrono,
        ErroreConnessione,
        LibreriaAssente,
        Lettura,
        Log,
        LoginRifiutato,
    )
    from stati import NON_LEGGIBILE, OFFLINE  # type: ignore[no-redef]

POLL_DEFAULT = 5.0
POLL_MINIMO = 2.0
JITTER = 0.05
BACKOFF_MASSIMO = 300.0
FATTORE_BLOCCO = 3.0
SALTO_OROLOGIO = 60.0


class Ritmo:
    """Quando leggere: polling con jitter, avvio scaglionato, backoff esponenziale."""

    def __init__(self, poll: float | None = None, rng: random.Random | None = None, log: Log | None = None) -> None:
        richiesto = POLL_DEFAULT if poll is None else float(poll)
        self.poll = max(POLL_MINIMO, richiesto)
        if richiesto < POLL_MINIMO and log is not None:
            log.warning("polling di %.1f s sotto il minimo: uso %.1f s", richiesto, POLL_MINIMO)
        self.rng = rng or random.Random()

    def attesa(self) -> float:
        """Prossima attesa tra due letture: poll ±5 %, mai sotto il minimo."""
        return max(POLL_MINIMO, self.poll * (1 + self.rng.uniform(-JITTER, JITTER)))

    def avvio(self) -> float:
        """Ritardo casuale della prima lettura, per non interrogare tutte le macchine insieme."""
        return self.rng.uniform(0, self.poll)

    def backoff(self, tentativi: int) -> float:
        """Attesa dopo ``tentativi`` fallimenti consecutivi: poll, 2×poll, 4×poll… fino a 300 s."""
        base = min(self.poll * (2.0 ** max(0, tentativi - 1)), BACKOFF_MASSIMO)
        return max(POLL_MINIMO, min(BACKOFF_MASSIMO, base * (1 + self.rng.uniform(-JITTER, JITTER))))


class Orologio:
    """Confronta orologio di sistema e monotono: un salto oltre la soglia si segnala una volta."""

    def __init__(self, log: Log, soglia: float = SALTO_OROLOGIO,
                 parete: Callable[[], float] = time.time, monotono: Callable[[], float] = time.monotonic) -> None:
        self.log, self.soglia, self._parete, self._monotono = log, soglia, parete, monotono
        self.salti = 0
        self._riallinea()

    def _riallinea(self) -> None:
        self._p0, self._m0 = self._parete(), self._monotono()

    def controlla(self) -> float | None:
        """Secondi di salto se l'orologio di sistema si è spostato oltre la soglia, altrimenti None."""
        salto = (self._parete() - self._p0) - (self._monotono() - self._m0)
        if abs(salto) <= self.soglia:
            return None
        self.salti += 1
        self.log.warning("l'orologio di sistema è saltato di %+.0f s: i timestamp seguono il nuovo orario, "
                         "le durate restano misurate con l'orologio monotono", salto)
        self._riallinea()
        return salto


def lettura_fuori_linea(nome: str, driver: str, stato: str, errore: str) -> Lettura:
    return Lettura(ts=dt.datetime.now(dt.timezone.utc), machine=nome, driver=driver, online=False,
                   stato=stato, execution="OFFLINE" if stato == OFFLINE else "UNKNOWN", errore=errore)


class Lavoratore(threading.Thread):
    """Il thread di una macchina: connessione persistente, letture a ritmo, riconnessione con backoff."""

    def __init__(self, nome: str, crea_driver: Callable[[], DriverSincrono], ritmo: Ritmo,
                 consegna: Callable[[Lettura], None], stop: threading.Event, log: Log, generazione: int = 0) -> None:
        super().__init__(name=f"cnc-{nome}-{generazione}", daemon=True)
        self.nome = nome
        self.crea_driver = crea_driver
        self.ritmo = ritmo
        self._consegna = consegna
        self.stop = stop
        self.log = log
        self.abbandonato = threading.Event()
        self.driver: DriverSincrono | None = None
        self.in_chiamata_dal: float | None = None
        self.timeout = 5.0
        self.ultimo_stato: str | None = None
        self.connessioni = 0
        self.letture = 0

    # ---------------- chiamate sorvegliate ----------------
    def _chiama(self, fn: Callable[[], Any]) -> Any:
        self.in_chiamata_dal = time.monotonic()
        try:
            return fn()
        finally:
            self.in_chiamata_dal = None

    def bloccato(self, ora: float | None = None) -> bool:
        """True se una chiamata alla libreria dura da più di 3 volte il timeout."""
        inizio = self.in_chiamata_dal
        return inizio is not None and (ora or time.monotonic()) - inizio > FATTORE_BLOCCO * self.timeout

    def abbandona(self) -> None:
        """Dal sorvegliante: da qui in poi i record di questo thread non passano e la connessione si interrompe."""
        self.abbandonato.set()
        driver = self.driver
        if driver is not None:
            try:
                driver.interrompi()
            except Exception as e:  # noqa: BLE001 - interruzione al meglio: il thread è comunque abbandonato
                self.log.debug("interruzione della connessione non riuscita: %s", e)

    def _attivo(self) -> bool:
        return not self.stop.is_set() and not self.abbandonato.is_set()

    def consegna(self, lettura: Lettura) -> None:
        if self.abbandonato.is_set():
            return
        self._consegna(lettura)

    def _fuori_linea(self, stato: str, errore: str, attesa: float) -> None:
        if stato != self.ultimo_stato:
            if stato == NON_LEGGIBILE:
                self.log.error("%s; ritento ogni %.0f s", errore, attesa)
            else:
                self.log.warning("non raggiungibile (%s), ritento tra %.0f s", errore, attesa)
        self.ultimo_stato = stato
        driver = self.driver
        nome_driver = driver.nome_driver if driver is not None else ""
        self.consegna(lettura_fuori_linea(self.nome, nome_driver, stato, errore))

    def _chiudi(self) -> None:
        driver, self.driver = self.driver, None
        if driver is not None:
            try:
                driver.chiudi()
            except Exception as e:  # noqa: BLE001 - chiusura al meglio: la connessione è comunque abbandonata
                self.log.debug("chiusura della connessione non riuscita: %s", e)

    # ---------------- ciclo ----------------
    def run(self) -> None:
        if self.stop.wait(self.ritmo.avvio()):
            return
        tentativi = 0
        try:
            while self._attivo():
                if self.driver is None:
                    driver = self.crea_driver()
                    self.driver, self.timeout = driver, float(driver.timeout)
                    try:
                        self._chiama(driver.connetti)
                    except ErroreConnessione as e:
                        tentativi += 1
                        attesa = BACKOFF_MASSIMO if isinstance(e, (LoginRifiutato, LibreriaAssente)) else self.ritmo.backoff(tentativi)
                        stato = NON_LEGGIBILE if isinstance(e, (LoginRifiutato, LibreriaAssente)) else OFFLINE
                        self._fuori_linea(stato, str(e), attesa)
                        self._chiudi()
                        self.stop.wait(attesa)
                        continue
                    self.connessioni += 1
                    self.log.info("connessa")
                try:
                    lettura: Lettura = self._chiama(self.driver.leggi)
                except LoginRifiutato as e:
                    tentativi += 1
                    self._fuori_linea(NON_LEGGIBILE, str(e), BACKOFF_MASSIMO)
                    self._chiudi()
                    self.stop.wait(BACKOFF_MASSIMO)
                    continue
                except Exception as e:  # noqa: BLE001 - connessione persa o errore imprevisto del driver: si riconnette
                    if not isinstance(e, ErroreConnessione):
                        self.log.warning("errore imprevisto del driver, riconnetto: %s: %s", type(e).__name__, e)
                    tentativi += 1
                    attesa = self.ritmo.backoff(tentativi)
                    self._fuori_linea(OFFLINE, f"{type(e).__name__}: {e}", attesa)
                    self._chiudi()
                    self.stop.wait(attesa)
                    continue
                tentativi = 0
                self.letture += 1
                if self.ultimo_stato in (OFFLINE, NON_LEGGIBILE):
                    self.log.info("di nuovo leggibile")
                self.ultimo_stato = lettura.stato
                self.consegna(lettura)
                self.stop.wait(self.ritmo.attesa())
        finally:
            self._chiudi()


class Sorvegliante:
    """Tiene in vita il ``Lavoratore`` di una macchina e lo sostituisce se resta bloccato."""

    def __init__(self, nome: str, crea_driver: Callable[[], DriverSincrono], ritmo: Ritmo,
                 consegna: Callable[[Lettura], None], log: Log) -> None:
        self.nome, self.crea_driver, self.ritmo, self.consegna, self.log = nome, crea_driver, ritmo, consegna, log
        self.stop = threading.Event()
        self.generazione = 0
        self.bloccati = 0
        self.abbandonati: list[Lavoratore] = []
        self.lavoratore = self._nuovo()

    def _nuovo(self) -> Lavoratore:
        self.generazione += 1
        return Lavoratore(self.nome, self.crea_driver, self.ritmo, self.consegna, self.stop, self.log, self.generazione)

    def avvia(self) -> None:
        self.lavoratore.start()

    def controlla(self, ora: float | None = None) -> bool:
        """Da chiamare spesso (es. ogni secondo): True se ha dovuto sostituire un thread bloccato."""
        self.abbandonati = [t for t in self.abbandonati if t.is_alive()]
        attuale = self.lavoratore
        if not attuale.bloccato(ora):
            return False
        self.bloccati += 1
        self.log.error("thread bloccato in una lettura da oltre %.0f s: connessione interrotta, riparto con un "
                       "driver nuovo (blocco n. %d)", FATTORE_BLOCCO * attuale.timeout, self.bloccati)
        attuale.abbandona()
        self.abbandonati.append(attuale)
        self.lavoratore = self._nuovo()
        if not self.stop.is_set():
            self.lavoratore.start()
        self.consegna(lettura_fuori_linea(self.nome, "", OFFLINE, "lettura bloccata: thread sostituito"))
        return True

    def ferma(self, timeout: float = 10.0) -> list[str]:
        """Stop pulito: segnala, aspetta i thread fino a ``timeout`` secondi; ritorna quelli rimasti vivi."""
        self.stop.set()
        limite = time.monotonic() + timeout
        vivi = []
        for t in [self.lavoratore, *self.abbandonati]:
            if t.ident is None:
                continue
            t.join(max(0.0, limite - time.monotonic()))
            if t.is_alive():
                vivi.append(t.name)
        if vivi:
            self.log.error("thread non terminati entro %.0f s: %s (abbandonati, sono daemon)", timeout, ", ".join(vivi))
        return vivi


def log_macchina(nome: str, driver: str, host: str, base: logging.Logger | None = None) -> logging.LoggerAdapter[logging.Logger]:
    """Logger con il contesto della macchina in ogni riga: ``[DM6 lsv2 192.168.23.114] …``."""
    return _LogMacchina(base or logging.getLogger("collector"), {"macchina": nome, "driver": driver, "host": host})


class _LogMacchina(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        e = self.extra or {}
        kwargs.setdefault("extra", {}).update(e)
        return f"[{e.get('macchina')} {e.get('driver')} {e.get('host')}] {msg}", kwargs
