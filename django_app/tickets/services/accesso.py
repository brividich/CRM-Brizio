"""Regola di accesso in gestione a un singolo ticket, riusabile fuori da ``tickets``."""

from __future__ import annotations


def utente_puo_gestire_ticket(request, ticket) -> bool:
    """True se l'utente puo' gestire *questo* ticket: gestore del suo tipo o admin legacy.

    E' la stessa regola di ``tickets.views._api_require_ticket_access``, che la usa.
    """
    if request is None or not getattr(request.user, "is_authenticated", False):
        return False
    from ..views import _ticket_access_flags

    access = _ticket_access_flags(request, ticket)
    return bool(access["is_gestore"] or access["is_admin"])


def puo_aprire_ticket(request, tipo: str) -> bool:
    """True se l'utente puo' aprire un ticket del tipo dato (stessa regola del form «Nuovo ticket»)."""
    from ..views import _can_open_tickets

    return _can_open_tickets(request, tipo)


def identita_utente(request) -> tuple[str, str]:
    """Nome ed email con cui firmare log e commenti del ticket (come le API ticket)."""
    from ..views import _legacy_identity

    name, email, _ = _legacy_identity(request)
    return name, email
