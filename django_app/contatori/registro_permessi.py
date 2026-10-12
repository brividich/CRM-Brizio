"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='contatori',
    nome='Contatori MFC e SNMP',
    descrizione='Letture e consumabili delle stampanti, fatture, monitor SNMP.',
    area='IT',
    app='contatori',
    moduli_acl=('contatori',),
    domini_ai=('contatori',),
))
