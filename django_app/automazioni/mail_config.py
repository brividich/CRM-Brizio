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

    return _applica_testo(cfg, subject, body_text, fragment, footer_note)


def _applica_testo(cfg, subject: str, body_text: str, fragment: str, footer_note: str) -> tuple[str, str, str, str]:
    new_subject = componi_oggetto(cfg.subject, subject)
    new_footer = (cfg.footer or "").strip() or footer_note
    intro = (cfg.intro or "").strip()
    if intro:
        body_text = f"{intro}\n\n{body_text}" if body_text else intro
        # Con un frammento HTML l'intro va anche lì; senza, send_hub_mail converte body_text.
        if fragment:
            intro_html = "".join(
                f"<p style='margin:0 0 12px;color:#334155'>{escape(p.strip())}</p>"
                for p in intro.splitlines() if p.strip()
            )
            fragment = intro_html + fragment
    return new_subject, body_text, fragment, new_footer


# ── Flusso in stile Power Automate: Ricorrenza/evento → processo → «Invia mail» ──

# Contenuto dinamico dell'oggetto: «{oggetto}» = l'oggetto che il modulo avrebbe usato.
TOKEN_OGGETTO = "{oggetto}"


def componi_oggetto(personalizzato: str, originale: str) -> str:
    personalizzato = (personalizzato or "").strip()
    if not personalizzato:
        return originale
    return personalizzato.replace(TOKEN_OGGETTO, originale or "")


def elenco_indirizzi(testo: str) -> list[str]:
    """Indirizzi divisi da virgola, punto e virgola, spazi o a capo."""
    import re

    return [x.strip() for x in re.split(r"[,;\s]+", testo or "") if x.strip()]


def destinatari_elenco(task_name: str) -> list[str]:
    """Indirizzi dell'elenco fisso del task (SiteConfig), già divisi."""
    return elenco_indirizzi(get_recipients_raw(task_name))


def _unici(indirizzi, esclusi: set[str]) -> list[str]:
    visti: set[str] = set()
    out = []
    for x in indirizzi:
        k = str(x).strip().lower()
        if k and k not in visti and k not in esclusi:
            visti.add(k)
            out.append(str(x).strip())
    return out


def personalizza_invio(subject: str, body_text: str, fragment: str, footer_note: str,
                       recipients, cc, *, codice: str | None = None, anteprima: bool = False) -> dict | None:
    """Passaggio «Invia mail» del flusso, applicato da ``core.email_utils.send_hub_mail``.

    Vale per ogni mail che un processo manda mentre gira dentro il suo flusso gestito
    (o per ``codice`` esplicito, es. l'anteprima). None = nessuna personalizzazione.
    Con ``anteprima`` cambia solo il testo: i destinatari restano quelli passati.
    """
    if not codice:
        from .managed_flows import codice_flusso_corrente

        codice = codice_flusso_corrente()
    if not codice:
        return None
    cfg = get_text_overrides(codice)
    if cfg is None:
        return None
    if cfg.mail_disattivata and not anteprima:
        return {"blocca": True, "motivo": "Mail disattivata nel flusso"}
    # I comandi di MAIL_TASKS applicano già la cornice con apply_mail_overrides.
    if codice not in MAIL_TASKS or anteprima:
        subject, body_text, fragment, footer_note = _applica_testo(cfg, subject, body_text, fragment, footer_note)
    to, copia = list(recipients or []), list(cc or [])
    if not anteprima:
        esclusi = {x.lower() for x in elenco_indirizzi(cfg.escludi)}
        aggiunti_a = elenco_indirizzi(cfg.aggiungi_a)
        to = aggiunti_a if cfg.sostituisci_destinatari else to + aggiunti_a
        copia = [] if cfg.sostituisci_destinatari else copia
        copia = copia + elenco_indirizzi(cfg.aggiungi_cc)
        to = _unici(to, esclusi)
        copia = _unici(copia, esclusi | {x.lower() for x in to})
    return {"blocca": not to, "motivo": "Nessun destinatario dopo le regole del flusso",
            "subject": subject, "body_text": body_text, "fragment": fragment,
            "footer_note": footer_note, "recipients": to, "cc": copia,
            "intro": (cfg.intro or "").strip(), "footer": (cfg.footer or "").strip(),
            "testo_applicato": codice not in MAIL_TASKS or anteprima}


