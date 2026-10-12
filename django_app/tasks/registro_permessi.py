"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='kickoff',
    nome='KICK-OFF',
    descrizione='Progetti, attività, Gantt, incontri con convocazione e minuta.',
    area='Produzione',
    app='tasks',
    moduli_acl=('tasks',),
    domini_ai=('tasks',),
))
