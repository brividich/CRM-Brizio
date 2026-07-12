from django import template


register = template.Library()


LABELS = {
    "acknowledged": "Preso in carico",
    "closed": "Chiuso",
    "critical": "Critico",
    "disabled": "Disattivato",
    "error": "Errore",
    "failed": "Fallito",
    "false_positive": "Falso positivo",
    "high": "Alto",
    "info": "Info",
    "in_progress": "In lavorazione",
    "low": "Basso",
    "medium": "Medio",
    "misconfigured": "Configurazione errata",
    "muted": "Silenziato",
    "new": "Nuovo",
    "ok": "OK",
    "open": "Aperto",
    "parsed": "Analizzato",
    "pending": "In attesa",
    "resolved": "Risolto",
    "skipped": "Saltato",
    "snoozed": "Posticipato",
    "suppressed": "Soppresso",
    "warning": "Attenzione",
}


CANONICAL_LABELS = {
    "acknowledged": "Acknowledged",
    "closed": "Closed",
    "false_positive": "False positive",
    "in_progress": "In progress",
    "muted": "Muted",
    "new": "New",
    "open": "Open",
    "resolved": "Resolved",
    "snoozed": "Snoozed",
    "suppressed": "Suppressed",
}


@register.filter
def ui_label(value):
    if value is None:
        return "-"
    text = str(value)
    return LABELS.get(text.lower(), text)


@register.filter
def canonical_status_label(value):
    if value is None:
        return "-"
    text = str(value)
    return CANONICAL_LABELS.get(text.lower(), text)


@register.filter
def si_no(value):
    return "Si" if value else "No"
