"""Anagrafica nel sistema dei permessi (core.permessi): tre moduli distinti.

Visite mediche e formazione hanno destinatari diversi dall'anagrafica (dato
sanitario, area sicurezza): si assegnano separatamente in matrice.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave="anagrafica",
    nome="Anagrafica dipendenti",
    descrizione="Schede dipendenti, dati HR, mansioni, ruoli, organigramma, recruiting, skill matrix.",
    area="Persone",
    app="anagrafica",
    moduli_acl=("anagrafica",),
    domini_ai=("anagrafica", "skillmatrix"),
))

registra_modulo(ModuloPermessi(
    chiave="visite_mediche",
    nome="Visite mediche e idoneità",
    descrizione="Visite, referti e giudizi di idoneità (dato sanitario).",
    area="Persone",
    app="anagrafica",
    codici_acl=("anagrafica.visite.view", "anagrafica.visite.edit", "anagrafica.visite.delete"),
))

registra_modulo(ModuloPermessi(
    chiave="formazione",
    nome="Formazione ed e-learning",
    descrizione="Corsi, attestati, scadenze formative ed e-learning.",
    area="Persone",
    app="anagrafica",
    codici_acl=("anagrafica.formazione.view", "anagrafica.formazione.manage", "anagrafica.formazione.approve"),
    domini_ai=("rischi_mansione",),
))
