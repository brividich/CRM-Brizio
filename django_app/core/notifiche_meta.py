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
    "sicurezza": "Sicurezza dell'account",
}

# Moduli: come la pagina Notifiche raggruppa e filtra i tipi.
MODULI: dict[str, str] = {
    "assenze": "Assenze e presenze",
    "dpi": "DPI",
    "ticket": "Ticket",
    "anomalie": "Anomalie e qualità",
    "reception": "Reception e fornitori",
    "kickoff": "KICK-OFF e attività",
    "specifiche": "Specifiche",
    "scadenze": "Scadenze, asset e formazione",
    "ambiente": "Rifiuti (RENTRI)",
    "it": "IT e sicurezza",
    "altro": "Altro",
}


def _t(label: str, icona: str, tono: str, categoria: str, modulo: str) -> dict[str, str]:
    return {"label": label, "icona": icona, "tono": tono, "categoria": categoria, "modulo": modulo}


# tono ∈ {ok, warn, danger, info}  →  i template mappano il tono a un colore.
# categoria ∈ CATEGORIE  →  usata per l'enforcement (vedi core.notifiche_prefs).
# modulo ∈ MODULI  →  filtro «Modulo» della pagina Notifiche.
TIPO_META: dict[str, dict[str, str]] = {
    # Assenze e presenze
    "assenza_approvata":     _t("Assenza approvata", "✅", "ok", "assenze", "assenze"),
    "assenza_rifiutata":     _t("Assenza rifiutata", "⛔", "danger", "assenze", "assenze"),
    "assenza_in_attesa":     _t("Assenza da approvare", "⏳", "warn", "assenze", "assenze"),
    "assenza_modificata":    _t("Assenza modificata", "✏️", "info", "assenze", "assenze"),
    "assenza_cancellata":    _t("Assenza cancellata", "🗑️", "warn", "assenze", "assenze"),
    "assenze_avviso":        _t("Assenze", "🗓️", "info", "assenze", "assenze"),
    "presenze_uscita":       _t("Uscita non timbrata", "🕘", "warn", "assenze", "assenze"),
    # Anomalie e qualità
    "anomalia_segnalata":    _t("Anomalia segnalata", "⚠️", "warn", "operativita", "anomalie"),
    "anomalia_chiusa":       _t("Anomalia chiusa", "✅", "ok", "operativita", "anomalie"),
    "anomalia_da_gestire":   _t("Anomalia da gestire", "🔧", "warn", "operativita", "anomalie"),
    "anomalia_rdc_mancante": _t("RDC da aprire", "📝", "warn", "operativita", "anomalie"),
    "anomalia_nc_azione":    _t("Azione NC in scadenza", "📋", "warn", "operativita", "anomalie"),
    "capa":                  _t("Azione CAPA", "🛠️", "info", "operativita", "anomalie"),
    # DPI
    "dpi_da_approvare":      _t("DPI da approvare", "🦺", "warn", "scadenzari", "dpi"),
    "dpi_approvata":         _t("DPI approvata", "🦺", "ok", "scadenzari", "dpi"),
    "dpi_rifiutata":         _t("DPI rifiutata", "🦺", "danger", "scadenzari", "dpi"),
    "dpi_pronta":            _t("DPI pronta da ritirare", "🦺", "ok", "scadenzari", "dpi"),
    "dpi_ordinata":          _t("DPI ordinata", "🦺", "info", "scadenzari", "dpi"),
    "dpi_consegnata":        _t("DPI consegnata", "🦺", "ok", "scadenzari", "dpi"),
    "dpi_annullata":         _t("DPI annullata", "🦺", "info", "scadenzari", "dpi"),
    "dpi_commento":          _t("Commento sulla DPI", "💬", "info", "scadenzari", "dpi"),
    "dpi_scadenza":          _t("DPI in scadenza", "🦺", "warn", "scadenzari", "dpi"),
    # Ticket
    "ticket_nuovo":          _t("Ticket nuovo", "🎫", "warn", "ticket", "ticket"),
    "ticket_aperto":         _t("Ticket aperto", "🎫", "info", "ticket", "ticket"),
    "ticket_assegnato":      _t("Ticket assegnato a te", "🎫", "warn", "ticket", "ticket"),
    "ticket_preso":          _t("Ticket preso in carico", "🎫", "ok", "ticket", "ticket"),
    "ticket_stato":          _t("Ticket aggiornato", "🎫", "info", "ticket", "ticket"),
    "ticket_risolto":        _t("Ticket risolto: confermi?", "✅", "warn", "ticket", "ticket"),
    "ticket_commento":       _t("Nuovo commento sul ticket", "💬", "info", "ticket", "ticket"),
    "ticket_riaperto":       _t("Ticket riaperto", "🔁", "warn", "ticket", "ticket"),
    "ticket_annullato":      _t("Ticket annullato", "⛔", "info", "ticket", "ticket"),
    "ticket_allegato":       _t("Allegato da controllare", "📎", "warn", "ticket", "ticket"),
    "ticket_allegato_rifiutato": _t("Allegato rifiutato", "📎", "danger", "ticket", "ticket"),
    "ticket_sla":            _t("SLA ticket scaduto", "🎫", "danger", "ticket", "ticket"),
    "ticket_avviso":         _t("Ticket", "🎫", "info", "ticket", "ticket"),
    # Reception e fornitori
    "reception_richiesta":   _t("Richiesta di appuntamento", "🛎️", "warn", "operativita", "reception"),
    "reception_decisa":      _t("Richiesta decisa dalla reception", "🛎️", "info", "operativita", "reception"),
    "fornitore_accesso":     _t("Accesso fornitore", "🚚", "warn", "operativita", "reception"),
    # KICK-OFF e attività
    "task":                  _t("Attività", "🗒️", "info", "operativita", "kickoff"),
    "kickoff_incontro":      _t("Incontro KICK-OFF", "🤝", "info", "operativita", "kickoff"),
    "kickoff_spostamento":   _t("Spostamento date", "📅", "info", "operativita", "kickoff"),
    "promemoria":            _t("Promemoria", "⏰", "info", "operativita", "kickoff"),
    "sc_assegnazione":       _t("Suggestion Corner", "💡", "info", "operativita", "kickoff"),
    "sc_esito":              _t("La tua segnalazione", "💡", "info", "operativita", "kickoff"),
    "checklist":             _t("Checklist operativa", "☑️", "warn", "operativita", "kickoff"),
    # Specifiche
    "specifica":             _t("Specifica", "📐", "info", "operativita", "specifiche"),
    # Scadenze, asset e formazione
    "asset_scadenza":        _t("Scadenza asset", "🔧", "warn", "scadenzari", "scadenze"),
    "formazione_promemoria": _t("Promemoria formazione", "🎓", "info", "scadenzari", "scadenze"),
    "scadenza_assegnata":    _t("Scadenza assegnata", "📅", "info", "scadenzari", "scadenze"),
    "scadenza_promemoria":   _t("Scadenza da gestire", "📅", "warn", "scadenzari", "scadenze"),
    "visita_scadenza":       _t("Visita medica", "🩺", "warn", "scadenzari", "scadenze"),
    "presa_visione":         _t("Presa visione", "📄", "info", "scadenzari", "scadenze"),
    # Rifiuti
    "rentri":                _t("Registro rifiuti", "♻️", "warn", "operativita", "ambiente"),
    # IT e sicurezza
    "it_ingresso":           _t("Nuovo ingresso: accessi IT", "💻", "info", "operativita", "it"),
    "it_monitoraggio":       _t("Monitoraggio IT", "🖥️", "warn", "operativita", "it"),
    "accesso_nuovo_dispositivo": _t("Accesso da un nuovo dispositivo", "🔐", "warn", "sicurezza", "it"),
    # Altro
    "rettifica_dati":        _t("Rettifica dei dati", "✏️", "info", "operativita", "altro"),
    "automazione":           _t("Automazioni", "⚙️", "info", "operativita", "altro"),
    "generico":              _t("Notifica", "🔔", "info", "operativita", "altro"),
}

_DEFAULT: dict[str, str] = {"label": "Notifica", "icona": "🔔", "tono": "info", "categoria": "operativita", "modulo": "altro"}


def notifica_meta(tipo: str | None) -> dict[str, str]:
    """Metadati di presentazione (label/icona/tono/categoria) per il ``tipo`` dato.

    Ripiega sul default per i tipi non registrati (mai KeyError)."""
    return TIPO_META.get((tipo or "").strip(), _DEFAULT)


def notifica_categoria(tipo: str | None) -> str:
    """Categoria di notifica per il ``tipo`` (default 'operativita')."""
    return notifica_meta(tipo).get("categoria", "operativita")


def tipi_del_modulo(modulo: str) -> list[str]:
    """Tipi registrati del ``modulo``. Per «altro» la vista aggiunge i tipi non registrati."""
    return [t for t, m in TIPO_META.items() if m.get("modulo") == modulo]
