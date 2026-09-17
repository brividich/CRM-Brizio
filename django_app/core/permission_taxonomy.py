"""Tassonomia di *presentazione* per i permessi canonici.

Serve solo a raggruppare/filtrare i permission code nelle UI admin lungo tre
assi gia' impliciti nel naming `modulo.risorsa.azione`:

* **area** funzionale (sopra il modulo) -> allineata al Project Summary del CLAUDE.md;
* **modulo** -> campo ``PermissionDefinition.module`` (fonte autorevole);
* **risorsa** -> 2o segmento del code, derivato in modo robusto anche per i
  code legacy importati come ``legacy.<modulo>.<azione>``.

In piu' espone l'**origine** del code (canonico / legacy-import / API).

ATTENZIONE: nulla qui e' un confine di sicurezza. La decisione di
autorizzazione resta in :mod:`core.acl_v2`. Questo modulo influenza solo come i
permessi vengono mostrati e filtrati nell'ACL Canonico.
"""
from __future__ import annotations

import re

# ── Aree funzionali (allineate a CLAUDE.md -> Primary product areas) ──────────
AREA_CORE = "core"
AREA_OPERAZIONI = "operazioni"
AREA_HR = "hr"
AREA_SICUREZZA = "sicurezza"
AREA_AUTOMAZIONE = "automazione"
AREA_ALTRO = "altro"

AREA_LABELS = {
    AREA_CORE: "Core / Piattaforma",
    AREA_OPERAZIONI: "Operazioni",
    AREA_HR: "HR / Workflow",
    AREA_SICUREZZA: "Sicurezza / Compliance",
    AREA_AUTOMAZIONE: "Automazione",
    AREA_ALTRO: "Altro / Non mappato",
}

# Ordine di presentazione delle aree (le non mappate finiscono in fondo).
AREA_ORDER = [
    AREA_CORE,
    AREA_OPERAZIONI,
    AREA_HR,
    AREA_SICUREZZA,
    AREA_AUTOMAZIONE,
    AREA_ALTRO,
]

# Mappa modulo -> area. I moduli non elencati ricadono in AREA_ALTRO (nessun
# permesso viene mai nascosto: l'ignoto resta sempre visibile sotto "Altro").
MODULE_AREA = {
    # Core platform
    "core": AREA_CORE,
    "dashboard": AREA_CORE,
    "admin_portale": AREA_CORE,
    "hub_tools": AREA_CORE,
    "setup_wizard": AREA_CORE,
    "monitoring": AREA_CORE,
    "ai_assistant": AREA_CORE,
    # Operations
    "anagrafica": AREA_OPERAZIONI,
    "assets": AREA_OPERAZIONI,
    "attrezzature": AREA_OPERAZIONI,
    "tasks": AREA_OPERAZIONI,
    "planimetria": AREA_OPERAZIONI,
    "gestione_specifiche": AREA_OPERAZIONI,
    # HR / workflow
    "assenze": AREA_HR,
    "anomalie": AREA_HR,
    "tickets": AREA_HR,
    "timbri": AREA_HR,
    "notizie": AREA_HR,
    # Safety / compliance
    "dpi": AREA_SICUREZZA,
    "diario_preposto": AREA_SICUREZZA,
    "rilevazione_incidenti": AREA_SICUREZZA,
    "procedure_refresh": AREA_SICUREZZA,
    "rentri": AREA_SICUREZZA,
    # Automation
    "automazioni": AREA_AUTOMAZIONE,
}


def area_for_module(module: str) -> str:
    return MODULE_AREA.get((module or "").strip().lower(), AREA_ALTRO)


def area_label(area: str) -> str:
    return AREA_LABELS.get(area, AREA_LABELS[AREA_ALTRO])


# ── Origine / tipo del permission code ───────────────────────────────────────
ORIGIN_CANONICO = "canonico"
ORIGIN_LEGACY = "legacy"
ORIGIN_API = "api"

ORIGIN_LABELS = {
    ORIGIN_CANONICO: "Canonico",
    ORIGIN_LEGACY: "Legacy",
    ORIGIN_API: "API",
}
ORIGIN_ORDER = [ORIGIN_CANONICO, ORIGIN_LEGACY, ORIGIN_API]

