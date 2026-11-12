"""Configurazione utente dei flussi mail schedulati (destinatari + testo).

Due livelli, entrambi editabili dalla scheda «Task pianificati» dell'area automazioni:

- **Destinatari**: restano su ``core.SiteConfig`` (una chiave per flusso), così i
  management command li leggono già senza modifiche (via ``get_reminder_recipients``).
  La UI legge/scrive la chiave indicata in ``MAIL_TASKS[task]['config_key']``.
- **Cornice testuale** (oggetto/intro/nota): su ``ScheduledMailText`` (per task).
  I comandi la applicano prima dell'invio con :func:`apply_mail_overrides`.

Solo i task elencati in ``MAIL_TASKS`` espongono destinatari e testo nel pannello «Modifica» (orario e info valgono per tutti).
"""
from __future__ import annotations

from html import escape

# task_name (schedule) → configurazione mail modificabile.
#   config_key: chiave SiteConfig dei destinatari (None se il flusso non usa un
#               elenco fisso — es. destinatari calcolati per dipendente/assegnatario).
MAIL_TASKS: dict[str, dict] = {
    "visite_expiry_reminders": {
        "config_key": "visite_reminder_emails",
        "label": "Reminder visite mediche in scadenza",
    },
    "contratti_expiry_reminders": {
        "config_key": "contratti_reminder_emails",
        "label": "Reminder contratti/prove in scadenza",
    },
    "idoneita_digest": {
        "config_key": "idoneita_reminder_emails",
        "label": "Digest idoneità alla mansione",
    },
    "cambio_mansione_digest": {
        "config_key": "cambio_mansione_emails",
        "label": "Cambio mansione: adempimenti e stato operativo",
    },
    "training_expiry_reminders": {
        "config_key": "training_reminder_emails",
        "label": "Reminder formazione obbligatoria in scadenza",
    },
    "elearning_reminders": {
        "config_key": "elearning_reminder_emails",
        "label": "Reminder micro-corsi e-learning",
    },
    "dpi_expiry_reminders": {
        "config_key": "dpi_reminder_emails",
        "label": "Reminder DPI in scadenza",
    },
    "assets_maintenance_reminders": {
        "config_key": "assets_reminder_emails",
        "label": "Reminder manutenzioni/verifiche assets",
    },
    # solo_destinatari: nessun ripiego su ADMINS/superuser, con la lista vuota la mail non parte.
    "contatori_letture_mensili": {
        "config_key": "contatori_letture_mensili_emails",
        "label": "Letture mensili MFC: riepilogo e mancanti",
        "solo_destinatari": True,
    },
}


def is_configurable(task_name: str) -> bool:
    return task_name in MAIL_TASKS


def task_meta(task_name: str) -> dict:
    return MAIL_TASKS.get(task_name, {})


def get_recipients_raw(task_name: str) -> str:
    """Valore grezzo dei destinatari (dalla chiave SiteConfig del flusso)."""
    meta = MAIL_TASKS.get(task_name)
    if not meta or not meta.get("config_key"):
        return ""
    from core.models import SiteConfig

    return SiteConfig.get(meta["config_key"], "")


def set_recipients_raw(task_name: str, value: str) -> bool:
    meta = MAIL_TASKS.get(task_name)
    if not meta or not meta.get("config_key"):
        return False
    from core.models import SiteConfig

    return SiteConfig.set(meta["config_key"], (value or "").strip(),
                          descrizione=f"Destinatari mail: {meta.get('label', task_name)}")


def get_text_overrides(task_name: str):
    """Ritorna il record ScheduledMailText del task (None se assente)."""
    from .models import ScheduledMailText

    try:
        return ScheduledMailText.objects.filter(task_name=task_name).first()
    except Exception:
        return None


def apply_mail_overrides(task_name: str, *, subject: str, body_text: str = "",
                         fragment: str = "", footer_note: str = "") -> tuple[str, str, str, str]:
    """Applica gli override di cornice (oggetto/intro/nota) prima di ``send_hub_mail``.

    Ritorna ``(subject, body_text, fragment, footer_note)``. Fail-safe: se non c'è
    override, restituisce gli argomenti invariati. L'intro viene anteposta sia al
    testo sia al frammento HTML (escaped); oggetto e nota sostituiscono i default.
    """
    cfg = get_text_overrides(task_name)
    if cfg is None:
        return subject, body_text, fragment, footer_note

    new_subject = (cfg.subject or "").strip() or subject
    new_footer = (cfg.footer or "").strip() or footer_note
    intro = (cfg.intro or "").strip()
    if intro:
        body_text = f"{intro}\n\n{body_text}" if body_text else intro
        # Se il chiamante usa un frammento HTML, anteponi l'intro come paragrafo.
        # Se NON usa un frammento (fragment=""), lascialo vuoto: send_hub_mail
        # convertirà automaticamente body_text (che già contiene l'intro).
        if fragment:
            intro_html = "".join(
                f"<p style='margin:0 0 12px;color:#334155'>{escape(p.strip())}</p>"
                for p in intro.splitlines() if p.strip()
            )
            fragment = intro_html + fragment
    return new_subject, body_text, fragment, new_footer


