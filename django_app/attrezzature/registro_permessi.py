"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='attrezzature',
    nome='Attrezzature',
    descrizione='Workflow attrezzi e P/N, import Excel, collegamento KICK-OFF.',
    area='Produzione',
    app='attrezzature',
    moduli_acl=('attrezzature',),
))
