"""Segnalazione incidenti nel sistema dei permessi (core.permessi).

Proprietario di una rilevazione = chi l'ha inserita (``segnalato_da_legacy_id``).
Le rilevazioni storiche, e quelle lette da SharePoint, non hanno un autore
affidabile (solo un nominativo in chiaro): le vede soltanto chi ha «tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_rilevazione(rilevazione):
    if isinstance(rilevazione, dict):
        valore = rilevazione.get("SegnalatoDaLegacyId")
    else:
        valore = getattr(rilevazione, "segnalato_da_legacy_id", None)
    try:
        return int(valore) if valore else None
    except (TypeError, ValueError):
        return None


registra_modulo(ModuloPermessi(
    chiave="rilevazione_incidenti",
    nome="Segnalazione incidenti",
    descrizione="Unsafe condition, near miss, incidenti, KPI e heatmap.",
    area="Sicurezza",
    app="rilevazione_incidenti",
    moduli_acl=("rilevazione_incidenti", "sicurezza"),
    proprietario=proprietario_rilevazione,
    domini_ai=("sicurezza",),
))
