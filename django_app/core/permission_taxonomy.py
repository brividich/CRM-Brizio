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
