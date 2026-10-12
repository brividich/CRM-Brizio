"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='assets',
    nome='Assets e manutenzione',
    descrizione='Inventario, ordini di lavoro, piani di manutenzione, verifiche periodiche.',
    area='Produzione',
    app='assets',
    moduli_acl=('assets',),
    domini_ai=('assets',),
))
