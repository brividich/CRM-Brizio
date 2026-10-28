"""DPI nel sistema dei permessi (core.permessi).

Proprietario di una richiesta = il dipendente per cui e' fatta.
``RichiestaDPI.richiedente_legacy_id`` e' l'id **anagrafica**: si converte in
``utenti.id`` con ``core.permessi.identita``. Senza scheda collegata vale chi
l'ha inserita (``created_by``).
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_richiesta(richiesta):
    from core.permessi import legacy_id_da_user_id
    from core.permessi.identita import utente_da_anagrafica

    return utente_da_anagrafica(getattr(richiesta, "richiedente_legacy_id", None)) or legacy_id_da_user_id(
        getattr(richiesta, "created_by_id", None)
    )


registra_modulo(ModuloPermessi(
    chiave="dpi",
    # Permesso della pagina principale legato a un prefisso: «ereditava» le rotte di
    # scrittura/gestione sotto e la matrice lo dava solo a «modificare»/«gestire», cosi'
    # chi ha «vedere» non apriva il modulo ne' lo trovava nel menu. Le scritture hanno
    # controlli propri nelle view (verificati il 28/10/2026).
    capacita_forzate=(
        ("legacy.dpi.dpi_view", "lettura"),
    ),
    nome="DPI",
    descrizione="Richieste, approvazioni, consegne e magazzino dei dispositivi di protezione.",
    area="Sicurezza",
    app="dpi",
    moduli_acl=("dpi",),
    proprietario=proprietario_richiesta,
    domini_ai=("dpi",),
))
