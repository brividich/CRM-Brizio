"""Reception nel sistema dei permessi (core.permessi).

Il pannello della reception usa il permesso di «Accessi esterni» (modulo Fornitori). Qui c'è solo
la pagina personale «Annuncia una visita», nella dotazione base di ogni ruolo (core/permessi/preset.py):
ognuno vede e annuncia i propri ospiti e decide le richieste rivolte a lui (controllo nella view).
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave="visite_ospiti",
    nome="Visite degli ospiti",
    descrizione="Annunciare i propri ospiti alla reception e rispondere alle loro richieste di appuntamento.",
    area="Persone",
    app="reception",
    moduli_acl=("reception",),
    capacita_forzate=(("reception.annuncia.view", "lettura"),),
))
