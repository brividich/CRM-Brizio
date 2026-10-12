"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='suggestion_corner',
    nome='Suggestion Corner',
    descrizione='Segnalazioni e miglioramenti con ciclo PDCA. Il form anonimo pubblico resta aperto.',
    area='Qualità',
    app='suggestion_corner',
    moduli_acl=('suggestion_corner',),
    domini_ai=('suggestioni',),
))
