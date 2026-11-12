"""Dichiarazione del modulo nel sistema dei permessi (core.permessi).

Vedi docs/ai/PERMESSI_RUOLI.md. La lista e l'appello sono di tutti; le uscite non
timbrate di tutta l'azienda e le impostazioni sono di chi gestisce il modulo.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave='presenti',
    capacita_forzate=(
        ('presenti.lista.view', 'lettura'),
        ('presenti.appello.manage', 'lettura'),
        ('presenti.uscite.view', 'lettura'),
    ),
    nome='Presenti in azienda',
    descrizione='Chi è in azienda adesso (timbrature Solari), appello di evacuazione, uscite non timbrate.',
    area='Persone',
    app='presenti',
    moduli_acl=('presenti',),
))
