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
    # Il permesso della lista copre tutto /diario-preposto (prefisso) e
    # «ereditava» la pagina Impostazioni: sembrava amministrazione e lo accendeva
    # solo «gestire», cosi' il Preposto non apriva il diario ne' lo vedeva nel
    # menu. Impostazioni, modifica, elimina e allegati hanno permessi loro.
    # Le ispezioni sono la stessa consultazione (crearne una e' ispezione_nuova).
    capacita_forzate=(
        ("legacy.diario_preposto.diario_preposto_lista", "lettura"),
        ("legacy.diario_preposto.diario_preposto_ispezioni", "lettura"),
    ),
    domini_ai=("sicurezza",),
))
