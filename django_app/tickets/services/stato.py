"""Cambio di stato di un ticket: una sola implementazione per l'API e per gli OdL.

Prima la logica viveva solo in ``tickets.views.api_stato``: chi chiudeva un
intervento di manutenzione collegato a un ticket non aveva modo di aggiornarlo
senza duplicarla. Qui fa esattamente cio' che faceva la view: date di presa in
carico/chiusura, chi ha risolto, data prevista, log strutturato, commento interno
automatico e specchio SharePoint (solo a transazione confermata).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from django.db import transaction
from django.utils.timezone import now as tz_now

from ..models import StatoTicket, Ticket, TicketCommento, TicketStatoLog

logger = logging.getLogger("tickets.views")

STATI_CHIUSI = (StatoTicket.CHIUSO, StatoTicket.ANNULLATO, StatoTicket.RISOLTO)
STATI_APERTI = (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)


class StatoTicketNonValido(ValueError):
    """Stato richiesto non presente fra ``StatoTicket``."""


def _parse_data_prevista(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _sync_sharepoint(ticket_id: int) -> None:
    # Import tardivo: la funzione resta in views (dove la usano anche le altre API)
    # e i test la sostituiscono li'.
    from .. import views as ticket_views

    ticket = Ticket.objects.filter(pk=ticket_id).first()
    if ticket is None:
        return
    try:
        ticket_views._update_ticket_sharepoint(ticket)
    except Exception:
        logger.exception("Ticket %s: sincronizzazione SharePoint fallita", ticket_id)


def cambia_stato_ticket(
    ticket: Ticket,
    nuovo_stato: str,
    *,
    utente_nome: str,
    utente_email: str = "",
    nota: str = "",
    data_prevista=None,
) -> None:
    """Porta ``ticket`` a ``nuovo_stato`` registrando log e commento automatico.

    ``data_prevista`` (data o stringa ``AAAA-MM-GG``) vale solo per ``IN_ATTESA``;
    una stringa non valida viene ignorata, come nell'API.
    """
    if nuovo_stato not in dict(StatoTicket.choices):
        raise StatoTicketNonValido(nuovo_stato)

    vecchio = ticket.stato
    ticket.stato = nuovo_stato
    now = tz_now()

    if nuovo_stato in STATI_CHIUSI:
        if not ticket.closed_at:
            ticket.closed_at = now
    else:
        ticket.closed_at = None

    update_fields = ["stato", "closed_at", "updated_at"]

    # Analytics: data_presa_in_carico al primo passaggio IN_CARICO
    if nuovo_stato == StatoTicket.IN_CARICO and not ticket.data_presa_in_carico:
        ticket.data_presa_in_carico = now
        update_fields.append("data_presa_in_carico")

    # Data prevista risoluzione quando messo IN_ATTESA
    if nuovo_stato == StatoTicket.IN_ATTESA:
        prevista = _parse_data_prevista(data_prevista)
        if prevista is not None:
            ticket.data_prevista_risoluzione = prevista
            update_fields.append("data_prevista_risoluzione")

    # Analytics: chi ha risolto
    if nuovo_stato == StatoTicket.RISOLTO and not ticket.risolto_da_nome:
        ticket.risolto_da_nome = utente_nome
        update_fields.append("risolto_da_nome")

    with transaction.atomic():
        ticket.save(update_fields=update_fields)

        TicketStatoLog.objects.create(
            ticket=ticket,
            da_stato=vecchio,
            a_stato=nuovo_stato,
            utente_nome=utente_nome,
            utente_email=utente_email,
            nota=nota,
        )

        etichette = dict(StatoTicket.choices)
        testo_auto = f"Stato aggiornato: {etichette.get(vecchio, vecchio)} → {etichette.get(nuovo_stato, nuovo_stato)}"
        if nota:
            testo_auto += f"\n{nota}"
        TicketCommento.objects.create(
            ticket=ticket,
            autore_nome=utente_nome,
            autore_email=utente_email,
            testo=testo_auto,
            is_interno=True,
        )

        ticket_id = ticket.pk
        transaction.on_commit(lambda: _sync_sharepoint(ticket_id))
