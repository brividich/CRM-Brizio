"""Definizione unica della navigazione Manutenzione.

Prima esistevano due navigazioni della stessa sezione: la barra di sezione
(scritta nel codice) e il ramo della sidebar (a database, ``AssetSidebarButton``).
Avevano voci, ordine ed etichette diverse — la stessa pagina si chiamava
"Attivita'" in una e "Impostazioni" nell'altra.

Da qui leggono entrambe:

- la barra di sezione (``views._assets_section_nav``) la costruisce a runtime;
- la sidebar e' allineata dalla migration ``0106_sidebar_manutenzione_menu_unico``,
  che ne porta una copia congelata (le migration non importano codice
  applicativo); un test verifica che le due restino identiche.

Due rami: *Manutenzione* e' cio' che si apre ogni giorno, *Configurazione* cio'
che si tocca quando si imposta il lavoro. Nessun URL cambia.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    route: str
    # Rotte che accendono la voce: la pagina stessa piu' le sue sottopagine e i
    # vecchi indirizzi che rimandano qui.
    routes: frozenset[str] = field(default_factory=frozenset)
    query: str = ""
    # Codice del pulsante ``AssetSidebarButton`` che rappresenta la voce.
    sidebar_code: str = ""

    @property
    def all_routes(self) -> frozenset[str]:
        return self.routes | {self.route}


@dataclass(frozen=True)
class NavGroup:
    key: str
    label: str
    items: tuple[NavItem, ...]
    sidebar_code: str = ""


GROUP_OPERATIVO = "manutenzione"
GROUP_SETUP = "configurazione"

MAINTENANCE_NAV: tuple[NavGroup, ...] = (
    NavGroup(
        key=GROUP_OPERATIVO,
        label="Manutenzione",
        sidebar_code="maintenance_hub",
        items=(
            NavItem("panoramica", "Panoramica", "maintenance_responsabile", sidebar_code="maintenance_quadro"),
            NavItem(
                "da_fare",
                "Da fare",
                "maintenance_da_fare",
                sidebar_code="maintenance_da_fare",
                # ``maintenance_hub`` e' il vecchio centro operativo: finche' risponde
                # resta sotto "Da fare", che ne ha preso il posto.
                routes=frozenset({
                    "maintenance_hub", "maintenance_todo", "il_mio_turno",
                    "occurrence_complete", "occurrence_followup_create",
                }),
            ),
            NavItem("calendario", "Calendario", "calendario_asset", sidebar_code="calendario_main"),
            NavItem(
                "scadenzario",
                "Scadenzario",
                "maintenance_scadenze",
                sidebar_code="maintenance_scadenzario",
                routes=frozenset({"maintenance_schedule", "maintenance_scadenzario"}),
            ),
            NavItem(
                "interventi",
                "Interventi",
                "wo_list",
                sidebar_code="maintenance_interventi",
                routes=frozenset({"wo_view", "wo_create", "wo_close", "wo_campaign_create"}),
            ),
            NavItem("storico", "Storico", "maintenance_history", sidebar_code="maintenance_storico"),
            NavItem(
                "report",
                "Report",
                "reports",
                sidebar_code="report_asset",
                routes=frozenset({"report_template_admin"}),
                query="scope=production",
            ),
        ),
    ),
    NavGroup(
        key=GROUP_SETUP,
        label="Configurazione",
        sidebar_code="maintenance_configurazione",
        items=(
            NavItem(
                "piani",
                "Piani",
                "maintenance_plan_list",
                sidebar_code="maintenance_piani",
                routes=frozenset({
                    "maintenance_plan_detail", "maintenance_plan_create", "maintenance_plan_edit",
                    "maintenance_assignment_create", "maintenance_assignment_edit",
                    "asset_maintenance_plans", "asset_plan_customize", "maintenance_history_import",
                    "maintenance_rule_list", "maintenance_rule_create", "maintenance_rule_edit",
                    "asset_maintenance_rule_list", "asset_maintenance_rule_override_create",
                    "asset_maintenance_rule_override_edit", "asset_maintenance_rule_override_reset",
                    "periodic_verifications",
                }),
            ),
            NavItem(
                "catalogo",
                "Catalogo attività",
                "maintenance_impostazioni",
                sidebar_code="maintenance_impostazioni",
                routes=frozenset({"maintenance_template_list", "maintenance_template_create", "maintenance_template_edit"}),
            ),
            NavItem(
                "gruppi",
                "Gruppi asset",
                "asset_group_list",
                sidebar_code="maintenance_asset_groups",
                routes=frozenset({"asset_group_create", "asset_group_edit"}),
            ),
            NavItem(
                "copertura",
                "Copertura",
                "maintenance_coverage",
                sidebar_code="maintenance_copertura",
                routes=frozenset({"maintenance_coverage_matrix"}),
            ),
            NavItem(
                "fornitori",
                "Fornitori",
                "maintenance_suppliers",
                sidebar_code="maintenance_fornitori",
                routes=frozenset({"maintenance_supplier_detail"}),
            ),
            NavItem("contratti", "Contratti assistenza", "assistance_contract_list", sidebar_code="maintenance_contratti"),
            NavItem("licenze", "Licenze software", "software_license_list", sidebar_code="licenze"),
        ),
    ),
)


def find_active(route_name: str) -> tuple[NavGroup, NavItem] | None:
    """Gruppo e voce accesi dalla rotta corrente, oppure ``None`` se la pagina
    non appartiene alla sezione Manutenzione."""
    if not route_name:
        return None
    for group in MAINTENANCE_NAV:
        for item in group.items:
            if route_name in item.all_routes:
                return group, item
    return None


def sidebar_code_routes() -> dict[str, frozenset[str]]:
    """Codice pulsante sidebar -> rotte che lo accendono.

    Il genitore di ramo si accende con qualsiasi voce del suo ramo."""
    mapping: dict[str, frozenset[str]] = {}
    for group in MAINTENANCE_NAV:
        group_routes: set[str] = set()
        for item in group.items:
            group_routes |= item.all_routes
            if item.sidebar_code:
                mapping[item.sidebar_code] = item.all_routes
        if group.sidebar_code:
            mapping[group.sidebar_code] = frozenset(group_routes)
    return mapping