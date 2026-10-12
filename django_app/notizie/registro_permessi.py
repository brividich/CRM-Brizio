"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='notizie',
    nome='Notizie',
    descrizione='Bacheca notizie con pubblico, allegati e letture obbligatorie.',
    area='Persone',
    app='notizie',
    moduli_acl=('notizie',),
    domini_ai=('notizie',),
))