# Un code e' "API" quando ha un segmento "api" (es. modulo.api_xxx.view).
_API_PERMISSION_RE = re.compile(r"(^|[._])api(_|[._]|$)")


def is_api_code(code: str) -> bool:
    return bool(_API_PERMISSION_RE.search((code or "").lower()))


def origin_for_code(code: str) -> str:
    normalized = (code or "").strip().lower()
    if normalized.startswith("legacy."):
        return ORIGIN_LEGACY
    if is_api_code(normalized):
        return ORIGIN_API
    return ORIGIN_CANONICO


def origin_label(origin: str) -> str:
    return ORIGIN_LABELS.get(origin, origin or "")


# ── Natura del permesso: configurazione/amministrazione vs operativo ─────────
# Dentro un modulo convivono due cose diverse: i permessi che *impostano* il
# modulo (chi puo' cambiarne le regole, i cataloghi, chi vi accede) e quelli con
# cui lo si *usa* tutti i giorni. Chi concede accessi ragiona quasi sempre su
# questo confine — "gli do il modulo, non le sue impostazioni" — e finora doveva
# ricavarlo leggendo un codice alla volta.
NATURE_CONFIG = "configurazione"
NATURE_OPERATIVO = "operativo"

NATURE_LABELS = {
    NATURE_CONFIG: "Configurazione e amministrazione",
    NATURE_OPERATIVO: "Operativo",
}
NATURE_ORDER = [NATURE_CONFIG, NATURE_OPERATIVO]

# L'azione finale `manage` e' gia' il raccoglitore in cui `bootstrap_acl_v2`
# normalizza gestione/configurazione/impostazioni/wizard/toggle: e' il segnale
# piu' affidabile che il permesso governa il modulo invece di usarlo.
_CONFIG_ACTIONS = {"manage"}

# Risorse che sono amministrazione a prescindere dall'azione: anche un semplice
# `view` sui permessi o sugli utenti e' materia di configurazione.
_CONFIG_RESOURCE_TOKENS = {
    "acl",
    "admin",
    "amministrazione",
    "catalog",
    "catalogo",
    "config",
    "configurazione",
    "gruppi",
    "groups",
    "impostazioni",
    "permessi",
    "permission",
    "permissions",
    "roles",
    "ruoli",
    "settings",
    "setup",
    "users",
    "utenti",
    "wizard",
}


def action_for_code(code: str) -> str:
    """Ultimo segmento del code (`assets.piani.manage` -> ``manage``)."""
    parts = [segment for segment in (code or "").lower().split(".") if segment]
    return parts[-1] if len(parts) > 1 else ""


def nature_for_code(code: str, module: str = "") -> str:
    """Configurazione/amministrazione oppure operativo.

    Nessun permesso viene mai nascosto da questa funzione: e' una divisione di
    presentazione, e nel dubbio si ricade su ``operativo`` (il caso piu' comune
    e il meno sorprendente per chi legge la pagina Accessi).
    """
    if action_for_code(code) in _CONFIG_ACTIONS:
        return NATURE_CONFIG
    resource = derive_resource(code, module)
    tokens = {token for chunk in resource.split(".") for token in chunk.split("_") if token}
    if tokens & _CONFIG_RESOURCE_TOKENS:
        return NATURE_CONFIG
    return NATURE_OPERATIVO


def nature_label(nature: str) -> str:
    return NATURE_LABELS.get(nature, NATURE_LABELS[NATURE_OPERATIVO])


def derive_resource(code: str, module: str) -> str:
    """Risorsa (2o livello) ricavata dal code, robusta verso i code legacy.

    Regole: si rimuove l'azione finale; un eventuale prefisso ``legacy`` e il
    segmento che duplica il modulo vengono scartati per non generare gruppi
    rumore. Se non resta nulla di significativo si usa ``(generale)``.
    """
    parts = [segment for segment in (code or "").lower().split(".") if segment]
    if len(parts) <= 1:
        return "(generale)"
    body = parts[:-1]  # rimuove l'azione finale
    if body and body[0] == "legacy":
        body = body[1:]
    module_norm = (module or "").strip().lower()
    if len(body) > 1 and body[0] == module_norm:
        body = body[1:]
    resource = ".".join(body)
    return resource or "(generale)"


