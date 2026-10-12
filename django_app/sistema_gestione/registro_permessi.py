"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='sistema_gestione',
    nome='Sistema di gestione',
    descrizione='SoA ISO 27001, audit interni EN 9100, rilievi.',
    area='Qualità',
    app='sistema_gestione',
    moduli_acl=('sistema_gestione',),
))
