"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='soc',
    nome='Security Center (SOC)',
    descrizione='Alert, casi, incidenti NIS2/GDPR, backup, report periodico.',
    area='IT',
    app='security',
    moduli_acl=('security',),
    domini_ai=('soc',),
))
