"""Lavori django-q della sezione Ordini di produzione: lettura dei report CMM dalla share."""
from __future__ import annotations

import time

from django.core.cache import cache

from automazioni.system_runlog import system_job_run

from . import report_cmm_indice as indice

_BLOCCO_GIRO = "produzione_report_cmm_giro"
_BLOCCO_PN = "produzione_report_cmm_pn:{}"
TIMEOUT = 900  # q_options: oltre i 120 s del cluster
_MINUTI_PN = 13


@system_job_run("produzione_report_cmm_giro")
def run_giro_report_cmm():
    """Giro pianificato. La riconsegna del broker (retry 180 s) trova il blocco ed esce subito."""
    if not cache.add(_BLOCCO_GIRO, 1, TIMEOUT):
        return {"skipped": "giro già in corso"}
    try:
        minuti = min(indice.settings.PRODUZIONE_REPORT_CMM_MINUTI, _MINUTI_PN)
        return indice.giro(minuti)
    finally:
        cache.delete(_BLOCCO_GIRO)


def run_leggi_pn(pn: str):
    """Pulsante «Leggi i report» della scheda P/N: solo la cartella di quel P/N."""
    chiave = _BLOCCO_PN.format(indice.normalize_part_number(pn))
    if not cache.add(chiave, 1, TIMEOUT):
        return {"saltato": "lettura già in corso"}
    try:
        percorso = indice.cartella_del_pn(pn)
        if not percorso:
            return {"errore": "Nessuna cartella per questo P/N nella share dei report."}
        return indice.leggi_cartella(pn, percorso, time.monotonic() + _MINUTI_PN * 60)
    finally:
        cache.delete(chiave)


def accoda_lettura_pn(pn: str) -> bool:
    """Accoda la lettura del P/N; ``False`` se già in corso."""
    from django_q.tasks import async_task

    if cache.get(_BLOCCO_PN.format(indice.normalize_part_number(pn))):
        return False
    async_task("produzione.tasks.run_leggi_pn", pn, q_options={"timeout": TIMEOUT})
    return True
