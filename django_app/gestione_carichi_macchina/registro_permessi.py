"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='carichi_macchina',
    nome='Carichi macchina',
    descrizione='Pianificazione dei carichi macchine x giorni e Gantt.',
    area='Produzione',
    app='gestione_carichi_macchina',
    moduli_acl=('gestione_carichi_macchina',),
    domini_ai=('carichi',),
))