# ── Capacita' e livelli d'accesso preimpostati ──────────────────────────────
# Terzo asse, sempre di sola presentazione: che *cosa consente di fare* il
# permesso. Serve a un bisogno concreto di chi concede accessi: quasi sempre non
# vuole scegliere permesso per permesso, vuole dire "a questo ruolo il modulo in
# sola lettura". I livelli qui sotto sono quella frase tradotta in un insieme di
# interruttori, e restano una *macro di selezione*: dopo averli applicati i
# singoli permessi si correggono a mano, e cio' che viene salvato sono sempre e
# solo i grant canonici, uno per uno.
#
# La regola portante e' **fail-closed**: un permesso che non si riesce a
# classificare con certezza NON viene acceso dai livelli bassi. Il catalogo
# reale (847 permessi in dev al 17/09/2026) e' per due terzi fatto di code
# legacy importati come ``legacy.<modulo>.<nome_della_view>``, che non finiscono
# con un'azione canonica: ``legacy.assets.asset_create``,
# ``legacy.assenze.assenze_evento_delete``, ``legacy.assets.assets_bulk_update``.
# Leggerli come "lettura" perche' non finiscono in ``create``/``edit`` vorrebbe
# dire che "Solo lettura" concede creazioni e cancellazioni: e' esattamente
# l'errore che questo modulo deve non fare.
CAPABILITY_LETTURA = "lettura"
CAPABILITY_MODIFICA = "modifica"
CAPABILITY_APPROVAZIONE = "approvazione"
CAPABILITY_AMMINISTRAZIONE = "amministrazione"
# Nessun token riconosciuto: il permesso non si sa cosa faccia. Lo concede solo
# il livello piu' alto, ed e' dichiarato in pagina invece di essere indovinato.
CAPABILITY_IGNOTO = "ignoto"

CAPABILITY_LABELS = {
    CAPABILITY_LETTURA: "Lettura",
    CAPABILITY_MODIFICA: "Modifica",
    CAPABILITY_APPROVAZIONE: "Approvazione",
    CAPABILITY_AMMINISTRAZIONE: "Amministrazione",
    CAPABILITY_IGNOTO: "Non classificato",
}
CAPABILITY_ORDER = [
    CAPABILITY_LETTURA,
    CAPABILITY_MODIFICA,
    CAPABILITY_APPROVAZIONE,
    CAPABILITY_AMMINISTRAZIONE,
    CAPABILITY_IGNOTO,
]

# Quando in un nome convivono piu' segnali (``assets_bulk_update``) vince il
# piu' alto: concedere di meno e' un fastidio, concedere di piu' e' un incidente.
_CAPABILITY_RANK = {
    CAPABILITY_LETTURA: 1,
    CAPABILITY_MODIFICA: 2,
    CAPABILITY_APPROVAZIONE: 3,
    CAPABILITY_AMMINISTRAZIONE: 4,
}

# Azione canonica -> capacita'. Sono le nove azioni in cui `bootstrap_acl_v2`
# normalizza i code nuovi. `export` sta con la lettura (porta fuori cio' che si
# puo' gia' vedere); `run` e `import` stanno con la modifica perche' cambiano lo
# stato del modulo; `manage` e' amministrazione.
_CAPABILITY_BY_ACTION = {
    "view": CAPABILITY_LETTURA,
    "export": CAPABILITY_LETTURA,
    "create": CAPABILITY_MODIFICA,
    "edit": CAPABILITY_MODIFICA,
    "delete": CAPABILITY_MODIFICA,
    "import": CAPABILITY_MODIFICA,
    "run": CAPABILITY_MODIFICA,
    "approve": CAPABILITY_APPROVAZIONE,
    "manage": CAPABILITY_AMMINISTRAZIONE,
}

