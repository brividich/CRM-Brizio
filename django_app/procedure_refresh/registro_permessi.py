"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='procedure',
    nome='Procedure (presa visione)',
    descrizione='Campagne di presa visione delle procedure, scadenze e solleciti.',
    area='Sicurezza',
    app='procedure_refresh',
    moduli_acl=('procedure_refresh',),
    domini_ai=('procedure',),
))
