"""Collegamenti HTTP ai servizi AI in rete interna (Ollama, TEI, Open WebUI) e scadenza dei giri.

Il server ha ``HTTPS_PROXY``/``HTTP_PROXY`` per i servizi internet: l'opener di default di urllib
e ``requests`` li applicano anche alle chiamate verso la LAN, che passano dal proxy (lente o
respinte). Qui l'opener ignora il proxy (``ProxyHandler({})``) e la Session ha ``trust_env=False``,
come ``security.services.veeam_api``.

La **scadenza** (``scadenza``) è il tempo massimo di un giro pianificato: dentro il blocco ogni
chiamata all'AI usa come timeout il minimo fra quello configurato e il tempo che resta, così la
somma delle chiamate non supera il tempo del worker django-q.
"""
from __future__ import annotations

import contextlib
import contextvars
import socket
import time
import urllib.error
import urllib.request

_LAN_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_SCADENZA: contextvars.ContextVar[float | None] = contextvars.ContextVar("ai_scadenza", default=None)

# Sotto questo tempo residuo una nuova chiamata non parte nemmeno: finirebbe comunque in timeout.
RESIDUO_MINIMO = 3


def lan_urlopen(request, timeout=None):
    """Come ``urllib.request.urlopen`` ma senza proxy d'ambiente (servizi in rete interna)."""
    if timeout is None:
        return _LAN_OPENER.open(request)
    return _LAN_OPENER.open(request, timeout=timeout)


def lan_session():
    """Session ``requests`` per i servizi in rete interna: ignora proxy e variabili d'ambiente."""
    import requests

    session = requests.Session()
    session.trust_env = False
    return session


# --- Scadenza dei giri --------------------------------------------------------------------------

@contextlib.contextmanager
def scadenza(secondi):
    """Le chiamate all'AI dentro il blocco finiscono entro ``secondi`` da adesso (la più stretta vince)."""
    nuova = time.monotonic() + max(0.0, float(secondi))
    attuale = _SCADENZA.get()
    token = _SCADENZA.set(nuova if attuale is None else min(attuale, nuova))
    try:
        yield
    finally:
        _SCADENZA.reset(token)


def residuo():
    """Secondi che restano alla scadenza in corso, o None se non c'è una scadenza."""
    fine = _SCADENZA.get()
    return None if fine is None else fine - time.monotonic()


def timeout_entro_scadenza(timeout):
    """Timeout della singola chiamata: min(timeout configurato, tempo che resta alla scadenza)."""
    resta = residuo()
    if resta is None:
        return timeout
    return max(1, min(int(timeout), int(resta)))


def scadenza_vicina():
    """True se manca troppo poco alla scadenza per far partire una nuova chiamata."""
    resta = residuo()
    return resta is not None and resta < RESIDUO_MINIMO


# --- Classificazione degli errori di rete -------------------------------------------------------

def tipo_errore(exc):
    """'timeout', 'connessione' o 'http' per un errore di urllib/requests (per messaggi e log)."""
    if isinstance(exc, urllib.error.HTTPError):
        return "http"
    reason = getattr(exc, "reason", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    try:
        import requests

        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout"
        if isinstance(exc, requests.exceptions.HTTPError):
            return "http"
    except ImportError:  # pragma: no cover - requests è una dipendenza del progetto
        pass
    return "connessione"
