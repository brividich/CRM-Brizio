"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='planimetria',
    nome='Planimetria',
    descrizione='Solo collegamenti alla mappa officina di Asset: i permessi veri di mappa ed editor sono quelli del modulo Asset.',
    area='Produzione',
    app='planimetria',
    moduli_acl=('planimetria',),
))
