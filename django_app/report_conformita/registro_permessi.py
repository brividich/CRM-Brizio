"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='report_conformita',
    nome='Report conformità',
    descrizione='Report per audit ISO 9001, EN 9100, ISO 45001, ISO 27001.',
    area='Qualità',
    app='report_conformita',
    moduli_acl=('report_conformita',),
))
