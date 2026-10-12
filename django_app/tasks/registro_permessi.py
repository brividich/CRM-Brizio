"""KICK-OFF nel sistema dei permessi (core.permessi).

La partecipazione ai progetti (team PM/CC/PRG/CR, assegnatario, creatore,
iscritti) resta la regola di base del modulo (``tasks/access.py``). La matrice
decide l'ambito: «propri» = solo cio' a cui si partecipa, «team» = anche
attivita' e progetti delle persone del team d'organigramma, «tutti» = tutto.

Proprietari di un'attivita': assegnatario e creatore. Di un progetto: il creatore.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietari_kickoff(oggetto):
    from core.permessi import legacy_id_da_user_id

    ids = {
        legacy_id_da_user_id(getattr(oggetto, campo, None))
        for campo in ("assigned_to_id", "created_by_id")
    }
    return {i for i in ids if i}


registra_modulo(ModuloPermessi(
    chiave="kickoff",
    nome="KICK-OFF",
    descrizione="Progetti, attività, Gantt, incontri con convocazione e minuta.",
    area="Produzione",
    app="tasks",
    moduli_acl=("tasks",),
    proprietario=proprietari_kickoff,
    domini_ai=("tasks",),
))
