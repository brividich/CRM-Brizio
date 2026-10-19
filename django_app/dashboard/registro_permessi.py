"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md: azioni, permessi di pagina collegati e
proprietario dei record per la visibilita' «propri / team / tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='bacheca',
    nome='Home e bacheca',
    descrizione='Login, home, bacheca, profilo, preferenze, rubrica e organigramma: dotazione base di ogni ruolo.',
    area='Piattaforma',
    app='dashboard',
    moduli_acl=('login', 'logout', 'dashboard', 'core', 'preferenze', 'profilo', 'notifiche', 'rubrica', 'organigramma', 'richieste', 'hub_preview', 'cambia_password'),
))