# Token (in italiano e in inglese) riconosciuti dentro il nome della view per i
# code legacy. Ricalca `_ACTION_ALIASES` di `bootstrap_acl_v2` e vi aggiunge il
# vocabolario che compare davvero nel catalogo del portale.
_CAPABILITY_BY_TOKEN = {
    # ── lettura: guardare, cercare, portare fuori cio' che si vede gia'
    "view": CAPABILITY_LETTURA,
    "vedi": CAPABILITY_LETTURA,
    "list": CAPABILITY_LETTURA,
    "lista": CAPABILITY_LETTURA,
    "elenco": CAPABILITY_LETTURA,
    "index": CAPABILITY_LETTURA,
    "home": CAPABILITY_LETTURA,
    "menu": CAPABILITY_LETTURA,
    "dashboard": CAPABILITY_LETTURA,
    "cruscotto": CAPABILITY_LETTURA,
    "detail": CAPABILITY_LETTURA,
    "dettaglio": CAPABILITY_LETTURA,
    "scheda": CAPABILITY_LETTURA,
    "storico": CAPABILITY_LETTURA,
    "calendario": CAPABILITY_LETTURA,
    "calendar": CAPABILITY_LETTURA,
    "map": CAPABILITY_LETTURA,
    "mappa": CAPABILITY_LETTURA,
    "statistiche": CAPABILITY_LETTURA,
    "statistics": CAPABILITY_LETTURA,
    "report": CAPABILITY_LETTURA,
    "reports": CAPABILITY_LETTURA,
    "export": CAPABILITY_LETTURA,
    "esporta": CAPABILITY_LETTURA,
    "download": CAPABILITY_LETTURA,
    "scarica": CAPABILITY_LETTURA,
    "csv": CAPABILITY_LETTURA,
    "pdf": CAPABILITY_LETTURA,
    "xlsx": CAPABILITY_LETTURA,
    "excel": CAPABILITY_LETTURA,
    "stampa": CAPABILITY_LETTURA,
    "print": CAPABILITY_LETTURA,
    "labels": CAPABILITY_LETTURA,
    "etichette": CAPABILITY_LETTURA,
    "colors": CAPABILITY_LETTURA,
    "search": CAPABILITY_LETTURA,
    "cerca": CAPABILITY_LETTURA,
    "lookup": CAPABILITY_LETTURA,
    "preview": CAPABILITY_LETTURA,
    "anteprima": CAPABILITY_LETTURA,
    "schedule": CAPABILITY_LETTURA,
    "scadenzario": CAPABILITY_LETTURA,
    "giacenze": CAPABILITY_LETTURA,
    # ── modifica: tutto cio' che scrive, anche quando si chiama "salva"
    "create": CAPABILITY_MODIFICA,
    "crea": CAPABILITY_MODIFICA,
    "new": CAPABILITY_MODIFICA,
    "nuovo": CAPABILITY_MODIFICA,
    "nuova": CAPABILITY_MODIFICA,
    "add": CAPABILITY_MODIFICA,
    "aggiungi": CAPABILITY_MODIFICA,
    "edit": CAPABILITY_MODIFICA,
    "modifica": CAPABILITY_MODIFICA,
    "update": CAPABILITY_MODIFICA,
    "aggiorna": CAPABILITY_MODIFICA,
    "save": CAPABILITY_MODIFICA,
    "salva": CAPABILITY_MODIFICA,
    "set": CAPABILITY_MODIFICA,
    "toggle": CAPABILITY_MODIFICA,
    "delete": CAPABILITY_MODIFICA,
    "elimina": CAPABILITY_MODIFICA,
    "remove": CAPABILITY_MODIFICA,
    "rimuovi": CAPABILITY_MODIFICA,
    "annulla": CAPABILITY_MODIFICA,
    "cancel": CAPABILITY_MODIFICA,
    "close": CAPABILITY_MODIFICA,
    "chiudi": CAPABILITY_MODIFICA,
    "chiusura": CAPABILITY_MODIFICA,
    "confirm": CAPABILITY_MODIFICA,
    "conferma": CAPABILITY_MODIFICA,
    "comment": CAPABILITY_MODIFICA,
    "commento": CAPABILITY_MODIFICA,
    "nota": CAPABILITY_MODIFICA,
    "note": CAPABILITY_MODIFICA,
    "import": CAPABILITY_MODIFICA,
    "importa": CAPABILITY_MODIFICA,
    "upload": CAPABILITY_MODIFICA,
    "carica": CAPABILITY_MODIFICA,
    "allegato": CAPABILITY_MODIFICA,
    "allegati": CAPABILITY_MODIFICA,
    "documento": CAPABILITY_MODIFICA,
    "sync": CAPABILITY_MODIFICA,
    "push": CAPABILITY_MODIFICA,
    "pull": CAPABILITY_MODIFICA,
    "refresh": CAPABILITY_MODIFICA,
    "reset": CAPABILITY_MODIFICA,
    "retry": CAPABILITY_MODIFICA,
    "run": CAPABILITY_MODIFICA,
    "esegui": CAPABILITY_MODIFICA,
    "registra": CAPABILITY_MODIFICA,
    "invia": CAPABILITY_MODIFICA,
    "send": CAPABILITY_MODIFICA,
    "genera": CAPABILITY_MODIFICA,
    "generate": CAPABILITY_MODIFICA,
    "link": CAPABILITY_MODIFICA,
    "collega": CAPABILITY_MODIFICA,
    "editor": CAPABILITY_MODIFICA,
    "queue": CAPABILITY_MODIFICA,
    "coda": CAPABILITY_MODIFICA,
    "sposta": CAPABILITY_MODIFICA,
    "move": CAPABILITY_MODIFICA,
    "duplica": CAPABILITY_MODIFICA,
    # ── approvazione: decidere sul lavoro di un altro
    "approve": CAPABILITY_APPROVAZIONE,
    "approva": CAPABILITY_APPROVAZIONE,
    "approvazione": CAPABILITY_APPROVAZIONE,
    "rifiuta": CAPABILITY_APPROVAZIONE,
    "reject": CAPABILITY_APPROVAZIONE,
    "valida": CAPABILITY_APPROVAZIONE,
    "validate": CAPABILITY_APPROVAZIONE,
    "firma": CAPABILITY_APPROVAZIONE,
    "consegna": CAPABILITY_APPROVAZIONE,
    "autorizza": CAPABILITY_APPROVAZIONE,
    # ── amministrazione: impostare il modulo, non usarlo
    "admin": CAPABILITY_AMMINISTRAZIONE,
    "amministrazione": CAPABILITY_AMMINISTRAZIONE,
    "gestione": CAPABILITY_AMMINISTRAZIONE,
    "manage": CAPABILITY_AMMINISTRAZIONE,
    "config": CAPABILITY_AMMINISTRAZIONE,
    "configurazione": CAPABILITY_AMMINISTRAZIONE,
    "impostazioni": CAPABILITY_AMMINISTRAZIONE,
    "settings": CAPABILITY_AMMINISTRAZIONE,
    "setup": CAPABILITY_AMMINISTRAZIONE,
    "wizard": CAPABILITY_AMMINISTRAZIONE,
    "bulk": CAPABILITY_AMMINISTRAZIONE,
    "massiva": CAPABILITY_AMMINISTRAZIONE,
    "assign": CAPABILITY_AMMINISTRAZIONE,
    "assegna": CAPABILITY_AMMINISTRAZIONE,
    "pannello": CAPABILITY_AMMINISTRAZIONE,
    "diagnostica": CAPABILITY_AMMINISTRAZIONE,
}

