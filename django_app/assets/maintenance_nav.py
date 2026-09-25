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
            # Registro separato dai piani: revisioni, certificati, garanzie.
            NavItem(
                "amministrative",
                "Scadenze amministrative",
                "asset_administrative_deadline_list",
                sidebar_code="maintenance_amministrative",
                routes=frozenset({"asset_administrative_deadline_create", "asset_administrative_deadline_edit"}),
            ),
            # Verifiche sugli impianti (luci di emergenza, quadri, terra...), non sul
            # singolo asset. Da non confondere con la vecchia "Manutenzioni periodiche".
            NavItem(
                "verifiche",
                "Verifiche periodiche",
                "periodic_check_list",
                sidebar_code="maintenance_verifiche",
                routes=frozenset({
                    "periodic_check_type_detail", "periodic_check_register", "periodic_check_session_detail",
                    "periodic_check_type_create", "periodic_check_type_edit", "periodic_check_systems",
                    "periodic_check_sheet_issue", "periodic_check_sheet_preview", "periodic_check_sheet_pdf",
                }),
            ),
            NavItem(
                "interventi",
                "Interventi",
                "wo_list",
                sidebar_code="maintenance_interventi",
                routes=frozenset({"wo_view", "wo_create", "wo_close", "wo_campaign_create"}),
            ),
            # Dashboard officina: stato macchine e reparti, prima raggiungibile solo dall'elenco asset.
            NavItem("officina", "Officina", "work_machine_dashboard", sidebar_code="maintenance_officina"),
            NavItem("storico", "Storico", "maintenance_history", sidebar_code="maintenance_storico"),
            # KPI sostituisce "Report": i report storici (budget, export, PDF) sono
            # raggiungibili dalla pagina KPI e restano accesi sotto questa voce.
            NavItem(
                "kpi",
                "KPI",
                "maintenance_kpi",
                sidebar_code="report_asset",
                routes=frozenset({"reports", "report_template_admin"}),
            ),
            # Segnalazione rapida di un guasto (ticket MAN): il punto d'ingresso del
            # lavoro correttivo, prima fuori dal menu.
            NavItem("segnala", "Segnala guasto", "asset_quick_report", sidebar_code="maintenance_segnala"),
        ),
    ),
    NavGroup(
        key=GROUP_SETUP,
        label="Configurazione",
        sidebar_code="maintenance_configurazione",
        items=(
            NavItem("imposta", "Imposta", "maintenance_setup", sidebar_code="maintenance_imposta"),
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
                    # Ex "Catalogo attivita'": stesso modello, ora dentro Piani.
                    "maintenance_impostazioni", "maintenance_template_list",
                    "maintenance_template_create", "maintenance_template_edit",
                }),
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

