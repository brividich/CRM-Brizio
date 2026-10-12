"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='glossario',
    nome='Glossario tecnico',
    descrizione='Termini tecnici e sigle SGI con sinonimi e traduzioni.',
    area='Qualità',
    app='glossario_tecnico',
    moduli_acl=('glossario_tecnico',),
))
