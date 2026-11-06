"""Le due azioni del tecnico: prendere un ticket e chiuderlo con l'intervento fatto.

Stessa logica per la scheda, per l'elenco e per «Già risolto» nel form di apertura.
"""

from __future__ import annotations

from django.db import transaction

from ..models import (
    EsitoIntervento,
    StatoTicket,
    Ticket,
    TicketCommento,
    TicketIntervento,
    TipoFermo,
)
from .stato import _sync_sharepoint, cambia_stato_ticket


def prendi_in_carico(ticket: Ticket, *, nome: str, email: str = "") -> None:
    """Assegna il ticket a chi clicca e lo porta «In carico» se non lo era già."""
    with transaction.atomic():
        ticket.assegnato_a = nome[:200]
        ticket.assegnato_email = email[:200]
        ticket.save(update_fields=["assegnato_a", "assegnato_email", "updated_at"])
        TicketCommento.objects.create(
            ticket=ticket,
            autore_nome=nome,
            autore_email=email,
            testo=f"Ticket assegnato a: {nome}",
            is_interno=True,
        )
        if ticket.stato != StatoTicket.IN_CARICO:
            cambia_stato_ticket(ticket, StatoTicket.IN_CARICO, utente_nome=nome, utente_email=email)
        else:
            ticket_id = ticket.pk
            transaction.on_commit(lambda: _sync_sharepoint(ticket_id))


def chiudi_con_intervento(
    ticket: Ticket,
    *,
    nome: str,
    email: str = "",
    lavoro: str,
    inizio,
    fine,
    ore=None,
    tecnico: str = "",
    tipo_fermo: str = "",
    ore_fermo=None,
    componente: str = "",
    causa: str = "",
    ricorrente: bool = False,
    materiali=None,
    rapportino: str = "",
    nota: str = "",
) -> TicketIntervento:
    """Registra l'intervento concluso e chiude il ticket, tutto o niente."""
    with transaction.atomic():
        intervento = TicketIntervento.objects.create(
            ticket=ticket,
            tecnico_nome=(tecnico or nome)[:200],
            tecnico_email=email[:200],
            data_inizio=inizio,
            data_fine=fine,
            ore_lavorate=ore,
            descrizione_lavoro=lavoro,
            componente_interessato=componente[:200],
            esito=EsitoIntervento.COMPLETATO,
            materiali_costo_eur=materiali,
            numero_rapportino=rapportino[:50],
        )

        campi = ["closed_at", "risolto_da_nome", "updated_at"]
        # Una visita di ieri su un ticket di oggi non deve dare una chiusura prima dell'apertura.
        ticket.closed_at = max(fine, ticket.created_at)
        ticket.risolto_da_nome = ticket.risolto_da_nome or nome
        if not ticket.data_primo_intervento:
            ticket.data_primo_intervento = inizio
            campi.append("data_primo_intervento")
        if not ticket.assegnato_a and not ticket.delegato_fornitore_id:
            ticket.assegnato_a = nome[:200]
            ticket.assegnato_email = email[:200]
            campi += ["assegnato_a", "assegnato_email"]
        if tipo_fermo in dict(TipoFermo.choices):
            ticket.tipo_fermo = tipo_fermo
            campi.append("tipo_fermo")
        if ore_fermo is not None:
            ticket.ore_fermo_macchina = ore_fermo
            campi.append("ore_fermo_macchina")
        if componente:
            ticket.componente = componente[:200]
            campi.append("componente")
        if causa:
            ticket.causa_radice = causa[:500]
            campi.append("causa_radice")
        if ricorrente:
            ticket.ricorrente = True
            campi.append("ricorrente")
        ticket.save(update_fields=campi)

        # Visibile anche a richiedente e compilatore: vedono solo i commenti non interni.
        TicketCommento.objects.create(
            ticket=ticket,
            autore_nome=nome,
            autore_email=email,
            testo=f"Intervento eseguito: {lavoro}",
            is_interno=False,
        )
        cambia_stato_ticket(ticket, StatoTicket.CHIUSO, utente_nome=nome, utente_email=email, nota=nota)
    return intervento
