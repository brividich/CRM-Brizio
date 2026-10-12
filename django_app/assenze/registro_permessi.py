"""Assenze nel sistema dei permessi (core.permessi).

Proprietario di una richiesta = la persona assente (``assenze.utente_id``).
Le righe del modulo sono dict da SQL: il campo si chiama ``utente_id`` o, nei
caricatori della coda del capo, ``legacy_user_id``.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


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
    proprietario=proprietario_assenza,
    domini_ai=("absence",),
))
