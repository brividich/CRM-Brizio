"""Diario preposto nel sistema dei permessi (core.permessi).

Proprietario di una segnalazione = chi l'ha creata (``creato_da``). Le
segnalazioni storiche senza autore sono visibili solo a chi ha ambito «tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_segnalazione(segnalazione):
    from core.permessi import legacy_id_da_user_id

    return legacy_id_da_user_id(getattr(segnalazione, "creato_da_id", None))


registra_modulo(ModuloPermessi(
    chiave="diario_preposto",
    nome="Diario preposto",
    descrizione="Segnalazioni e ispezioni periodiche del preposto.",
    area="Sicurezza",
    app="diario_preposto",
    moduli_acl=("diario_preposto",),
    proprietario=proprietario_segnalazione,
    domini_ai=("sicurezza",),
))
