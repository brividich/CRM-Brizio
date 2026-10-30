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

Tre rami: *Manutenzione* e' cio' che si apre ogni giorno, *Configurazione* cio'
che si tocca quando si imposta il lavoro, *IT e rete* licenze, software, indirizzi
e rack (fino alla 0156 stavano dentro Configurazione). Nessun URL cambia.
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
GROUP_IT = "it_rete"

MAINTENANCE_NAV: tuple[NavGroup, ...] = (
    NavGroup(
        key=GROUP_OPERATIVO,
        label="Manutenzione",
        sidebar_code="maintenance_hub",
        items=(
            # La pagina KPI e' confluita nella Panoramica («Dettaglio indicatori»): il suo
            # URL e i report storici (raggiungibili da «Report e budget») restano qui sotto.
            NavItem(
                "panoramica",
                "Panoramica",
                "maintenance_responsabile",
                sidebar_code="maintenance_quadro",
                routes=frozenset({"maintenance_kpi", "reports", "report_template_admin"}),
            ),
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
                    "periodic_check_categories",
                    "periodic_check_sheet_issue", "periodic_check_sheet_preview", "periodic_check_sheet_pdf",
                    "periodic_check_layout_image", "periodic_check_intake", "periodic_check_intake_scan",
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
            # Segnalazione rapida di un guasto (ticket MAN): il punto d'ingresso del
            # lavoro correttivo, prima fuori dal menu.
            NavItem("segnala", "Segnala guasto", "asset_quick_report", sidebar_code="maintenance_segnala"),
            # Ricambi minimi: anagrafica, giacenza, sotto scorta, scarico sugli interventi.
            NavItem(
                "ricambi",
                "Ricambi",
                "spare_part_list",
                sidebar_code="maintenance_ricambi",
                routes=frozenset({"spare_part_create", "spare_part_detail", "spare_part_edit", "workorder_spare_parts"}),
            ),
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
            NavItem("mtconnect", "Macchine collegate", "mtconnect_collegamenti", sidebar_code="mtconnect_collegamenti"),
        ),
    ),
    # Nella sidebar e' una sezione a se' («IT e rete») con le voci al primo livello:
    # nessun pulsante genitore, quindi ``sidebar_code`` vuoto.
    NavGroup(
        key=GROUP_IT,
        label="IT e rete",
        items=(
            NavItem("licenze", "Licenze software", "software_license_list", sidebar_code="licenze"),
            NavItem(
                "catalogo_software",
                "Catalogo software",
                "software_catalog",
                sidebar_code="catalogo_software",
                routes=frozenset({"software_catalog_detail"}),
            ),
            NavItem("rete_indirizzi", "Indirizzi IP", "rete_indirizzi", sidebar_code="rete_indirizzi"),
            NavItem("rete_rack", "Rack e switch", "rete_rack", sidebar_code="rete_rack",
                    routes=frozenset({"rete_rack_detail"})),
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
        "«Dettaglio indicatori» raccoglie puntualita', arretrato, copertura dei piani, adempimenti e rinnovi; «Report e budget» apre i report storici.",
    ),
    'da_fare': (
        "«Il mio lavoro» mostra le tue manutenzioni e quelle di nessuno; «Tutto» l'intera officina.",
        'Premi «Registra» su una riga per chiudere la manutenzione con esito e documento.',
        "Non si riesce a farla in tempo? Dalla pagina di registrazione premi «Rinvia»: nuova data e motivo, lo storico dei rinvii resta.",
        "Chi pianifica seleziona piu' righe e le raccoglie in un solo ordine di lavoro.",
    ),
    'calendario': (
        'Clicca una scadenza per il dettaglio e le azioni; clicca un giorno per vedere cosa scade.',
        "Trascina una manutenzione su un altro giorno per rinviarla (chi pianifica): la scadenza originale resta registrata e alla chiusura il conteggio riparte dalla data di esecuzione.",
        "«Crea OdL» o «Aggiungi alla selezione» raccolgono una o piu' scadenze in un ordine di lavoro.",
        'Viste Mese, Settimana, Elenco e Per asset; le tipologie si accendono e spengono in alto.',
    ),
    'scadenzario': (
        "Scegli il periodo (scadute, 7/30/90 giorni) e la tipologia con le schede in alto; «Svolte →» apre lo Storico con il lavoro gia' fatto.",
        'Seleziona le manutenzioni e crea un ordine di lavoro unico dalla barra in fondo.',
        "Scarica l'elenco in Excel o PDF con gli stessi filtri.",
    ),
    'amministrative': (
        "Revisioni, certificati, garanzie e altri adempimenti dell'asset: un registro a parte, non un piano di manutenzione.",
        "«+ Nuova scadenza» per aggiungerne una; apri una riga per registrare l'adempimento e fissare la scadenza successiva.",
        'Le scadenze amministrative compaiono anche in Calendario, Scadenzario e promemoria.',
        "Registrata, una scadenza si rinnova o passa in «Chiuse»: ogni esecuzione resta nello Storico («Svolte →»).",
    ),
    'verifiche': (
        "Verifiche periodiche sugli impianti (illuminazione di emergenza, quadri, cabine, terra, antincendio...): una riga per tipo di verifica, raggruppate per impianto.",
        "«Apri scheda» porta alla pagina della verifica: in cima «Come funziona questa verifica» dice i passi, cosa manca e il pulsante per farlo.",
        "Verifiche a planimetria: «Stampa foglio» crea il foglio con il QR per il tecnico, poi si carica la scansione. Le altre: «Registra» con il rapportino.",
        "Nella scheda: stato attuale, statistiche, storico con i rilievi segnalati, documenti. I rilievi non aprono ordini di lavoro.",
        "«Cartella scansioni»: i fogli scansionati nella cartella dello scanner tornano da soli alla loro verifica; quelli senza QR si smistano a mano.",
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
        "Tutto il lavoro svolto in un'unica cronologia: ordini di lavoro conclusi, manutenzioni registrate senza OdL, scadenze amministrative svolte e ticket di manutenzione.",
        "Filtra per asset, periodo o testo; «Origine» mostra un solo tipo (es. «Scadenze amministrative svolte»).",
        "Ci arrivi anche da «Svolte →» nelle pagine Scadenze manutenzione e Scadenze amministrative.",
    ),
    'ricambi': (
        "Cosa c'e' a magazzino: giacenza, scorta minima, scaffale. «Sotto scorta» mostra cosa sta finendo.",
        "Gli scarichi si fanno dall'intervento («Ricambi usati»): il costo materiali si calcola da solo.",
        'Carichi e rettifiche di inventario si registrano dalla scheda del ricambio (amministratori).',
    ),
    'imposta': (
        "Segui i passi dall'alto: ognuno dice cosa manca e porta alla pagina dove si sistema.",
        'Quando tutti i passi obbligatori sono verdi, le scadenze nascono da sole e sono complete.',
    ),
    'piani': (
        'Un piano dice cosa fare; le sue assegnazioni dicono su quali asset e ogni quanto.',
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
    'catalogo_software': (
        "Tutti i programmi installati sui PC secondo l'ultimo inventario, con PC, versioni, licenza e CVE.",
        'Apri un programma e decidi: Consentito, Da rimuovere o Non autorizzato; indica se è a pagamento e la versione minima.',
        'Il SOC segnala con un alert i PC con software non autorizzato, da rimuovere o sotto la versione minima.',
    ),
    'rete_indirizzi': (
        'Gli indirizzi della rete letti ogni ora dal DHCP e dal DNS di Windows Server, con gli ambiti e la loro occupazione.',
        'Filtro «Non censiti»: dispositivi in rete che nessun asset riconosce per MAC, IP o nome.',
        'I collegamenti agli asset si confermano dalla Riconciliazione dispositivi IT.',
    ),
    'rete_rack': (
        'Gli armadi di rete con i loro switch: per ogni switch le porte che serve (es. A0.2) e i dispositivi collegati.',
        'Il membro dello stack si indica sulla scheda dello switch: membro 2 = porte A0.2.x.',
        'In fondo le porte che nessuno switch censito serve e gli apparati non ancora messi in un rack.',
    ),
    'mtconnect': (
        "Le CNC lette dal loro agent MTConnect ogni 2 minuti: stato reale sulla mappa officina, programma, allarmi.",
        "Ore di lavoro e pezzi avanzano i contatori Ore e Cicli della macchina, al massimo una volta all'ora.",
        "Prima di salvare usa «Prova»: dice cosa legge dall'agent e se espone ore e pezzi.",
    ),
}


def help_for(item_key: str) -> tuple[str, ...]:
    return HELP_TEXTS.get(item_key, ())
