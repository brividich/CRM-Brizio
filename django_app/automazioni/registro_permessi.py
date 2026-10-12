"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='automazioni',
    nome='Automazioni',
    descrizione='Designer visuale, trigger, coda e approvazioni. I link di approvazione via mail restano attivi.',
    area='Piattaforma',
    app='automazioni',
    moduli_acl=('automazioni',),
))