# Testi di "Cosa posso fare qui" per voce: stanno qui accanto al menu, cosi' una
# pagina nuova non puo' nascere senza la sua spiegazione (lo verifica un test).
HELP_TEXTS: dict[str, tuple[str, ...]] = {
    'panoramica': (
        "Vedi in un colpo d'occhio scadute, prossime 30 giorni e prossima scadenza per ordinarie, amministrative, licenze e contratti.",
        'Filtra per famiglia e reparto: i link a Calendario e Scadenzario si portano dietro i filtri.',
        'Sotto trovi il lavoro: manutenzioni dovute ma senza ordine di lavoro, OdL aperti, rapporti mancanti, carico dei manutentori.',
    ),
    'da_fare': (
        "«Il mio lavoro» mostra le tue manutenzioni e quelle di nessuno; «Tutto» l'intera officina.",
        'Premi «Registra» su una riga per chiudere la manutenzione con esito e documento.',
        "Chi pianifica seleziona piu' righe e le raccoglie in un solo ordine di lavoro.",
    ),
    'calendario': (
        'Clicca una scadenza per il dettaglio e le azioni; clicca un giorno per vedere cosa scade.',
        'Trascina una manutenzione su un altro giorno per spostarne la data (chi pianifica).',
        "«Crea OdL» o «Aggiungi alla selezione» raccolgono una o piu' scadenze in un ordine di lavoro.",
        'Viste Mese, Settimana, Elenco e Per asset; le tipologie si accendono e spengono in alto.',
    ),
    'scadenzario': (
        'Scegli il periodo (scadute, 7/30/90 giorni) e la tipologia con le schede in alto.',
        'Seleziona le manutenzioni e crea un ordine di lavoro unico dalla barra in fondo.',
        "Scarica l'elenco in Excel o PDF con gli stessi filtri.",
    ),
    'amministrative': (
        "Revisioni, certificati, garanzie e altri adempimenti dell'asset: un registro a parte, non un piano di manutenzione.",
        "«+ Nuova scadenza» per aggiungerne una; apri una riga per registrare l'adempimento e fissare la scadenza successiva.",
        'Le scadenze amministrative compaiono anche in Calendario, Scadenzario e promemoria.',
    ),
    'verifiche': (
        "Verifiche periodiche sugli impianti (illuminazione di emergenza, quadri, cabine, terra, antincendio...): una riga per tipo di verifica, raggruppate per impianto.",
        "«Registra» su una riga per inserire l'esito con il rapportino: la prossima scadenza si ricalcola da sola.",
        "Una voce o un rilievo non conforme diventa un ordine di lavoro dalla pagina della verifica.",
    ),
    'officina': (
        'Stato delle macchine per reparto: in uso, ferme, in manutenzione.',
        'Da qui scarichi il PDF delle manutenzioni del mese, calcolato dalle scadenze pianificate.',
    ),
    'segnala': (
        'Segnala un guasto su un asset: nasce un ticket di manutenzione con asset, descrizione e priorita.',
        "Dal QR della macchina l'asset e' gia' scelto.",
    ),
    'interventi': (
        'Tutti gli ordini di lavoro aperti: chi li prende, a che punto sono, cosa li blocca.',
        "«+ Nuovo intervento» apre un guasto o un lavoro su un asset; «+ Campagna» su piu' asset.",
        'Apri un intervento per avviarlo, sospenderlo o chiuderlo con esito e costi.',
    ),
    'storico': (
        "Ordini di lavoro conclusi e ticket di manutenzione, in un'unica cronologia.",
        'Filtra per asset, periodo o testo per ritrovare un intervento passato.',
    ),
    'kpi': (
        "Puntualita', arretrato, copertura dei piani, adempimenti in regola, rinnovi in arrivo.",
        'Gli indicatori compaiono solo se i dati che li reggono sono compilati: altrimenti la pagina lo dice.',
        '«Report e budget» apre i report storici, i costi e il piano del mese.',
    ),
    'imposta': (
        "Segui i passi dall'alto: ognuno dice cosa manca e porta alla pagina dove si sistema.",
        'Quando tutti i passi obbligatori sono verdi, le scadenze nascono da sole e sono complete.',
    ),
    'piani': (
        'Un piano dice cosa fare; le sue applicazioni dicono su quali asset e ogni quanto.',
        'Apri un piano per applicarlo a un asset, un gruppo o una categoria e per modificarne checklist e istruzioni.',
        "«+ Nuovo piano» per un'attivita' nuova; «Importa storico» per partire dall'ultima esecuzione nota.",
    ),
    'gruppi': (
        'Un gruppo raccoglie asset di famiglie diverse (una linea, un reparto) per applicarci un piano.',
        'Se il piano vale per tutta una famiglia non serve un gruppo: applicalo alla categoria.',
    ),
    'copertura': (
        "Ogni riga e' un asset, ogni colonna un piano: vedi i buchi e i conflitti di periodicita'.",
        "Un conflitto blocca le scadenze di quel piano su quell'asset finche' non lo risolvi.",
    ),
    'fornitori': (
        'Le ditte che eseguono manutenzioni esterne, con piani e interventi collegati.',
        "L'anagrafica completa del fornitore si gestisce nel modulo Fornitori.",
    ),
    'contratti': (
        'Contratti di assistenza per asset, categoria o generali, con scadenza e costo.',
        'Le scadenze dei contratti compaiono anche in Calendario, Scadenzario e promemoria.',
    ),
    'licenze': (
        'Licenze software assegnate a un asset, a una persona o a un reparto.',
        'Le scadenze delle licenze compaiono anche in Calendario, Scadenzario e promemoria.',
    ),
}


def help_for(item_key: str) -> tuple[str, ...]:
    return HELP_TEXTS.get(item_key, ())
