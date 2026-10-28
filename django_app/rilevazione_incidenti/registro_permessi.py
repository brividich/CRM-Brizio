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
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ("legacy.rilevazione_incidenti.rilev_inc_lista", "lettura"),
    ),
    nome="Segnalazione incidenti",
    descrizione="Unsafe condition, near miss, incidenti, KPI e heatmap.",
    area="Sicurezza",
    app="rilevazione_incidenti",
    moduli_acl=("rilevazione_incidenti", "sicurezza"),
    proprietario=proprietario_rilevazione,
    domini_ai=("sicurezza",),
))