# Sostantivi: dicono su *cosa* si agisce, non cosa si fa. Contano solo quando
# nel nome non c'e' nessun verbo, altrimenti "cerca utenti" diventerebbe
# amministrazione per via di "utenti" pur essendo una ricerca.
_CAPABILITY_BY_ENTITY = {
    "utenti": CAPABILITY_AMMINISTRAZIONE,
    "users": CAPABILITY_AMMINISTRAZIONE,
    "ruoli": CAPABILITY_AMMINISTRAZIONE,
    "roles": CAPABILITY_AMMINISTRAZIONE,
    "permessi": CAPABILITY_AMMINISTRAZIONE,
    "permissions": CAPABILITY_AMMINISTRAZIONE,
    "gruppi": CAPABILITY_AMMINISTRAZIONE,
    "groups": CAPABILITY_AMMINISTRAZIONE,
    "catalogo": CAPABILITY_AMMINISTRAZIONE,
    "catalog": CAPABILITY_AMMINISTRAZIONE,
    "rule": CAPABILITY_AMMINISTRAZIONE,
    "rules": CAPABILITY_AMMINISTRAZIONE,
    "regole": CAPABILITY_AMMINISTRAZIONE,
    "regola": CAPABILITY_AMMINISTRAZIONE,
    "template": CAPABILITY_AMMINISTRAZIONE,
    "templates": CAPABILITY_AMMINISTRAZIONE,
    "overrides": CAPABILITY_AMMINISTRAZIONE,
    "override": CAPABILITY_AMMINISTRAZIONE,
    "widget": CAPABILITY_AMMINISTRAZIONE,
    "layout": CAPABILITY_AMMINISTRAZIONE,
    "database": CAPABILITY_AMMINISTRAZIONE,
}


