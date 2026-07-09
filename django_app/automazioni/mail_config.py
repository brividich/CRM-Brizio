"""Configurazione utente dei flussi mail schedulati (destinatari + testo).

Due livelli, entrambi editabili dalla scheda «Task pianificati» dell'area automazioni:

- **Destinatari**: restano su ``core.SiteConfig`` (una chiave per flusso), così i
  management command li leggono già senza modifiche (via ``get_reminder_recipients``).
  La UI legge/scrive la chiave indicata in ``MAIL_TASKS[task]['config_key']``.
- **Cornice testuale** (oggetto/intro/nota): su ``ScheduledMailText`` (per task).
  I comandi la applicano prima dell'invio con :func:`apply_mail_overrides`.

Solo i task elencati in ``MAIL_TASKS`` espongono la pagina «Configura mail».
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
        if body_text:
            body_text = f"{intro}\n\n{body_text}"
        else:
            body_text = intro
        intro_html = "".join(
            f"<p style='margin:0 0 12px;color:#334155'>{escape(p.strip())}</p>"
            for p in intro.splitlines() if p.strip()
        )
        fragment = intro_html + (fragment or "")
    return new_subject, body_text, fragment, new_footer
