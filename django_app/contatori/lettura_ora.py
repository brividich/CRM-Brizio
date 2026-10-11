"""«Leggi adesso» dei consumabili MFC: un job in coda con stato, mai SNMP nella request.

Lo stato vive in cache (come il lock di coda dei job): ``in_coda`` alla richiesta,
``ok``/``errore`` quando il job ``contatori.tasks.leggi_consumabili`` finisce. Il
frammento HTMX lo interroga finche' la lettura non e' conclusa.
"""
from __future__ import annotations

from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

STATO_SECONDI = 15 * 60
IN_CODA, OK, ERRORE = "in_coda", "ok", "errore"


def _key(pk: int) -> str:
    return f"contatori:lettura_ora:consumabili:{pk}"


def accoda(macchina) -> dict:
    """Mette in coda la lettura (se non c'e' gia') e ritorna lo stato corrente."""
    from .tasks import _enqueue

    corrente = cache.get(_key(macchina.pk))
    if corrente and corrente.get("stato") == IN_CODA:
        _enqueue("contatori.tasks.leggi_consumabili", macchina.pk)  # no-op se gia' in coda
        return corrente
    # Lo stato si scrive PRIMA di accodare: un job velocissimo (o sync) trova la chiave
    # e registra l'esito. Se il job pianificato e' gia' in coda si segue quello.
    stato = {"stato": IN_CODA, "richiesta_il": timezone.now().isoformat()}
    cache.set(_key(macchina.pk), stato, STATO_SECONDI)
    try:
        _enqueue("contatori.tasks.leggi_consumabili", macchina.pk)
    except Exception:
        cache.delete(_key(macchina.pk))
        raise
    return stato


#: Oltre questo tempo una lettura "in coda" e' considerata non completata (worker fermo).
SCADENZA_SECONDI = 180


def stato(pk: int) -> dict | None:
    corrente = cache.get(_key(pk))
    if corrente and corrente.get("stato") == IN_CODA:
        try:
            richiesta = datetime.fromisoformat(corrente["richiesta_il"])
        except (KeyError, ValueError):
            richiesta = None
        if richiesta is None or (timezone.now() - richiesta).total_seconds() > SCADENZA_SECONDI:
            return {"stato": ERRORE, "scaduta": True}
    return corrente


def registra_esito(pk: int, *, ok: bool) -> None:
    """Chiamata dal job: l'errore tecnico resta nei log/django-q, non nel frammento."""
    if cache.get(_key(pk)) is None:
        return  # lettura del job pianificato, nessuno sta aspettando
    cache.set(_key(pk), {"stato": OK if ok else ERRORE, "concluso_il": timezone.now().isoformat()}, STATO_SECONDI)
