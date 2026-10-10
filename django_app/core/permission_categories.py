"""Categorie dei permessi per la pagina Accessi: modulo, categoria, etichetta.

Il catalogo reale (868 permessi in dev al 10/10/2026) non si legge per nome di
code. Due terzi dei permessi nascono da ``bootstrap_acl_v2``, uno per rotta
(``admin_portale.api_navigation_item_create.view``), o dall'import legacy, uno
per pulsante (``legacy.assets.assets_wm_map``). Raggrupparli per "secondo
segmento del code" produceva centinaia di gruppi da un permesso solo, con nomi
come ``Api navigation item create``: chi concedeva accessi doveva leggere un
codice alla volta.

Qui ogni permesso riceve tre cose, tutte di sola presentazione:

* il **modulo di pagina** in cui compare (``display_module``): coincide col campo
  ``module`` tranne dove quel campo spezza una stessa funzione in piu' banchi
  (``sicurezza`` e ``rilevazione_incidenti``, ``rifiuti`` e ``rentri``, le API
  delle anomalie sotto ``api``, le decine di micro-moduli tecnici come
  ``login``/``logout``/``healthz`` riuniti in *Piattaforma*);
* la **categoria** dentro il modulo (``category_for``), da una tabella di regole
  scritta leggendo il catalogo e le rotte che ciascun permesso governa;
* un'**etichetta leggibile** quando quella a database e' solo il nome tecnico
  della rotta (``admin_portale / utente_toggle_active``).

ATTENZIONE: come :mod:`core.permission_taxonomy`, nulla qui e' un confine di
sicurezza. Cambia solo dove un interruttore compare nella pagina: il grant
salvato e' sempre il singolo permission code, e la decisione ACL resta in
:mod:`core.acl_resolver`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── Modulo di pagina ──────────────────────────────────────────────────────────

PLATFORM_MODULE = "piattaforma"

# Moduli che a database hanno un nome diverso dalla funzione che governano.
MODULE_ALIASES = {
    "admin": "admin_portale",
    "portale_esterno": "admin_portale",
    "gestione-anomalie": "anomalie",
    "gestione_anomalie": "anomalie",
    "sicurezza": "rilevazione_incidenti",
    "rifiuti": "rentri",
    "monitoring_admin": "monitoring",
}

# Micro-moduli generati dal bootstrap per le pagine comuni a tutti: uno o due
# permessi ciascuno, un banco a testa li rendeva introvabili.
PLATFORM_SOURCE_MODULES = frozenset({
    "approval_proxy",
    "bacheca",
    "cambia_password",
    "check",
    "coming",
    "core",
    "gestione_reparto",
    "gestione_utenti",
    "health",
    "healthz",
    "home_portale",
    "hub_preview",
    "impersonation",
    "login",
    "logout",
    "mie_attivita",
    "modifica_capo",
    "modifica_info_completa",
    "notifiche",
    "organigramma",
    "preferenze",
    "profilo",
    "readyz",
    "richieste",
    "rubrica",
    "scadenze",
    "twofa",
    "version",
})

# Permessi che il campo ``module`` mette nel posto sbagliato, decisi uno per uno
# leggendo le rotte che governano.
CODE_MODULE_OVERRIDES = {
    # Pulsanti legacy della dashboard che aprono il modulo Anomalie.
    "legacy.dashboard.gestione_anomalie": "anomalie",
    "legacy.dashboard.dashboard_anomalie_menu": "anomalie",
}

MODULE_LABELS = {
    PLATFORM_MODULE: "Piattaforma e servizi comuni",
    "admin_portale": "Amministrazione portale",
    "ai_assistant": "Assistente AI",
    "anagrafica": "Anagrafica e risorse umane",
    "anomalie": "Anomalie e non conformità",
    "assenze": "Assenze",
    "assets": "Asset e manutenzione",
    "attrezzature": "Gestione attrezzature",
    "automazioni": "Automazioni",
    "capa": "Azioni correttive (CAPA)",
    "checklist_operativa": "Checklist operativa",
    "contatori": "Contatori stampanti e SNMP",
    "dashboard": "Dashboard e bacheca dipendente",
    "diario_preposto": "Diario del preposto",
    "dpi": "DPI",
    "fornitori": "Fornitori",
    "gestione_carichi_macchina": "Carichi macchina",
    "gestione_specifiche": "Gestione specifiche",
    "glossario_tecnico": "Glossario tecnico",
    "hub_tools": "Strumenti HUB",
    "monitoring": "Monitoraggio",
    "notizie": "Notizie e comunicazioni",
    "planimetria": "Planimetria",
    "procedure_refresh": "Presa visione procedure",
    "rentri": "RENTRI - registro rifiuti",
    "report_conformita": "Report di conformità",
    "rilevazione_incidenti": "Rilevazione incidenti",
    "schede_sicurezza": "Schede di sicurezza (SDS)",
    "security": "Security Center (SOC)",
    "setup_wizard": "Setup Wizard",
    "sistema_gestione": "Sistema di gestione (SoA e audit)",
    "suggestion_corner": "Suggestion Corner",
    "tasks": "Attività e KICK-OFF",
    "tickets": "Ticket",
    "timbri": "Timbrature",
}


def _norm_module(module: str) -> str:
    return str(module or "").strip().lower()


def display_module(code: str, module: str) -> str:
    """Banco della pagina Accessi in cui compare il permesso."""
    normalized = str(code or "").strip().lower()
    source = _norm_module(module)
    if normalized in CODE_MODULE_OVERRIDES:
        return CODE_MODULE_OVERRIDES[normalized]
    if source == "api":
        # `api.anomalie_*`: endpoint del modulo Anomalie registrati sotto /api/.
        return "anomalie" if normalized.startswith("api.anomalie") else PLATFORM_MODULE
    if source == "admin_portale" and normalized.startswith("admin_portale.automazioni"):
        # Le stesse funzioni di Automazioni, servite dentro /admin-portale/.
        return "automazioni"
    if source in PLATFORM_SOURCE_MODULES:
        return PLATFORM_MODULE
    return MODULE_ALIASES.get(source, source or "senza modulo")


def module_label(display: str) -> str:
    return MODULE_LABELS.get(display, str(display or "").replace("_", " ").replace("-", " ").capitalize())


# ── Soggetto del permesso ─────────────────────────────────────────────────────


def permission_subject(code: str, module: str) -> str:
    """Il code senza ``legacy.`` e senza il nome del modulo, a parole unite da ``_``.

    ``legacy.assets.assets_wm_map`` -> ``wm_map``;
    ``admin_portale.utente_toggle_active.view`` -> ``utente_toggle_active_view``.
    E' il testo su cui lavorano le regole delle categorie: togliere il modulo
    evita che ``assets`` faccia scattare ogni regola che cerca ``asset``.
    """
    parts = [part for part in str(code or "").strip().lower().split(".") if part]
    if parts and parts[0] == "legacy":
        parts = parts[1:]
    source = _norm_module(module).replace("-", "_")
    if len(parts) > 1 and parts[0].replace("-", "_") == source:
        parts = parts[1:]
    subject = "_".join(parts).replace("-", "_")
    while source and subject.startswith(source + "_"):
        subject = subject[len(source) + 1:]
    return subject


# ── Categorie ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CategoryRule:
    key: str
    label: str
    pattern: str = ""
    # Se valorizzato la regola vale solo per i permessi nati in questi moduli
    # (serve a Piattaforma, che raccoglie moduli diversi).
    source_modules: frozenset = frozenset()

    def matches(self, subject: str, source_module: str) -> bool:
        if self.source_modules and source_module not in self.source_modules:
            return False
        # Senza pattern la regola prende tutto cio' che le arriva: e' la
        # categoria "di chiusura" del modulo, o quella di un modulo d'origine.
        return not self.pattern or re.search(self.pattern, subject) is not None


def _rules(*rows) -> tuple[CategoryRule, ...]:
    built = []
    for row in rows:
        key, label, pattern, *rest = row
        built.append(CategoryRule(key, label, pattern, frozenset(rest[0]) if rest else frozenset()))
    return tuple(built)


# La prima regola che corrisponde vince: l'ordine conta e va dal piu' specifico
# al piu' generico. L'ordine e' anche quello in cui le categorie compaiono.
CATEGORY_RULES: dict[str, tuple[CategoryRule, ...]] = {
    PLATFORM_MODULE: _rules(
        ("accesso", "Login, logout e cambio password", "", {"login", "logout", "cambia_password", "check"}),
        ("verifica_due_passaggi", "Verifica in due passaggi", "", {"twofa"}),
        ("home", "Home, bacheca e pagine comuni", "",
         {"core", "coming", "richieste", "hub_preview", "home_portale", "bacheca", "mie_attivita", "scadenze"}),
        ("notifiche", "Notifiche", "", {"notifiche"}),
        ("notifiche", "Notifiche", r"notific", {"api"}),
        ("profilo", "Profilo e preferenze", "", {"profilo", "preferenze"}),
        ("persone", "Rubrica, organigramma e reparto", "",
         {"rubrica", "organigramma", "gestione_reparto", "modifica_capo", "modifica_info_completa", "gestione_utenti"}),
        ("persone", "Rubrica, organigramma e reparto", r"reparto", {"api"}),
        ("bacheca_dipendente", "Bacheca dipendente, widget e preferenze tabelle",
         r"employee_board|widget|onboarding|table_prefs|debug_ui", {"api"}),
        ("home", "Home, bacheca e pagine comuni", r"global_search|route", {"api"}),
        ("impersonazione", "Impersonazione", "", {"impersonation"}),
        ("approvazioni_link", "Approvazioni via link (Entra proxy)", "", {"approval_proxy"}),
        ("sonde", "Sonde tecniche (health, ready, versione)", "", {"health", "healthz", "readyz", "version"}),
    ),
    "admin_portale": _rules(
        ("pannello", "Pannello di amministrazione", r"^(home|index|route|pannello)"),
        ("accessi", "Accessi, gruppi, ruoli e permessi",
         r"accessi|acl|permess|matrice|gestione_ruoli|ruol[oi]|user_(perm|modulo|module)"),
        ("anagrafica", "Configurazione anagrafica", r"anagrafica|opzione"),
        ("reparti", "Reparti e responsabili", r"reparto"),
        ("utenti", "Utenti e account", r"utent[ei]|gestione_utenti|ldap_(import|utenti)|api_user_|ruolo_create"),
        ("login", "Pagina di login e verifica in due passaggi", r"login|twofa"),
        ("navigazione", "Menu, navigazione e pulsanti",
         r"navigation|nav_user|pulsant|modulo_crea|module_card|topbar|legacy_redirect"),
        ("aspetto", "Branding e modelli PDF", r"branding|pdf_template|template_(config|preview)"),
        ("checklist", "Checklist utenti", r"checklist"),
        ("ai", "Assistente AI: impostazioni e conoscenza", r"(^|_)ai(_|$)"),
        ("bacheca", "Bacheca e notifiche di sistema", r"bacheca|hub_(category|link|reorder)|notifiche"),
        ("diagnostica", "Audit, attività utenti e diagnostica",
         r"audit|activity|health|diagnostica|schema_dati"),
        ("release", "Release e database", r"release|database|hub_database"),
        ("portale_esterno", "Portale esterno ospiti", r"portale_esterno|guestportal"),
    ),
    "ai_assistant": _rules(
        ("conoscenza", "Knowledge base e feedback", r"knowledge|feedback"),
        ("chat", "Chat, brief e report", r"chat|brief|report"),
    ),
    "anagrafica": _rules(
        ("cruscotto", "Cruscotto del modulo", r"^index"),
        ("riservati", "Dati HR, documenti riservati e statistiche", r"^hr|riservat|statistiche"),
        ("fornitori", "Fornitori", r"fornitor"),
        ("visite", "Visite mediche e sorveglianza sanitaria", r"visit|referti|sanitari"),
        ("formazione", "Formazione", r"formazione|corsi|attestat"),
        ("skillmatrix", "Skill matrix", r"skillmatrix|skill_matrix|skm"),
        ("mpq", "Processi qualificati (MOD.128)", r"mpq"),
        ("recruiting", "Recruiting e ingressi", r"recruiting|onboarding|ingress|posizion|candidat"),
        ("cambio_mansione", "Cambio mansione", r"cambio_mansione|adempiment"),
        ("dipendenti", "Dipendenti e schede", r"dipendent"),
        ("mansioni", "Mansioni", r"mansion"),
        ("qualifiche", "Qualifiche e tipi di qualifica", r"qualific"),
        ("ruoli", "Ruoli operativi", r"ruol[oi]"),
        ("reportistica", "Reportistica ed export", r"reportistica|export"),
        ("configurazione", "Schede, widget e cataloghi", r"scheda|widget|impostazioni|catalog"),
    ),
    "anomalie": _rules(
        ("configurazione", "Configurazione del modulo", r"config|^admin|(^|_)db(_|$)"),
        ("report", "Statistiche, report ed export", r"statistiche|report|export|filtrato"),
        ("controlli", "Controlli e blocchi", r"controll"),
        ("qualita", "Qualità, NC e copilota", r"(^|_)nc(_|$)|qualita|copilota|timeline"),
        ("gestione", "Gestione delle segnalazioni",
         r"gestione|salva|allegat|sync|notifica|seriali|ricerca|descrizione"),
        ("segnalazione", "Segnalazione e consultazione", r""),
    ),
    "assenze": _rules(
        ("richieste", "Richieste e le mie assenze", r"richiesta|view_assenze"),
        ("calendario", "Calendario ed eventi", r"calendario|evento|eventi"),
        ("gestione", "Gestione e approvazione", r"gestione|admin"),
        ("sincronizzazione", "Sincronizzazione SharePoint", r"sync"),
        ("modulo", "Accesso al modulo", r""),
    ),
    "assets": _rules(
        ("configurazione", "Impostazioni, layout e report template",
         r"gestione|(^|_)admin(_|$)|detail_layout|view_layout|save_config|report_template|reports_manage"),
        ("report", "Report, etichette e stampe", r"maintenance_month|report|label|qr"),
        ("macchine", "Macchine di lavoro e mappa officina", r"work_machine|(^|_)wm(_|$)|plant_layout"),
        ("manutenzione", "Manutenzione: piani, regole e template",
         r"maint|manutenz|override|(^|_)plans?(_|$)|piani"),
        ("scadenze", "Scadenze amministrative e contratti", r"deadline|assistance|contratt|calend"),
        ("verifiche", "Verifiche periodiche impianti", r"periodic|verific"),
        ("odl", "Ordini di lavoro (OdL)", r"(^|_)wo(_|$)|workorder"),
        ("componenti", "Componenti", r"component"),
        ("inventario", "Inventario asset", r""),
    ),
    "attrezzature": _rules(
        ("import", "Import da Excel", r"import"),
        ("task", "Task delle attrezzature", r"task"),
        ("kickoff", "Collegamento KICK-OFF", r"kickoff"),
        ("attrezzature", "Attrezzature", r""),
    ),
    "automazioni": _rules(
        ("impostazioni", "Impostazioni", r"settings"),
        ("approvazioni", "Approvazioni e modelli di approvazione", r"approval"),
        ("integrazioni", "Teams e casella di posta", r"teams|mailbox"),
        ("pianificazioni", "Automazioni pianificate e notifiche di sistema", r"pianificat|event"),
        ("esecuzioni", "Coda ed esecuzioni", r"queue|(^|_)run(_|$)|record|recent"),
        ("sorgenti", "Sorgenti, tabelle e contenuti", r"sorgent|source|table|contenut|^manage$|^view$"),
        ("regole", "Regole e designer", r"rule|regol|htmx|designer|trigger|power_automate"),
    ),
    "capa": _rules(
        ("verifica", "Presa in carico, chiusura e verifica", r"take|close|verify|cancel"),
        ("azioni", "Azioni correttive", r""),
    ),
    "checklist_operativa": _rules(
        ("configurazione", "Configurazione task, eventi e proposte", r"configurazione|task|evento|voce|propost"),
        ("riepilogo", "Riepilogo", r"riepilogo"),
        ("compilazione", "Compilazione e conferme", r""),
    ),
    "contatori": _rules(
        ("accesso", "Accesso e gestione del modulo", r"^modulo|^gestione"),
        ("snmp", "SNMP: centrale, dispositivi, profili e discovery",
         r"snmp|discovery|wizard|sond|profil|dispositiv|oid"),
        ("letture", "Letture e import", r"lettur|importa"),
        ("fatture", "Fatture e riconciliazione", r"fattur|riconcili"),
        ("consumabili", "Consumabili", r"consumabil"),
        ("analisi", "Analisi ed export", r"analisi|export"),
        ("macchine", "Stampanti multifunzione (MFC)", r"macchin"),
        ("cruscotto", "Cruscotto", r""),
    ),
    "dashboard": _rules(
        ("bacheca_dipendente", "Bacheca dipendente", r"employee"),
        ("scheda", "Scheda dipendente", r"scheda"),
        ("primo_accesso", "Primo accesso (onboarding)", r"onboarding"),
        ("richieste", "Richieste", r"richieste"),
        ("widget", "Widget personali", r"api_(layout|toggle)"),
        ("home", "Home e dashboard", r""),
    ),
    "diario_preposto": _rules(
        ("impostazioni", "Impostazioni", r"impostazioni"),
        ("allegati", "Allegati", r"allegat"),
        ("export", "Export", r"export"),
        ("diario", "Ispezioni e diario", r""),
    ),
    "dpi": _rules(
        ("catalogo", "Catalogo: categorie, tipi e modelli", r"categori|impostazioni|tipo|modello"),
        ("gestione", "Gestione richieste: approvazione e consegna", r"gestione|approva|rifiuta|consegna|manage"),
        ("magazzino", "Cruscotto, magazzino e report", r"magazzino|report"),
        ("richieste", "Richieste e storico del dipendente", r""),
    ),
    "fornitori": _rules(
        ("documenti", "Documenti", r"documento"),
        ("ordini", "Ordini", r"ordine"),
        ("valutazioni", "Valutazioni", r"valutazione"),
        ("asset", "Asset collegati", r"asset"),
        ("anagrafica_fornitori", "Creazione e modifica", r"create|edit|toggle"),
        ("elenco", "Elenco e scheda fornitore", r""),
    ),
    "gestione_carichi_macchina": _rules(("piano", "Piano dei carichi", r"")),
    "gestione_specifiche": _rules(
        ("amministrazione", "Amministrazione e cartelle", r"^admin"),
        ("mod133", "MOD.133", r"mod133"),
        ("distribuzione", "Distribuzione copie", r"distribu"),
        ("registro_ofi", "Registro OFI", r"ofi"),
        ("specifiche", "Specifiche", r""),
    ),
    "glossario_tecnico": _rules(("termini", "Termini e varianti", r"")),
    "hub_tools": _rules(
        ("database", "Database e backup", r"(^|_)db_|database"),
        ("aspetto", "Branding, homepage e KPI", r"branding|homepage|kpi"),
        ("moduli", "Moduli, categorie e pulsanti", r"moduli|pulsant|categorie"),
        ("notifiche", "Notifiche", r"notific"),
        ("guide", "Guide", r"guide"),
        ("setup", "Setup e riconfigurazione", r"setup|reconfigure"),
        ("hub", "Pagina HUB", r""),
    ),
    "monitoring": _rules(
        ("sonde", "Sonde di stato (health, ready)", r"healthz|readyz"),
        ("problemi", "Segnalazione problemi", r"problem"),
        ("automazioni", "Automazioni monitorate", r"automation"),
        ("issue", "Issue", r"issue"),
        ("stato", "Stato del sistema e schedulazioni", r"system|schedule|status"),
        ("cruscotto", "Cruscotto", r""),
    ),
    "notizie": _rules(
        ("report", "Report HR ed export", r"report"),
        ("lettura", "Lettura e conferma", r"lista|conferma|obbligatorie|^view_notizie"),
        ("redazione", "Redazione e pubblicazione", r""),
    ),
    "planimetria": _rules(
        ("editor", "Editor", r"editor"),
        ("mappa", "Mappa", r""),
    ),
    "procedure_refresh": _rules(
        ("mie_procedure", "Le mie procedure (presa visione)",
         r"my_assign|view_procedure|^assignment_detail|pr_assignment_detail|document_open"),
        ("campagne", "Campagne", r"campaign"),
        ("documenti", "Documenti e revisioni", r"document|revision"),
        ("assegnazioni", "Assegnazioni", r"assign"),
        ("report", "Report ed export", r"report|export"),
        ("amministrazione", "Amministrazione e SharePoint", r""),
    ),
    "rentri": _rules(
        ("import_export", "Import ed export", r"import|export"),
        ("sincronizzazione", "Sincronizzazione", r"sync"),
        ("registro", "Registro: carico, scarico e rettifica", r"carico|rettifica|registro"),
        ("consultazione", "Consultazione e scadenzario", r""),
    ),
    "report_conformita": _rules(
        ("accesso", "Accesso al modulo", r"^modulo"),
        ("sezioni", "Sezioni del report", r""),
    ),
    "rilevazione_incidenti": _rules(
        ("impostazioni", "Impostazioni", r"impostazioni"),
        ("statistiche", "Statistiche ed export", r"statistiche|export"),
        ("rilevazioni", "Rilevazioni", r""),
    ),
    "schede_sicurezza": _rules(("prodotti", "Prodotti e schede di sicurezza", r"")),
    "security": _rules(
        ("configurazione", "Configurazione SOC, sorgenti e diagnostica",
         r"config|settings|autoconfig|addon|mailbox|diagnostic"),
        ("incidenti", "Incidenti (NIS2)", r"incident"),
        ("alert", "Alert", r"alert"),
        ("eventi", "Eventi", r"event|escalation"),
        ("ticket", "Ticket e casi", r"ticket|case"),
        ("backup", "Backup", r"backup"),
        ("dispositivi", "PC, asset e VPN", r"assets|(^|_)pc(_|$)|preview|vpn"),
        ("analisi", "Analisi, report e pipeline", r"history|report|pipeline|inbox|(^|_)ai(_|$)"),
        ("panoramica", "Panoramica, KPI e documentazione", r""),
    ),
    "setup_wizard": _rules(
        ("test", "Test delle connessioni (DB, LDAP, SMTP)", r"test"),
        ("configurazione", "Configurazione, moduli e migrazioni", r""),
    ),
    "sistema_gestione": _rules(
        ("accesso", "Accesso al modulo", r"^modulo"),
        ("audit", "Audit", r"audit"),
        ("soa", "Dichiarazione di applicabilità (SoA)", r"soa"),
    ),
    "suggestion_corner": _rules(("segnalazioni", "Segnalazioni", r"")),
    "tasks": _rules(
        ("kickoff", "KICK-OFF: permessi per azione", r"^kickoff"),
        ("amministrazione", "Amministrazione e impostazioni", r"admin|impostazioni|gestione"),
        ("progetti", "Progetti, Gantt e VRF", r"project|gantt|^route"),
        ("collaborazione", "Commenti, allegati e sottotask", r"comment|attachment|subtask"),
        ("attivita", "Attività", r""),
    ),
    "tickets": _rules(
        ("impostazioni", "Impostazioni e integrazione SharePoint", r"impostazioni|test_sp"),
        ("asset", "Collegamento agli asset", r"asset"),
        ("allegati", "Allegati", r"allegat"),
        ("gestione", "Gestione ticket (operatori)", r"gestione|assegna|stato|bulk|commento|cerca_utenti|import"),
        ("ticket", "Apertura e consultazione", r""),
    ),
    "timbri": _rules(
        ("configurazione", "Configurazione e import SharePoint", r"config|import"),
        ("export", "Export e report", r"export|report"),
        ("registro", "Registrazioni", r"registro|edit"),
        ("operatori", "Operatori e schede", r"operator|timbri_view|^view$|serve_image"),
        ("elenco", "Elenco timbrature", r""),
    ),
}

FALLBACK_CATEGORY = ("altro", "Altre funzioni")

# Permessi che il nome colloca male, decisi leggendo le rotte che governano.
CODE_CATEGORY_OVERRIDES = {
    # "DPI - Dashboard": governa magazzino, report di conformita' e giacenze.
    "legacy.dpi.dpi_view": "magazzino",
}


def category_for(code: str, module: str) -> tuple[str, str]:
    """(chiave, etichetta) della categoria del permesso nel suo modulo di pagina."""
    source = _norm_module(module)
    target = display_module(code, module)
    rules = CATEGORY_RULES.get(target, ())
    forced = CODE_CATEGORY_OVERRIDES.get(str(code or "").strip().lower())
    if forced:
        for rule in rules:
            if rule.key == forced:
                return rule.key, rule.label
    subject = permission_subject(code, module)
    for rule in rules:
        if rule.matches(subject, source):
            return rule.key, rule.label
    return FALLBACK_CATEGORY


def category_order(display: str) -> dict[str, int]:
    """Posizione di ogni categoria: quella in cui sono scritte le regole."""
    order: dict[str, int] = {}
    for rule in CATEGORY_RULES.get(display, ()):
        order.setdefault(rule.key, len(order))
    order.setdefault(FALLBACK_CATEGORY[0], len(order))
    return order


# ── Etichetta leggibile ───────────────────────────────────────────────────────

# Etichetta "tecnica": e' il nome della rotta, con o senza "modulo / " davanti.
_RAW_LABEL_RE = re.compile(r"^[a-z0-9_\-]+(\s*/\s*[a-z0-9_\-:]+)?$")

_SKIP_TOKENS = {"api", "ajax", "json", "htmx", "route", "page", "legacy", "noslash", "by"}

# Verbi: vanno in coda all'etichetta ("Regola — crea"), cosi' le righe della
# stessa risorsa si leggono una sotto l'altra.
_VERBS = {
    "view": "", "list": "elenco", "detail": "dettaglio", "index": "", "home": "",
    "create": "crea", "new": "crea", "nuovo": "crea", "nuova": "crea", "add": "aggiungi",
    "edit": "modifica", "update": "modifica", "modifica": "modifica", "set": "imposta",
    "delete": "elimina", "remove": "rimuovi", "elimina": "elimina", "clear": "azzera",
    "toggle": "attiva/disattiva", "save": "salva", "salva": "salva", "upload": "carica",
    "export": "esporta", "import": "importa", "run": "esegui", "test": "prova",
    "reset": "ripristina", "retry": "riprova", "stop": "ferma", "manage": "gestisci",
    "approve": "approva", "approva": "approva", "rifiuta": "rifiuta", "publish": "pubblica",
    "close": "chiudi", "reorder": "riordina", "restore": "ripristina", "clone": "duplica",
    "preview": "anteprima", "download": "scarica", "bulk": "in blocco", "sync": "sincronizza",
    "assign": "assegna", "assegna": "assegna", "submit": "invia", "invia": "invia",
}

_WORDS = {
    "accessi": "accessi", "acl": "ACL", "action": "azione", "active": "attivo", "activity": "attività",
    "admin": "amministrazione", "administrative": "amministrativa", "alert": "alert", "alerts": "alert",
    "allegato": "allegato", "allegati": "allegati", "analisi": "analisi", "anagrafica": "anagrafica",
    "approval": "approvazione", "asset": "asset", "assets": "asset", "assignment": "assegnazione",
    "assignments": "assegnazioni", "assistance": "assistenza", "attachment": "allegato", "audit": "audit",
    "automation": "automazione", "automazioni": "automazioni", "avanzati": "avanzati", "backup": "backup",
    "banner": "banner", "board": "bacheca", "bootstrap": "bootstrap", "branding": "branding",
    "builder": "costruttore", "calendar": "calendario", "calendario": "calendario", "campaign": "campagna",
    "capo": "responsabile", "card": "scheda", "catalog": "catalogo", "categorie": "categorie",
    "change": "cambio", "checklist": "checklist", "comment": "commento", "component": "componente",
    "condition": "condizione", "config": "configurazione", "configurazione": "configurazione",
    "contract": "contratto", "coverage": "copertura", "dashboard": "cruscotto", "database": "database",
    "deadline": "scadenza", "designer": "designer", "diagnostica": "diagnostica", "dipendente": "dipendente",
    "dipendenti": "dipendenti", "document": "documento", "due": "scadenza", "effettivi": "effettivi",
    "employee": "dipendente", "enabled": "abilitazione", "endpoint": "endpoint", "esegui": "esecuzione",
    "extra": "aggiuntive", "flow": "flusso", "force": "forza", "gantt": "Gantt", "gestione": "gestione",
    "guide": "guide", "health": "stato", "icon": "icona", "image": "immagine", "impersonate": "impersona",
    "impostazioni": "impostazioni", "info": "informazioni", "item": "voce", "kpi": "KPI", "label": "etichetta",
    "layout": "layout", "ldap": "LDAP", "log": "registro", "login": "login", "logo": "logo",
    "machine": "macchina", "mailbox": "casella di posta", "maintenance": "manutenzione", "map": "mappa",
    "mappa": "mappa", "matrice": "matrice", "migrations": "migrazioni", "moduli": "moduli", "module": "modulo",
    "modulo": "modulo", "my": "le mie", "navigation": "navigazione", "navigazione": "navigazione",
    "notifiche": "notifiche", "notifica": "notifica", "operatore": "operatore", "opzione": "opzione",
    "override": "eccezione", "package": "pacchetto", "password": "password", "payload": "contenuto",
    "perm": "permesso", "permessi": "permessi", "pdf": "PDF", "plant": "officina", "power": "Power",
    "automate": "Automate", "presets": "preset", "preset": "preset", "project": "progetto",
    "pulsante": "pulsante", "pulsanti": "pulsanti", "qr": "QR", "queue": "coda", "quick": "rapido",
    "recent": "recenti", "record": "record", "redirect": "reindirizzamento", "release": "release",
    "reparto": "reparto", "report": "report", "reports": "report", "result": "risultato", "revision": "revisione",
    "risposte": "risposte", "role": "ruolo", "ruoli": "ruoli", "ruolo": "ruolo", "rule": "regola",
    "rules": "regole", "schedule": "programmazione", "schema": "schema", "dati": "dati", "semplice": "semplice",
    "settings": "impostazioni", "shift": "spostamento", "source": "sorgente", "sorgenti": "sorgenti",
    "status": "stato", "subtask": "sottotask", "table": "tabella", "task": "attività", "teams": "Teams",
    "template": "modello", "templates": "modelli", "toggle": "attivazione", "topbar": "barra superiore",
    "trigger": "trigger", "user": "utente", "users": "utenti", "utente": "utente", "utenti": "utenti",
    "voce": "voce", "widget": "widget", "wizard": "procedura guidata", "work": "lavoro", "wo": "OdL",
    "workorder": "OdL", "worksheet": "foglio di lavoro", "month": "mese", "values": "valori", "field": "campo",
}


_WORDS.update({
    "addon": "componente aggiuntivo", "addons": "componenti aggiuntivi", "autoconfig": "configurazione automatica",
    "autocomplete": "completamento automatico", "backups": "backup", "brief": "sintesi", "case": "caso",
    "category": "categoria", "cleanup": "pulizia", "command": "comando", "debug": "debug", "device": "dispositivo",
    "diagnostics": "diagnostica", "discovery": "rilevamento", "doc": "documentazione", "docs": "documentazione",
    "event": "evento", "events": "eventi", "explain": "spiegazione", "general": "generali", "global": "globale",
    "guestportal": "portale ospiti", "help": "guida", "history": "storico", "inbox": "posta in arrivo",
    "incident": "incidente", "incidents": "incidenti", "ingestion": "acquisizione", "issue": "segnalazione",
    "knowledge": "conoscenza", "landing": "pagina iniziale", "link": "collegamento", "live": "in tempo reale",
    "locked": "blocco", "many": "multipli", "method": "metodo", "milestone": "scadenza", "note": "nota",
    "notifications": "notifiche", "optimize": "ottimizzazione", "overview": "panoramica", "panel": "pannello",
    "parsers": "parser", "partial": "parziale", "pc": "PC", "policy": "criteri", "prefs": "preferenze",
    "problem": "problema", "proposals": "proposte", "register": "registro", "resolution": "esito",
    "search": "ricerca", "serve": "apertura", "service": "servizio", "sidebar": "barra laterale",
    "sources": "sorgenti", "sp": "SharePoint", "sso": "SSO", "stats": "statistiche", "steps": "passi",
    "strip": "barra", "summary": "sintesi", "suppressions": "soppressioni", "system": "sistema",
    "terminal": "terminale", "tool": "strumento", "trim": "trimestrale", "ui": "interfaccia", "vpn": "VPN",
    "kpis": "KPI", "smtp": "SMTP", "db": "database", "ip": "IP", "oid": "OID", "snmp": "SNMP",
    "pianificati": "pianificate", "mail": "mail", "tasks": "attività", "from": "da",
    # Segnaposto delle locuzioni (vedi _PHRASES).
    "workmachine": "macchina di lavoro", "plantlayout": "mappa officina", "periodicverif": "verifiche periodiche",
    "admindeadline": "scadenza amministrativa", "assistancecontract": "contratto di assistenza",
    "maintenancerule": "regola di manutenzione", "maintenancetemplate": "modello di manutenzione",
    "maintenanceschedule": "programma manutenzioni", "ruleoverride": "eccezione alla regola",
    "labeldesigner": "editor etichette", "qrlabel": "etichetta QR", "reporttemplate": "modelli di report",
    "detaillayout": "layout della scheda", "legacyredirect": "reindirizzamento legacy",
    "eventnotifications": "notifiche di sistema", "markallread": "segna tutte come lette",
    "archivialette": "archivia le lette", "duedate": "scadenza", "changestatus": "cambio stato",
    "forcechangepassword": "obbligo di cambio password", "dailybrief": "sintesi del giorno",
    "bootstrapfromlegacy": "importa dal legacy",
})
_VERBS.update({
    "promote": "promuovi", "confirm": "conferma", "apply": "applica", "fix": "correggi", "restart": "riavvia",
    "scarta": "scarta", "archivia": "archivia", "leggi": "leggi", "interroga": "interroga", "avvia": "avvia",
    "applica": "applica", "verifica": "verifica", "decidi": "decidi", "riapri": "riapri", "chiudi": "chiudi",
    "termina": "termina", "apri": "apri", "upsert": "inserisci o aggiorna", "take": "prendi in carico",
    "verify": "verifica", "cancel": "annulla", "aggiorna": "aggiorna", "conferma": "conferma",
    "proponi": "proponi", "ok": "",
})

# Locuzioni che tradotte parola per parola non si leggono ("lavoro macchina").
_PHRASES = (
    ("force_change_password", "forcechangepassword"),
    ("bootstrap_from_legacy", "bootstrapfromlegacy"),
    ("periodic_verifications", "periodicverif"),
    ("administrative_deadline", "admindeadline"),
    ("assistance_contract", "assistancecontract"),
    ("maintenance_rule", "maintenancerule"),
    ("maintenance_template", "maintenancetemplate"),
    ("maintenance_schedule", "maintenanceschedule"),
    ("event_notifications", "eventnotifications"),
    ("mark_all_read", "markallread"),
    ("archivia_lette", "archivialette"),
    ("legacy_redirect", "legacyredirect"),
    ("label_designer", "labeldesigner"),
    ("report_template", "reporttemplate"),
    ("detail_layout", "detaillayout"),
    ("rule_override", "ruleoverride"),
    ("work_machine", "workmachine"),
    ("plant_layout", "plantlayout"),
    ("change_status", "changestatus"),
    ("daily_brief", "dailybrief"),
    ("due_date", "duedate"),
    ("qr_label", "qrlabel"),
)

# Nome leggibile dei moduli d'origine riuniti in un altro banco: quando il code
# e' solo `<modulo>.route.view` e' l'unica cosa che dice quale pagina sia.
SOURCE_MODULE_LABELS = {
    "approval_proxy": "Approvazione via link",
    "bacheca": "Bacheca",
    "cambia_password": "Cambio password",
    "check": "Verifica sessione legacy",
    "coming": "Pagine in arrivo",
    "core": "Home",
    "gestione_reparto": "Gestione reparto",
    "gestione_utenti": "Modifica utente (legacy)",
    "health": "Health check",
    "healthz": "Sonda healthz",
    "home_portale": "Home portale",
    "hub_preview": "Anteprima HUB",
    "impersonation": "Impersonazione",
    "login": "Login",
    "logout": "Logout",
    "mie_attivita": "Le mie attività",
    "modifica_capo": "Modifica responsabile",
    "modifica_info_completa": "Modifica informazioni complete",
    "notifiche": "Notifiche",
    "organigramma": "Organigramma",
    "preferenze": "Preferenze",
    "profilo": "Profilo",
    "readyz": "Sonda readyz",
    "richieste": "Richieste",
    "rubrica": "Rubrica",
    "scadenze": "Scadenze",
    "twofa": "Verifica in due passaggi",
    "version": "Versione",
}


def is_raw_label(label: str) -> bool:
    return bool(_RAW_LABEL_RE.match(str(label or "").strip()))


def _base_label(code: str, module: str) -> str:
    source = _norm_module(module)
    if source in SOURCE_MODULE_LABELS:
        return SOURCE_MODULE_LABELS[source]
    return module_label(display_module(code, module))


def readable_label(code: str, module: str, label: str) -> str:
    """L'etichetta a database se e' gia' leggibile, altrimenti una ricavata dal code.

    Le etichette scritte a mano ("Asset - Nuovo", "Skill Matrix - Gestisci")
    restano come sono. Le altre sono il nome della rotta generato dal bootstrap
    e diventano "Navigazione voce — crea": nomi tradotti, verbo in coda.
    """
    current = str(label or "").strip()
    if current and not is_raw_label(current):
        return current
    subject = permission_subject(code, module)
    # Spostato in un altro banco (`admin_portale.automazioni_rule_*` sotto
    # Automazioni): il nome del banco ripetuto in ogni riga e' solo rumore.
    target = display_module(code, module)
    if target != _norm_module(module) and subject.startswith(target + "_"):
        subject = subject[len(target) + 1:]
    for phrase, placeholder in _PHRASES:
        subject = re.sub(rf"(^|_){phrase}(_|$)", rf"\g<1>{placeholder}\g<2>", subject)
    nouns: list[str] = []
    verbs: list[str] = []
    for token in subject.split("_"):
        if not token or token in _SKIP_TOKENS or token.isdigit():
            continue
        if token in _VERBS:
            verb = _VERBS[token]
            if verb and verb not in verbs:
                verbs.append(verb)
            continue
        word = _WORDS.get(token, token)
        if not nouns or nouns[-1] != word:
            nouns.append(word)
    text = " ".join(nouns) if nouns else _base_label(code, module)
    if verbs:
        text = f"{text} — {', '.join(verbs)}"
    return text[:1].upper() + text[1:]
