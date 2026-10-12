"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='timbri',
    nome='Registro timbri MOD.130',
    descrizione='Timbri, firme e sigle del personale.',
    area='Qualità',
    app='timbri',
    moduli_acl=('timbri',),
))
