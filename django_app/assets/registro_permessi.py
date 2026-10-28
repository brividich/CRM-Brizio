"""Assets e manutenzione nel sistema dei permessi (core.permessi): quattro moduli distinti.

Inventario, Manutenzione, Ordini di lavoro e Verifiche e scadenze si assegnano
separatamente in matrice: un caporeparto può vedere l'inventario del suo reparto
e i piani di manutenzione solo delle sue macchine, l'ufficio manutenzione tutto.

Proprietario di un record = il proprietario del suo asset: l'utente a cui è
assegnato (``assigned_legacy_user_id``, id ``utenti``) o, per un asset non IT senza
persona, il caporeparto del reparto di installazione. L'ambito di ogni modulo si
applica in ``assets.services.visibilita``. Le pagine non elencate qui sotto restano
all'Inventario (``moduli_acl``), comprese le Impostazioni del modulo.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

MODULO_INVENTARIO = "assets"
MODULO_MANUTENZIONE = "assets_manutenzione"
MODULO_ODL = "assets_odl"
MODULO_VERIFICHE = "assets_verifiche"
SOTTOMODULI = (MODULO_MANUTENZIONE, MODULO_ODL, MODULO_VERIFICHE)


def _legacy(*codici: str) -> tuple[str, ...]:
    return tuple(f"legacy.assets.{codice}" for codice in codici)


CODICI_MANUTENZIONE = _legacy(
    "assets_maintenance_da_fare", "assets_maintenance_scadenze", "assets_maintenance_schedule",
    "assets_maintenance_quadro", "assets_maintenance_plans", "assets_maintenance_groups",
    "assets_maintenance_coverage", "assets_maintenance_asset_plans", "assets_maintenance_preview_api",
    "assets_maintenance_history_import", "assets_maintenance_month_pdf", "assets_maintenance_worksheet",
    "assets_maintenance_templates", "assets_maintenance_templates_new", "assets_maintenance_templates_edit",
    "assets_maintenance_rules", "assets_maintenance_rules_new", "assets_maintenance_rules_edit",
    "assets_asset_maintenance_rules", "assets_asset_maintenance_overrides_new",
    "assets_asset_maintenance_overrides_edit", "assets_asset_maintenance_overrides_reset",
    "assets_maintenance_suppliers", "assets_assistance_contracts", "assets_spare_parts",
    "maintenance_planning", "maintenance_execute",
)
CODICI_ODL = _legacy("assets_workorders", "assets_wo_new", "assets_wo_view", "assets_wo_close")
CODICI_VERIFICHE = _legacy(
    "assets_periodic_checks", "assets_periodic_check_categories", "assets_verifiche",
    "assets_deadlines", "assets_deadlines_new", "assets_deadlines_edit",
)


def proprietario_asset(asset):
    # Un record di manutenzione, un OdL o una verifica arrivano col loro asset.
    if not hasattr(asset, "assigned_legacy_user_id"):
        asset = getattr(asset, "asset", None)
    if asset is None:
        return None
    valore = getattr(asset, "assigned_legacy_user_id", None)
    if valore:
        return int(valore)
    # Asset non IT senza persona assegnata: è del caporeparto del reparto di installazione.
    from assets.services.responsabile_asset import utente_responsabile

    return utente_responsabile(asset)


registra_modulo(ModuloPermessi(
    chiave=MODULO_INVENTARIO,
    nome="Assets · Inventario",
    descrizione="Elenco e scheda asset, dispositivi IT, macchine, componenti, software, rete, mappa officina.",
    area="Produzione",
    app="assets",
    moduli_acl=("assets",),
    proprietario=proprietario_asset,
    domini_ai=("assets",),
))

registra_modulo(ModuloPermessi(
    chiave=MODULO_MANUTENZIONE,
    nome="Assets · Manutenzione",
    descrizione="Piani e regole, manutenzioni da fare, scadenze, quadro, copertura, fornitori, contratti, ricambi.",
    area="Produzione",
    app="assets",
    codici_acl=CODICI_MANUTENZIONE,
    proprietario=proprietario_asset,
))

registra_modulo(ModuloPermessi(
    chiave=MODULO_ODL,
    nome="Assets · Ordini di lavoro",
    descrizione="Ordini di lavoro: aprire, seguire, chiudere. Chi è assegnato a un ordine lo vede sempre.",
    area="Produzione",
    app="assets",
    codici_acl=CODICI_ODL,
    proprietario=proprietario_asset,
))

registra_modulo(ModuloPermessi(
    chiave=MODULO_VERIFICHE,
    nome="Assets · Verifiche e scadenze",
    descrizione="Verifiche periodiche degli impianti, manutenzione periodica e scadenze amministrative degli asset.",
    area="Produzione",
    app="assets",
    codici_acl=CODICI_VERIFICHE,
    proprietario=proprietario_asset,
))
