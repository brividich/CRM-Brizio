"""Assenze nel sistema dei permessi (core.permessi).

Proprietario di una richiesta = la persona assente (``assenze.utente_id``).
Le righe del modulo sono dict da SQL: il campo si chiama ``utente_id`` o, nei
caricatori della coda del capo, ``legacy_user_id``.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

# Impostazioni del modulo e amministrazione HR (/assenze/impostazioni/, area HR,
# gestione admin, certificazione presenze): azione a se', non la apre «gestire».
AZIONE_IMPOSTAZIONI = "impostazioni"
PAGINE_IMPOSTAZIONI = ("assenze.assenze.manage", "legacy.assenze.admin_assenze")


def proprietario_assenza(riga):
    if isinstance(riga, dict):
        valore = riga.get("utente_id") or riga.get("legacy_user_id")
    else:
        valore = getattr(riga, "utente_id", None)
    try:
        return int(valore) if valore else None
    except (TypeError, ValueError):
        return None


registra_modulo(ModuloPermessi(
    chiave="assenze",
    nome="Assenze",
    descrizione="Richieste di assenza, approvazioni, calendario, export.",
    area="Persone",
    app="assenze",
    moduli_acl=("assenze",),
    codici_acl=PAGINE_IMPOSTAZIONI,
    azioni_extra=((AZIONE_IMPOSTAZIONI, "Impostazioni e area HR (impostazioni, saldi, certificazioni)"),),
    pagine_azioni=((AZIONE_IMPOSTAZIONI, PAGINE_IMPOSTAZIONI),),
    # Pagine personali: «Le mie assenze» ha un permesso suo (core 0094), il modulo di
    # richiesta è un'azione di chi crea, il controllo corsi lo usa il modulo di richiesta.
    capacita_forzate=(
        ("assenze.mie_richieste.view", "lettura"),
        ("assenze.assenze_richiesta.view", "modifica"),
        ("assenze.assenze_check.manage", "lettura"),
    ),
    proprietario=proprietario_assenza,
    domini_ai=("absence",),
))