def _capability_from_tokens(tokens) -> str:
    """Capacita' di una lista di token: prima i verbi, poi i sostantivi.

    Il verbo dice cosa si fa e vince sempre: ``api_cerca_utenti`` e' una
    ricerca, non amministrazione, anche se nomina gli utenti. Quando di verbi
    non ce ne sono (``assets_maintenance_rules``) decide il sostantivo.
    """
    verbs = [_CAPABILITY_BY_TOKEN[token] for token in tokens if token in _CAPABILITY_BY_TOKEN]
    if verbs:
        return max(verbs, key=lambda capability: _CAPABILITY_RANK[capability])
    nouns = [_CAPABILITY_BY_ENTITY[token] for token in tokens if token in _CAPABILITY_BY_ENTITY]
    if nouns:
        return max(nouns, key=lambda capability: _CAPABILITY_RANK[capability])
    return CAPABILITY_IGNOTO


# Decisioni prese a mano, leggendo per ognuna la rotta che governa davvero
# (`RoutePermissionBinding`) e l'etichetta del pulsante legacy. Sono i code del
# catalogo reale che nessuna regola automatica riesce a leggere: nomi di pagina
# senza verbo (`rentri_carico`, `pr_campaigns`) o verbi solo italiani.
# Verificate sul catalogo di dev del 17/09/2026 (847 permessi).
#
# Quello che resta fuori da questa tabella resta `ignoto` di proposito: preferire
# "non lo so" a un'ipotesi e' il senso di tutto il modulo. Tre casi noti e
# lasciati apposta: `legacy.dashboard.onboarding` (wizard di primo accesso, non
# si sa se scriva), `legacy.notizie.notizie_obbligatorie` (pagina di lettura per
# il dipendente o pannello di chi le impone?), `legacy.tickets.tickets` (nessun
# binding attivo, non governa nulla).
_CAPABILITY_OVERRIDES = {
    # ─ lettura: elenchi e API di sola consultazione, le cui scritture hanno
    #   un permesso proprio (`assets_components_new`, `anomalie_api_salva`, ...)
    "anagrafica.export.use": CAPABILITY_LETTURA,
    "legacy.anagrafica.anagrafica_dipendenti": CAPABILITY_LETTURA,
    "legacy.anagrafica.anagrafica_fornitori": CAPABILITY_LETTURA,
    "legacy.anomalie.anomalie_api_anomalie": CAPABILITY_LETTURA,
    "legacy.anomalie.anomalie_api_campi": CAPABILITY_LETTURA,
    "legacy.anomalie.anomalie_api_ordini": CAPABILITY_LETTURA,
    "legacy.assets.assets_components": CAPABILITY_LETTURA,
    "legacy.assets.assets_deadlines": CAPABILITY_LETTURA,
    "legacy.assets.assets_verifiche": CAPABILITY_LETTURA,
    "legacy.assets.assets_work_machines": CAPABILITY_LETTURA,
    "legacy.assets.assets_workorders": CAPABILITY_LETTURA,
    "legacy.tickets.tickets_api_asset": CAPABILITY_LETTURA,
    "legacy.tickets.tickets_api_assets_autocomplete": CAPABILITY_LETTURA,
    # ─ modifica: pagine che esistono per registrare qualcosa
    "legacy.assenze.richiesta_assenze": CAPABILITY_MODIFICA,
    "legacy.assets.assets_assistance_contracts": CAPABILITY_MODIFICA,
    "legacy.diario_preposto.diario_preposto": CAPABILITY_MODIFICA,
    "legacy.fornitori.fornitore_ordine_stato": CAPABILITY_MODIFICA,
    "legacy.rentri.rentri_carico": CAPABILITY_MODIFICA,
    "legacy.rentri.rentri_rettifica": CAPABILITY_MODIFICA,
    "legacy.rentri.rentri_scarico_eff": CAPABILITY_MODIFICA,
    "legacy.rentri.rentri_scarico_orig": CAPABILITY_MODIFICA,
    "legacy.sicurezza.segnalazioni_incidenti": CAPABILITY_MODIFICA,
    "legacy.tickets.tickets_api_stato": CAPABILITY_MODIFICA,
    "gestione_specifiche.mod133.compila": CAPABILITY_MODIFICA,
    "gestione_specifiche.specifica.claim": CAPABILITY_MODIFICA,
    "gestione_specifiche.specifica.sospendi": CAPABILITY_MODIFICA,
    "gestione_specifiche.distribuzione.distribuisci": CAPABILITY_MODIFICA,
    "schede_sicurezza.prodotto.gestisci": CAPABILITY_MODIFICA,
    # Copre anche `tasks:project_vrf_upload` e `project_vrf_compile`: scrive.
    "tasks.kickoff.projects": CAPABILITY_MODIFICA,
    # ─ approvazione: derogare a una regola e' una decisione, non una modifica
    "gestione_specifiche.distribuzione.deroga": CAPABILITY_APPROVAZIONE,
    # ─ amministrazione: cataloghi, pannelli /admin/, diagnostica
    "legacy.anagrafica.anagrafica_mansioni": CAPABILITY_AMMINISTRAZIONE,
    "legacy.anagrafica.anagrafica_qualifiche": CAPABILITY_AMMINISTRAZIONE,
    "legacy.automazioni.automazioni_contenuti": CAPABILITY_AMMINISTRAZIONE,
    "legacy.automazioni.automazioni_sorgenti": CAPABILITY_AMMINISTRAZIONE,
    "legacy.portale_esterno.portale_esterno": CAPABILITY_AMMINISTRAZIONE,
    "legacy.procedure_refresh.pr_campaigns": CAPABILITY_AMMINISTRAZIONE,
    "legacy.procedure_refresh.pr_documents": CAPABILITY_AMMINISTRAZIONE,
    "legacy.tickets.tickets_api_test_sp": CAPABILITY_AMMINISTRAZIONE,
}