# ── Pannello unico «Mail, destinatari e orario» (Pianificati + designer) ───────

def orario_da_cron(cron: str) -> str:
    """«HH:MM» se minuto e ora del cron sono numeri singoli, altrimenti "" (non modificabile al volo)."""
    parts = str(cron or "").split()
    if len(parts) != 5 or not (parts[0].isdigit() and parts[1].isdigit()):
        return ""
    minuto, ora = int(parts[0]), int(parts[1])
    if minuto > 59 or ora > 23:
        return ""
    return f"{ora:02d}:{minuto:02d}"


def cron_con_orario(cron: str, orario: str) -> str:
    """Stesso calendario (giorni/mesi) con un nuovo «HH:MM». ValueError se l'orario non è valido."""
    if not orario_da_cron(cron):
        raise ValueError("Questo flusso non ha un orario fisso: cambia il calendario dal flusso.")
    try:
        ora_s, minuto_s = str(orario).strip().split(":")[:2]
        ora, minuto = int(ora_s), int(minuto_s)
    except (TypeError, ValueError):
        raise ValueError("Orario non valido: usa il formato HH:MM.")
    if not (0 <= ora <= 23 and 0 <= minuto <= 59):
        raise ValueError("Orario non valido: usa il formato HH:MM.")
    parts = str(cron).split()
    return " ".join([str(minuto), str(ora), *parts[2:]])


def pannello(task_name: str) -> dict | None:
    """Dati del pannello laterale per un task pianificato (None se il task non esiste)."""
    from .models import ManagedFlow
    from .schedules import DIGEST_E_PROMEMORIA, _oggetto_riga, describe_cadence, schedule_descriptions, spec_by_name

    spec = spec_by_name(task_name)
    if not spec:
        return None
    binding = ManagedFlow.objects.filter(code=task_name, kind="schedule").first()
    effective = dict(spec)
    if binding:
        effective.update(schedule_type=binding.schedule_type, minutes=binding.minutes, cron=binding.cron)
    meta = task_meta(task_name)
    txt = get_text_overrides(task_name) if meta else None
    orario = orario_da_cron(effective.get("cron")) if effective.get("schedule_type") == "C" else ""
    giorni = describe_cadence(effective)
    return {
        "name": task_name,
        "label": meta.get("label") or task_name.replace("_", " ").capitalize(),
        "description": schedule_descriptions().get(task_name, ""),
        "cadence": giorni,
        "orario": orario,
        "orario_modificabile": bool(binding and orario),
        "rule_id": binding.rule_id if binding else None,
        "configurable": bool(meta),
        "config_key": meta.get("config_key") or "",
        "solo_destinatari": bool(meta.get("solo_destinatari")),
        "recipients": get_recipients_raw(task_name),
        "a_chi": DIGEST_E_PROMEMORIA.get(task_name, ""),
        "subject": getattr(txt, "subject", "") or "",
        "intro": getattr(txt, "intro", "") or "",
        "footer": getattr(txt, "footer", "") or "",
        "oggetto_predefinito": _oggetto_riga(task_name)["oggetto"],
    }


def destinatari_elenco(task_name: str) -> list[str]:
    """Indirizzi configurati del task, già divisi (virgola, punto e virgola o a capo)."""
    import re

    return [x.strip() for x in re.split(r"[,;\s]+", get_recipients_raw(task_name)) if x.strip()]


def riepilogo_righe(task_name: str) -> list[str]:
    """Righe brevi per la card del designer (al posto di «Configurazione non disponibile»)."""
    p = pannello(task_name)
    if not p:
        return []
    righe = [f"Quando: {p['cadence']}"]
    if p["config_key"]:
        destinatari = ", ".join(destinatari_elenco(task_name))
        righe.append("Destinatari: " + (destinatari or ("nessuno, la mail non parte" if p["solo_destinatari"] else "amministratori di sistema")))
    elif p["a_chi"]:
        righe.append(f"A chi: {p['a_chi']}")
    oggetto = p["subject"] or p["oggetto_predefinito"]
    if oggetto:
        righe.append(f"Oggetto: {oggetto}")
    return righe
