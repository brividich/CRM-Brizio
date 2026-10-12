"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='dpi',
    nome='DPI',
    descrizione='Richieste, approvazioni, consegne e magazzino dei dispositivi di protezione.',
    area='Sicurezza',
    app='dpi',
    moduli_acl=('dpi',),
    domini_ai=('dpi',),
))