def capability_for_code(code: str, module: str = "") -> str:
    """Cosa consente di fare il permesso, o ``ignoto`` se non si sa.

    Tre passaggi, dal piu' affidabile al piu' incerto:

    0. decisione esplicita in ``_CAPABILITY_OVERRIDES``, presa leggendo la
       rotta che il permesso governa davvero;
    1. natura *configurazione* -> amministrazione (anche per un semplice `view`
       su permessi, ruoli, utenti: leggere chi puo' cosa e' amministrare);
    2. azione canonica finale, quella normalizzata da ``bootstrap_acl_v2``;
    3. token riconosciuti nel nome della view, per i code legacy
       (``legacy.assets.asset_create`` -> modifica). Fra piu' token vince il
       piu' alto.

    Se nessun passaggio dice qualcosa si risponde ``ignoto``: **non** "lettura".
    Un permesso che non si sa cosa faccia non deve finire dentro "Solo lettura".
    """
    normalized = str(code or "").strip().lower()
    if normalized in _CAPABILITY_OVERRIDES:
        return _CAPABILITY_OVERRIDES[normalized]
    if nature_for_code(code, module) == NATURE_CONFIG:
        return CAPABILITY_AMMINISTRAZIONE
    action = action_for_code(code)
    direct = _CAPABILITY_BY_ACTION.get(action)
    if direct:
        return direct
    return _capability_from_tokens(action.split("_"))


