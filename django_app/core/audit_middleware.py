"""Middleware che salva il request corrente in thread-local per i segnali di audit."""
from __future__ import annotations

import threading

_thread_local = threading.local()


def get_current_request():
    """Restituisce il request HTTP corrente nel thread attivo, o None."""
    return getattr(_thread_local, "request", None)


class AuditRequestMiddleware:
    """Memorizza il request nel thread-local cosicché i segnali post_save/post_delete
    possano accedere a utente e IP senza dover ricevere il request come argomento."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.request = request
        try:
            return self.get_response(request)
        finally:
            _thread_local.request = None
