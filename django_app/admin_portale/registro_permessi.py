"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='gestione_utenti',
    nome='Gestione utenti e ruoli',
    descrizione='Utenti, ruoli, matrice dei permessi, impersonazione.',
    area='Piattaforma',
    app='admin_portale',
    moduli_acl=('admin', 'admin_portale', 'gestione_utenti', 'impersonation'),
    solo_amministratore=True,
))