def capability_for_name(name: str) -> str:
    """Capacita' ricavata da un nome libero (route name, url name, nome view).

    Serve per leggere le rotte che un permesso governa *di fatto* quando il suo
    binding e' un prefisso di URL: ``assets:asset_component_create`` dice
    "modifica" anche se il permesso che lo copre si chiama ``assets_components``.
    Stesso vocabolario dei code, nessuna seconda tabella da tenere allineata.
    """
    tokens = [
        token
        for chunk in str(name or "").lower().replace(":", "_").replace(".", "_").replace("-", "_").split("_")
        for token in [chunk.strip()]
        if token
    ]
    return _capability_from_tokens(tokens)


def strongest_capability(capabilities) -> str:
    """La piu' alta fra quelle note; ``ignoto`` se non ce n'e' nessuna nota.

    L'incertezza non si mescola: un permesso che non si sa leggere resta
    ``ignoto`` anche se qualcosa attorno a lui e' chiaro (lo decide il
    chiamante), mentre fra capacita' note vince sempre la piu' alta.
    """
    known = [c for c in capabilities if c in _CAPABILITY_RANK]
    if not known:
        return CAPABILITY_IGNOTO
    return max(known, key=lambda capability: _CAPABILITY_RANK[capability])


def capability_label(capability: str) -> str:
    return CAPABILITY_LABELS.get(capability, CAPABILITY_LABELS[CAPABILITY_IGNOTO])


# I livelli sono cumulativi e si leggono dall'alto in basso come una scala.
# `capabilities` vuoto = il livello spegne tutto. Solo l'ultimo livello prende i
# permessi non classificati: sotto, l'incertezza non concede.
#
# Non esiste un livello "solo i propri record": ACL v2 decide allow/deny sulla
# rotta e lo scope per record e' codice dentro le singole view. Un livello che
# lo promettesse mentirebbe (vedi la proposta RBAC in docs/).
ACCESS_LEVELS = [
    {
        "key": "nessuno",
        "label": "Nessun accesso",
        "description": "Spegne tutti i permessi del modulo.",
        "capabilities": frozenset(),
    },
    {
        "key": "lettura",
        "label": "Solo lettura",
        "description": "Consulta ed esporta, non scrive nulla.",
        "capabilities": frozenset({CAPABILITY_LETTURA}),
    },
    {
        "key": "modifica",
        "label": "Lettura e modifica",
        "description": "Consulta, crea, modifica, elimina e importa. Niente approvazioni.",
        "capabilities": frozenset({CAPABILITY_LETTURA, CAPABILITY_MODIFICA}),
    },
    {
        "key": "operativo",
        "label": "Operativo completo",
        "description": "Tutto l'uso quotidiano, approvazioni comprese. Niente impostazioni.",
        "capabilities": frozenset(
            {CAPABILITY_LETTURA, CAPABILITY_MODIFICA, CAPABILITY_APPROVAZIONE}
        ),
    },
    {
        "key": "amministrazione",
        "label": "Amministratore del modulo",
        "description": "Tutto: impostazioni, configurazione e i permessi non classificati.",
        "capabilities": frozenset(CAPABILITY_ORDER),
    },
]

ACCESS_LEVELS_BY_KEY = {level["key"]: level for level in ACCESS_LEVELS}


def capabilities_for_level(level_key: str) -> frozenset:
    """Capacita' accese da un livello. Livello ignoto -> nessuna (non concede)."""
    level = ACCESS_LEVELS_BY_KEY.get(str(level_key or "").strip().lower())
    return level["capabilities"] if level else frozenset()


def level_grants_code(level_key: str, code: str, module: str = "") -> bool:
    """Il livello accende questo permesso?"""
    return capability_for_code(code, module) in capabilities_for_level(level_key)
