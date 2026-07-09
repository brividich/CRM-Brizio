"""Registro di presentazione dei tipi di notifica in-app.

Mappa ogni ``tipo`` (vedi ``core.models.Notifica``) a **etichetta**, **icona**
(emoji) e **tono** (chiave colore usata dai template) così la UI mostra icona +
etichetta coerenti invece del codice grezzo o di un generico "Generico".

Registro Python (niente migration): fonte unica per il centro notifiche, il
banner, la pagina ``/notifiche/`` e l'export CSV. I ``tipo`` sconosciuti ripiegano
su un default pulito.
"""
from __future__ import annotations

# Categorie di notifica (allineate a _ONBOARDING_NOTIFICATION_SPECS + "operativita"):
# usate per accendere/spegnere le notifiche (admin globale + preferenza utente).
CATEGORIE: dict[str, str] = {
    "assenze": "Assenze e presenze",
    "comunicazioni": "Comunicazioni aziendali",
    "scadenzari": "Scadenzari e manutenzioni",
    "ticket": "Ticket e segnalazioni",
    "operativita": "Operatività (anomalie, task, CAPA, specifiche)",
}

# tono ∈ {ok, warn, danger, info}  →  i template mappano il tono a un colore.
# categoria ∈ CATEGORIE  →  usata per l'enforcement (vedi core.notifiche_prefs).
TIPO_META: dict[str, dict[str, str]] = {
    "assenza_approvata":    {"label": "Assenza approvata",      "icona": "✅", "tono": "ok",     "categoria": "assenze"},
    "assenza_rifiutata":    {"label": "Assenza rifiutata",      "icona": "⛔", "tono": "danger", "categoria": "assenze"},
    "assenza_in_attesa":    {"label": "Assenza da approvare",   "icona": "⏳", "tono": "warn",   "categoria": "assenze"},
    "anomalia_segnalata":   {"label": "Anomalia segnalata",     "icona": "⚠️", "tono": "warn",   "categoria": "operativita"},
    "anomalia_chiusa":      {"label": "Anomalia chiusa",        "icona": "✅", "tono": "ok",     "categoria": "operativita"},
    "anomalia_da_gestire":  {"label": "Anomalia da gestire",    "icona": "🔧", "tono": "warn",   "categoria": "operativita"},
    "dpi_approvata":        {"label": "DPI approvata",          "icona": "🦺", "tono": "ok",     "categoria": "scadenzari"},
    "dpi_rifiutata":        {"label": "DPI rifiutata",          "icona": "🦺", "tono": "danger", "categoria": "scadenzari"},
    "dpi_consegnata":       {"label": "DPI consegnata",         "icona": "🦺", "tono": "ok",     "categoria": "scadenzari"},
    "dpi_scadenza":         {"label": "DPI in scadenza",        "icona": "🦺", "tono": "warn",   "categoria": "scadenzari"},
    "ticket_sla":           {"label": "SLA ticket scaduto",     "icona": "🎫", "tono": "danger", "categoria": "ticket"},
    "asset_scadenza":       {"label": "Scadenza asset",         "icona": "🔧", "tono": "warn",   "categoria": "scadenzari"},
    "formazione_promemoria": {"label": "Promemoria formazione", "icona": "🎓", "tono": "info",   "categoria": "scadenzari"},
    "visita_scadenza":      {"label": "Visita medica",          "icona": "🩺", "tono": "warn",   "categoria": "scadenzari"},
    "presa_visione":        {"label": "Presa visione",          "icona": "📄", "tono": "info",   "categoria": "scadenzari"},
    "task":                 {"label": "Attività",               "icona": "🗒️", "tono": "info",   "categoria": "operativita"},
    "capa":                 {"label": "Azione CAPA",            "icona": "🛠️", "tono": "info",   "categoria": "operativita"},
    "specifica":            {"label": "Specifica",              "icona": "📐", "tono": "info",   "categoria": "operativita"},
    "sc_assegnazione":      {"label": "Suggestion Corner",      "icona": "💡", "tono": "info",   "categoria": "operativita"},
    "generico":             {"label": "Notifica",               "icona": "🔔", "tono": "info",   "categoria": "operativita"},
}

_DEFAULT: dict[str, str] = {"label": "Notifica", "icona": "🔔", "tono": "info", "categoria": "operativita"}


def notifica_meta(tipo: str | None) -> dict[str, str]:
    """Metadati di presentazione (label/icona/tono/categoria) per il ``tipo`` dato.

    Ripiega sul default per i tipi non registrati (mai KeyError)."""
    return TIPO_META.get((tipo or "").strip(), _DEFAULT)


def notifica_categoria(tipo: str | None) -> str:
    """Categoria di notifica per il ``tipo`` (default 'operativita')."""
    return notifica_meta(tipo).get("categoria", "operativita")