def pannello(codice: str) -> dict | None:
    """Dati del flusso in stile Power Automate (None se il codice non è nel catalogo)."""
    from . import ricorrenza
    from .managed_flows import catalog
    from .models import ManagedFlow
    from .schedules import DIGEST_E_PROMEMORIA, DIGEST_OGGETTO, _oggetto_riga, describe_cadence

    spec = catalog().get(codice)
    if not spec:
        return None
    binding = ManagedFlow.objects.select_related("rule").filter(code=codice).first()
    meta = task_meta(codice)
    txt = get_text_overrides(codice)
    pianificato = spec["kind"] == "schedule"
    ric, cadence, next_run = None, "", None
    if pianificato:
        st = binding.schedule_type if binding else spec.get("schedule_type", "I")
        mins = binding.minutes if binding else spec.get("minutes")
        cron = binding.cron if binding else spec.get("cron", "")
        ric = ricorrenza.da_flusso(st, mins, cron)
        cadence = describe_cadence({"schedule_type": st, "minutes": mins, "cron": cron})
        try:
            from django_q.models import Schedule

            next_run = Schedule.objects.filter(name=codice).values_list("next_run", flat=True).first()
        except Exception:
            next_run = None
    serie = DIGEST_OGGETTO.get(codice)
    if meta or serie or not pianificato:
        manda_mail = "si"
    elif serie == ():
        manda_mail = "no"
    else:
        manda_mail = "forse"
    return {
        "name": codice,
        "kind": spec["kind"],
        "pianificato": pianificato,
        "label": meta.get("label") or spec.get("label") or codice.replace("_", " "),
        "module": spec.get("module", ""),
        "description": spec.get("description", ""),
        "quando_evento": "" if pianificato else spec.get("trigger", ""),
        "cadence": cadence,
        "ric": ric,
        "next_run": next_run,
        "frequenze": ricorrenza.FREQUENZE,
        "giorni_settimana": ricorrenza.GIORNI,
        "modificabile": bool(binding),
        "rule_id": binding.rule_id if binding else None,
        "attivo": bool(binding.rule.is_active and not binding.rule.is_draft) if binding else spec.get("attivo_di_default", True),
        "manda_mail": manda_mail,
        "configurable": bool(meta),
        "config_key": meta.get("config_key") or "",
        "solo_destinatari": bool(meta.get("solo_destinatari")),
        "recipients": get_recipients_raw(codice),
        "a_chi": DIGEST_E_PROMEMORIA.get(codice) or spec.get("destinatari", ""),
        "subject": getattr(txt, "subject", "") or "",
        "intro": getattr(txt, "intro", "") or "",
        "footer": getattr(txt, "footer", "") or "",
        "aggiungi_a": getattr(txt, "aggiungi_a", "") or "",
        "aggiungi_cc": getattr(txt, "aggiungi_cc", "") or "",
        "escludi": getattr(txt, "escludi", "") or "",
        "sostituisci": bool(getattr(txt, "sostituisci_destinatari", False)),
        "mail_disattivata": bool(getattr(txt, "mail_disattivata", False)),
        "oggetto_predefinito": _oggetto_riga(codice)["oggetto"],
        "token_oggetto": TOKEN_OGGETTO,
    }


def riepilogo_righe(codice: str) -> list[str]:
    """Righe brevi per la card del designer e il nodo del diagramma."""
    p = pannello(codice)
    if not p:
        return []
    righe = [f"Quando: {p['cadence'] or p['quando_evento']}"]
    if p["mail_disattivata"]:
        righe.append("Mail disattivata: il processo gira senza mandare mail")
        return righe
    if p["sostituisci"]:
        righe.append("A: " + ", ".join(elenco_indirizzi(p["aggiungi_a"])))
    elif p["config_key"]:
        destinatari = ", ".join(destinatari_elenco(codice))
        righe.append("A: " + (destinatari or ("nessuno, la mail non parte" if p["solo_destinatari"] else "amministratori di sistema")))
    elif p["a_chi"]:
        righe.append(f"A: {p['a_chi']}")
    if p["aggiungi_a"] and not p["sostituisci"]:
        righe.append("In più in A: " + ", ".join(elenco_indirizzi(p["aggiungi_a"])))
    if p["aggiungi_cc"]:
        righe.append("CC: " + ", ".join(elenco_indirizzi(p["aggiungi_cc"])))
    oggetto = componi_oggetto(p["subject"], p["oggetto_predefinito"]) if p["subject"] else p["oggetto_predefinito"]
    if oggetto:
        righe.append(f"Oggetto: {oggetto}")
    return righe
