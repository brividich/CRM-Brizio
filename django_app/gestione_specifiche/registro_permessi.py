"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='specifiche',
    nome='Gestione specifiche e OFI',
    descrizione='Flusso specifiche, MOD.133, distribuzione, registro OFI.',
    area='Qualità',
    app='gestione_specifiche',
    moduli_acl=('gestione_specifiche',),
))
