"""Assets e manutenzione nel sistema dei permessi (core.permessi).

Proprietario di un asset = l'utente a cui e' assegnato (``assigned_legacy_user_id``,
id ``utenti``). Con i ruoli attivi «gestire» su tutti apre l'amministrazione del
modulo (``assets.views._is_assets_admin``). L'elenco non e' ancora filtrato per
propri/team: i preset danno agli asset sempre visibilita' «tutti».
"""
from core.permessi.registro import ModuloPermessi, registra_modulo


def proprietario_asset(asset):
    valore = getattr(asset, "assigned_legacy_user_id", None)
    if valore:
        return int(valore)
    # Macchina di produzione senza persona assegnata: e' del caporeparto.
    from assets.services.responsabile_asset import utente_responsabile

    return utente_responsabile(asset)


registra_modulo(ModuloPermessi(
    chiave="assets",
    nome="Assets e manutenzione",
    descrizione="Inventario, ordini di lavoro, piani di manutenzione, verifiche periodiche.",
    area="Produzione",
    app="assets",
    moduli_acl=("assets",),
    proprietario=proprietario_asset,
    domini_ai=("assets",),
))
