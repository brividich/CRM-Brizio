"""Registro di presentazione dei tipi di notifica in-app.

Mappa ogni ``tipo`` (vedi ``core.models.Notifica``) a **etichetta**, **icona**
(emoji) e **tono** (chiave colore usata dai template) così la UI mostra icona +
etichetta coerenti invece del codice grezzo o di un generico "Generico".

Registro Python (niente migration): fonte unica per il centro notifiche, il
banner, la pagina ``/notifiche/`` e l'export CSV. I ``tipo`` sconosciuti ripiegano
su un default pulito.
"""
from __future__ import annotations

# tono ∈ {ok, warn, danger, info}  →  i template mappano il tono a un colore.
TIPO_META: dict[str, dict[str, str]] = {
    "assenza_approvata":    {"label": "Assenza approvata",      "icona": "✅", "tono": "ok"},
    "assenza_rifiutata":    {"label": "Assenza rifiutata",      "icona": "⛔", "tono": "danger"},
    "assenza_in_attesa":    {"label": "Assenza da approvare",   "icona": "⏳", "tono": "warn"},
    "anomalia_segnalata":   {"label": "Anomalia segnalata",     "icona": "⚠️", "tono": "warn"},
    "anomalia_chiusa":      {"label": "Anomalia chiusa",        "icona": "✅", "tono": "ok"},
    "anomalia_da_gestire":  {"label": "Anomalia da gestire",    "icona": "🔧", "tono": "warn"},
    "dpi_approvata":        {"label": "DPI approvata",          "icona": "🦺", "tono": "ok"},
    "dpi_rifiutata":        {"label": "DPI rifiutata",          "icona": "🦺", "tono": "danger"},
    "dpi_consegnata":       {"label": "DPI consegnata",         "icona": "🦺", "tono": "ok"},
    "dpi_scadenza":         {"label": "DPI in scadenza",        "icona": "🦺", "tono": "warn"},
    "ticket_sla":           {"label": "SLA ticket scaduto",     "icona": "🎫", "tono": "danger"},
    "asset_scadenza":       {"label": "Scadenza asset",         "icona": "🔧", "tono": "warn"},
    "formazione_promemoria": {"label": "Promemoria formazione", "icona": "🎓", "tono": "info"},
    "visita_scadenza":      {"label": "Visita medica",          "icona": "🩺", "tono": "warn"},
    "presa_visione":        {"label": "Presa visione",          "icona": "📄", "tono": "info"},
    "task":                 {"label": "Attività",               "icona": "🗒️", "tono": "info"},
    "capa":                 {"label": "Azione CAPA",            "icona": "🛠️", "tono": "info"},
    "specifica":            {"label": "Specifica",              "icona": "📐", "tono": "info"},
    "generico":             {"label": "Notifica",               "icona": "🔔", "tono": "info"},
}

_DEFAULT: dict[str, str] = {"label": "Notifica", "icona": "🔔", "tono": "info"}


def notifica_meta(tipo: str | None) -> dict[str, str]:
    """Metadati di presentazione (label/icona/tono) per il ``tipo`` dato.

    Ripiega sul default per i tipi non registrati (mai KeyError)."""
    return TIPO_META.get((tipo or "").strip(), _DEFAULT)
