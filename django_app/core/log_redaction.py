"""Filtro di log che maschera codici fiscali e IBAN (GDPR, 21/10/2026).

I log applicativi (``app.log``, ``qcluster.log``, ``sql.log``) restano sul server
per giorni e finiscono nei backup: un codice fiscale o un IBAN nel testo di un
errore (import cedolini, IntegrityError, parametri SQL) e' un dato personale
fuori dal suo archivio. Il filtro riscrive messaggio e traceback prima che
qualunque handler li scriva: ``RSSMRA80A01H501U`` diventa ``RSS***********01U``.
"""
from __future__ import annotations

import logging
import re

_CF = re.compile(
    r"\b([A-Z]{3})[A-Z]{3}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z]([0-9LMNPQRSTUV]{3}[A-Z])\b",
    re.IGNORECASE,
)
# IBAN: due lettere, due cifre di controllo, 11-30 caratteri alfanumerici maiuscoli.
_IBAN = re.compile(r"\b([A-Z]{2}\d{2})[A-Z0-9]{7,26}([A-Z0-9]{4})\b")
_FORMATTER = logging.Formatter()


def maschera(testo: str) -> str:
    if not testo:
        return testo
    testo = _CF.sub(lambda m: f"{m.group(1)}***********{m.group(2)[-3:]}", testo)
    return _IBAN.sub(lambda m: f"{m.group(1)}****{m.group(2)}", testo)


class MascheraDatiPersonali(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            messaggio = record.getMessage()
            pulito = maschera(messaggio)
            if pulito != messaggio:
                record.msg, record.args = pulito, None
            if record.exc_info and not record.exc_text:
                record.exc_text = _FORMATTER.formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = maschera(record.exc_text)
        except Exception:  # il log non deve mai rompersi per il filtro
            pass
        return True
