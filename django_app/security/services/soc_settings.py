"""Impostazioni operative del SOC (avvisi automatici, report programmato, soglie).

Un solo elenco descrive ogni impostazione: chiave, default, etichetta, spiegazione. La
pagina `/soc/impostazioni/` lo usa per disegnare il modulo e i servizi lo usano per
leggere i valori, così pagina e comportamento non possono divergere. I valori stanno in
``SecurityCenterSetting`` (categoria ``avvisi``): nessuna migrazione, audit già incluso.

Tutti gli avvisi nascono **spenti**: in produzione nessuno riceve mail finché qualcuno non
li accende e sceglie a quali canali mandarli.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from security.services.configuration import get_setting, set_setting

CATEGORY = "avvisi"


@dataclass(frozen=True)
class Option:
    key: str
    default: object
    label: str
    help: str = ""
    kind: str = "bool"  # bool | int | choice | channels
    choices: tuple = field(default_factory=tuple)
    min_value: int = 0
    max_value: int = 0


SECTIONS = [
    {
        "code": "incidenti",
        "title": "Scadenze incidenti NIS2 e GDPR",
        "intro": "Un avviso quando una notifica al CSIRT o al Garante sta per scadere e uno quando è scaduta. Ogni avviso parte una volta sola.",
        "options": [
            Option("avvisi.incidenti.attivo", False, "Avvisa sulle scadenze degli incidenti"),
            Option("avvisi.incidenti.anticipo_ore", 6, "Anticipo", "Ore prima della scadenza in cui parte il primo avviso.", "int", min_value=1, max_value=48),
            Option("avvisi.incidenti.canali", [], "Canali", "Dove mandare gli avvisi.", "channels"),
        ],
    },
    {
        "code": "backup",
        "title": "Backup dei PC e dei server",
        "intro": "Un avviso per ogni PC che resta senza backup riuscito oltre la soglia o il cui ultimo backup è fallito. Riparte solo dopo un nuovo backup riuscito.",
        "options": [
            Option("avvisi.backup.attivo", False, "Avvisa sui backup dei PC"),
            Option("avvisi.backup.giorni", 3, "Soglia", "Giorni senza backup riuscito dopo cui un PC va guardato (vale anche per la pagina Backup).", "int", min_value=1, max_value=30),
            Option("avvisi.backup.fallito", True, "Avvisa anche quando l'ultimo backup è fallito", "Senza aspettare la soglia."),
            Option("avvisi.backup.canali", [], "Canali", "Dove mandare gli avvisi.", "channels"),
        ],
    },
    {
        "code": "report",
        "title": "Report periodico automatico",
        "intro": "Il report del SOC inviato da solo ai canali scelti: via mail con il PDF allegato, su Teams con il riassunto e il link.",
        "options": [
            Option("report.auto.attivo", False, "Invia il report da solo"),
            Option("report.auto.frequenza", "weekly", "Frequenza", "Settimanale: il lunedì, sulla settimana prima. Mensile: il giorno 1, sul mese prima.", "choice",
                   choices=(("weekly", "Settimanale (lunedì)"), ("monthly", "Mensile (giorno 1)"))),
            Option("report.auto.canali", [], "Canali", "Dove mandare il report.", "channels"),
        ],
    },
]

OPTIONS = {option.key: option for section in SECTIONS for option in section["options"]}


def value(key):
    option = OPTIONS[key]
    raw = get_setting(key, option.default)
    if option.kind == "bool":
        return bool(raw)
    if option.kind == "int":
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return option.default
        return max(option.min_value, min(option.max_value, number)) if option.max_value else number
    if option.kind == "channels":
        return [int(x) for x in raw if str(x).isdigit()] if isinstance(raw, list) else []
    if option.kind == "choice":
        return raw if raw in dict(option.choices) else option.default
    return raw


def backup_stale_days():
    return value("avvisi.backup.giorni")


def parse_post(data):
    """Valori puliti dal POST del modulo, con l'elenco degli errori (``(valori, errori)``)."""
    from security.models import SecurityNotificationChannel

    valid_channels = set(SecurityNotificationChannel.objects.values_list("pk", flat=True))
    values, errors = {}, []
    for key, option in OPTIONS.items():
        field_name = key.replace(".", "__")
        if option.kind == "bool":
            values[key] = data.get(field_name) == "on"
        elif option.kind == "int":
            raw = str(data.get(field_name, "")).strip()
            if not raw.isdigit() or not option.min_value <= int(raw) <= option.max_value:
                errors.append(f"{option.label}: un numero da {option.min_value} a {option.max_value}.")
                continue
            values[key] = int(raw)
        elif option.kind == "choice":
            raw = data.get(field_name, "")
            if raw not in dict(option.choices):
                errors.append(f"{option.label}: scelta non valida.")
                continue
            values[key] = raw
        elif option.kind == "channels":
            values[key] = sorted({int(x) for x in data.getlist(field_name) if str(x).isdigit() and int(x) in valid_channels})
    for section in SECTIONS:
        active = next((o.key for o in section["options"] if o.kind == "bool"), None)
        channels = next((o.key for o in section["options"] if o.kind == "channels"), None)
        if active and channels and values.get(active) and not values.get(channels):
            errors.append(f"{section['title']}: per accenderli scegli almeno un canale.")
    return values, errors


def save(values, actor):
    """Salva solo ciò che è cambiato (ogni modifica finisce nell'audit della configurazione)."""
    changed = 0
    for key, new in values.items():
        if value(key) != new:
            set_setting(key, new, actor=actor, category=CATEGORY, description=OPTIONS[key].label)
            changed += 1
    return changed


def form_sections():
    """Sezioni con i valori correnti, pronte per il template."""
    out = []
    for section in SECTIONS:
        out.append({
            **section,
            "fields": [
                {"option": option, "name": option.key.replace(".", "__"), "value": value(option.key)}
                for option in section["options"]
            ],
            "active": value(next(o.key for o in section["options"] if o.kind == "bool")),
        })
    return out
