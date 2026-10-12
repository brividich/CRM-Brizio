"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='checklist_operativa',
    nome='Checklist operativa',
    descrizione='Checklist di chiusura aziendale con mansioni per reparto.',
    area='Sicurezza',
    app='checklist_operativa',
    moduli_acl=('checklist_operativa',),
))
