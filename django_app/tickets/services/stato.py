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


def e_chi_ha_aperto(ticket: Ticket, *, user_id=None, legacy_id=None, email: str = "") -> bool:
    """La persona e' chi ha aperto il ticket (richiedente o compilatore «per conto di»)?

    Stessi identificativi stabili di ``views._is_richiedente``: mai il solo nome.
    """
    if user_id and user_id in (ticket.richiedente_user_id, ticket.aperto_da_user_id):
        return True
    if legacy_id and ticket.richiedente_legacy_user_id == legacy_id:
        return True
    return bool(email and (ticket.richiedente_email or "").strip().lower() == email.strip().lower())


def stato_di_chiusura(ticket: Ticket, *, user_id=None, legacy_id=None, email: str = "") -> str:
    """Chiudere vale «Chiuso» solo per chi ha aperto il ticket.

    Chiunque altro (tecnico, gestore, OdL) lo porta «Risolto»: la chiusura la
    conferma chi l'ha aperto con «Confermo» (o lo riapre).
    """
    if e_chi_ha_aperto(ticket, user_id=user_id, legacy_id=legacy_id, email=email):
        return StatoTicket.CHIUSO
    return StatoTicket.RISOLTO


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
        if nuovo_stato == StatoTicket.RISOLTO and vecchio != StatoTicket.RISOLTO:
            avvisa_chi_ha_aperto(ticket_id, risolto_da=utente_nome)


def avvisa_chi_ha_aperto(ticket_id: int, *, risolto_da: str = "") -> None:
    """A transazione confermata: mail a chi ha aperto il ticket per confermare la chiusura."""
    from .avviso_conferma import invia_richiesta_conferma

    def _invia():
        ticket = Ticket.objects.select_related("aperto_da_user").filter(pk=ticket_id).first()
        if ticket is not None and ticket.stato == StatoTicket.RISOLTO:
            invia_richiesta_conferma(ticket, risolto_da=risolto_da)

    transaction.on_commit(_invia)
