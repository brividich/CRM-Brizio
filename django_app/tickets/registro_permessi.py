"""Ticket IT e Ticket Manutenzione nel sistema dei permessi (core.permessi).

Stessa app e stesse pagine, due moduli in matrice: chi gestisce i ticket IT
non gestisce per questo quelli di manutenzione. Il proprietario di un ticket e'
il richiedente (account o id utente legacy; mai il solo nome, ambiguo fra
omonimi).
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_ticket(ticket):
    from core.permessi import legacy_id_da_user_id

    if getattr(ticket, "richiedente_legacy_user_id", None):
        return int(ticket.richiedente_legacy_user_id)
    return legacy_id_da_user_id(getattr(ticket, "richiedente_user_id", None))


MODULO_PER_TIPO = {"IT": "ticket_it", "MAN": "ticket_manutenzione"}

registra_modulo(ModuloPermessi(
    chiave="ticket_it",
    nome="Ticket IT",
    descrizione="Richieste al reparto IT: apertura, assegnazione, chiusura.",
    area="IT",
    app="tickets",
    moduli_acl=("tickets",),
    proprietario=proprietario_ticket,
    domini_ai=("tickets",),
))

registra_modulo(ModuloPermessi(
    chiave="ticket_manutenzione",
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ("legacy.tickets.tickets_dashboard", "lettura"),
    ),
    nome="Ticket manutenzione",
    descrizione="Richieste di manutenzione e fermi macchina: apertura, assegnazione, chiusura.",
    area="Produzione",
    app="tickets",
    moduli_acl=("tickets",),
    proprietario=proprietario_ticket,
    domini_ai=("tickets",),
))
