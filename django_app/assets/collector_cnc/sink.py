"""Uscite del collector oltre a machines.db: interfaccia ``Sink`` e uscita su file (``--jsonl DIR``).

``Sink.write(record)`` riceve il record normalizzato di una macchina (stesso formato per tutti i driver)
a ogni cambio e a ogni battito. Un'uscita nuova (PostgreSQL, MQTT…) si aggiunge implementando
``Sink`` senza toccare i driver.

``CartellaJsonl``:
- ``<dir>/<macchina>/<AAAA-MM-GG>.jsonl``: un record per riga, in append (data UTC del record);
- ``<dir>/status.json``: l'ultimo record di ogni macchina, scritto in modo atomico (file temporaneo e
  ``os.replace``), con qualche tentativo se su Windows il file è aperto da un altro programma.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("collector")

TENTATIVI_REPLACE = 5
ATTESA_REPLACE = 0.2   # s


class Sink(Protocol):
    def write(self, record: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


def _nome_file(nome: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in nome) or "_"


class CartellaJsonl:
    """JSONL per macchina e giorno, più ``status.json`` con l'ultimo stato di tutte."""

    def __init__(self, cartella: str | Path) -> None:
        self.cartella = Path(cartella)
        self.cartella.mkdir(parents=True, exist_ok=True)
        self.ultimi: dict[str, dict[str, Any]] = {}
        self.errori = 0

    def write(self, record: dict[str, Any]) -> None:
        macchina = str(record.get("machine") or "_")
        giorno = str(record.get("ts") or "")[:10] or time.strftime("%Y-%m-%d", time.gmtime())
        file = self.cartella / _nome_file(macchina) / f"{giorno}.jsonl"
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as e:
            self.errori += 1
            log.warning("uscita JSONL non scritta (%s): %s", file, e)
        self.ultimi[macchina] = record
        self._status()

    def _status(self) -> None:
        dest = self.cartella / "status.json"
        tmp = dest.with_name(f"status.json.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(self.ultimi, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        except OSError as e:
            self.errori += 1
            log.warning("status.json non scritto: %s", e)
            return
        for tentativo in range(TENTATIVI_REPLACE):
            try:
                os.replace(tmp, dest)
                return
            except PermissionError:   # Windows: file aperto da un altro programma (editor, antivirus)
                if tentativo == TENTATIVI_REPLACE - 1:
                    break
                time.sleep(ATTESA_REPLACE)
        self.errori += 1
        log.warning("status.json bloccato da un altro programma: aggiornamento saltato")
        try:
            tmp.unlink()
        except OSError as e:
            log.debug("file temporaneo non cancellato: %s", e)

    def close(self) -> None:
        """Niente da chiudere: ogni scrittura apre e chiude il file."""
