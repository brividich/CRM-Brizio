"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='rentri',
    nome='RENTRI',
    descrizione='Registro rifiuti, scadenzario adempimenti, giacenze per CER.',
    area='Sicurezza',
    app='rentri',
    moduli_acl=('rentri', 'rifiuti'),
))
