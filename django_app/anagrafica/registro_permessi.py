"""Anagrafica nel sistema dei permessi (core.permessi): tre moduli distinti.

Visite mediche e formazione hanno destinatari diversi dall'anagrafica (dato
sanitario, area sicurezza): si assegnano separatamente in matrice.

Proprietario di una scheda = l'account collegato (``anagrafica_dipendenti.utente_id``).
I record dei moduli arrivano come riga dict (con ``utente_id``) o come id
anagrafica intero: entrambi si convertono in ``utenti.id``.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

AZIONE_DATI_RISERVATI = "dati_riservati"
# Il referto clinico (file e testo) e' separato dal giudizio di idoneita':
# capi e preposti vedono idoneita', limitazioni e scadenze, non il referto.
AZIONE_REFERTI = "referti"


def proprietario_scheda(scheda):
    from core.permessi.identita import utente_da_anagrafica

    if isinstance(scheda, dict):
        if scheda.get("utente_id"):
            return int(scheda["utente_id"])
        return utente_da_anagrafica(scheda.get("id") or scheda.get("legacy_anagrafica_id"))
    if isinstance(scheda, int):
        return utente_da_anagrafica(scheda)
    return utente_da_anagrafica(getattr(scheda, "legacy_anagrafica_id", None) or getattr(scheda, "pk", None))


registra_modulo(ModuloPermessi(
    chiave="anagrafica",
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ("legacy.anagrafica.anagrafica_index", "lettura"),
        ("legacy.anagrafica.anagrafica_dipendenti", "lettura"),
        ("legacy.anagrafica.anagrafica_ruoli_operativi", "lettura"),
    ),
    nome="Anagrafica dipendenti",
    descrizione="Schede dipendenti, mansioni, ruoli, organigramma, recruiting, skill matrix.",
    area="Persone",
    app="anagrafica",
    moduli_acl=("anagrafica",),
    azioni_extra=((AZIONE_DATI_RISERVATI, "Dati riservati (IBAN, CF, contratti, documenti riservati)"),),
    proprietario=proprietario_scheda,
    domini_ai=("anagrafica", "skillmatrix"),
))

registra_modulo(ModuloPermessi(
    chiave="visite_mediche",
    nome="Visite mediche e idoneità",
    descrizione="Visite, referti e giudizi di idoneità (dato sanitario).",
    area="Persone",
    app="anagrafica",
    codici_acl=("anagrafica.visite.view", "anagrafica.visite.edit", "anagrafica.visite.delete"),
    azioni_extra=((AZIONE_REFERTI, "Referti clinici (file e contenuto del referto)"),),
    proprietario=proprietario_scheda,
))

registra_modulo(ModuloPermessi(
    chiave="formazione",
    nome="Formazione ed e-learning",
    descrizione="Corsi, attestati, scadenze formative ed e-learning.",
    area="Persone",
    app="anagrafica",
    codici_acl=("anagrafica.formazione.view", "anagrafica.formazione.manage", "anagrafica.formazione.approve"),
    proprietario=proprietario_scheda,
    domini_ai=("rischi_mansione",),
))
