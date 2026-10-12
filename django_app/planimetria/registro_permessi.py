"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='planimetria',
    nome='Planimetria',
    descrizione='Mappa dello stabilimento e editor delle aree.',
    area='Produzione',
    app='planimetria',
    moduli_acl=('planimetria',),
))
