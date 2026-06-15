"""Notifica email per l'eliminazione di una richiesta di assenza/permesso *approvata*.

Il motore automazioni reagisce solo a insert/update/change: una riga eliminata
sparisce dal DB e non genera alcun evento, quindi la notifica di cancellazione
NON puo' passare dalle automazioni. Va emessa direttamente dalla view che esegue
la delete (`assenze.views.api_evento_delete`), prima di rimuovere il record.

Destinatari (deduplicati, case-insensitive):
- capo reparto che aveva approvato la richiesta;
- dipendente intestatario (email_esterna);
- mailbox amministrazione/HR (configurabile);
- utente che esegue l'eliminazione.

L'invio e' best-effort e fail-open: un errore mail non deve impedire/annullare
l'eliminazione (gia' avvenuta o imminente), si limita a loggare un warning.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string

from config.env_config import get_first_env_value

logger = logging.getLogger(__name__)

# Mailbox amministrazione/HR a cui inoltrare sempre l'avviso di eliminazione.
# Risolta da env (eventualmente piu' chiavi) con fallback vuoto: se non
# configurata, semplicemente non viene aggiunta ai destinatari.
_HR_MAILBOX_ENV_KEYS = ("ASSENZE_ELIMINAZIONE_NOTIFICA_TO", "ASSENZE_HR_MAILBOX")


def _hr_mailbox() -> str:
    return str(get_first_env_value(*_HR_MAILBOX_ENV_KEYS) or "").strip()


def _humanize_dt(value: Any) -> str:
    """Formatta una data/datetime in dd/mm/YYYY [HH:MM] leggibile.

    Coerente con il rendering delle mail di automazione: mezzanotte => solo data.
    Valori non interpretabili tornano come stringa grezza.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        parsed: datetime | None = value
    elif isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    else:
        text = str(value).strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed.strftime("%d/%m/%Y")
    return parsed.strftime("%d/%m/%Y %H:%M")


def _valid_email(value: Any) -> str:
    email = str(value or "").strip()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def _dedup_recipients(candidates: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        email = _valid_email(raw)
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(email)
    return out


def send_assenza_deleted_notification(
    record: dict,
    *,
    tipo_display: str,
    capo_email: str = "",
    deleted_by_name: str = "",
    deleted_by_email: str = "",
    from_email: str | None = None,
) -> bool:
    """Invia l'avviso di eliminazione di una richiesta approvata.

    Ritorna True se l'email e' stata accodata all'invio, False altrimenti
    (nessun destinatario valido o errore SMTP). Non solleva mai.
    """
    dipendente_email = str(record.get("email_esterna") or "").strip()
    dipendente_nome = str(record.get("copia_nome") or "").strip() or "Dipendente"

    to_list = _dedup_recipients(
        [capo_email, dipendente_email, _hr_mailbox(), deleted_by_email]
    )
    if not to_list:
        logger.info(
            "send_assenza_deleted_notification: nessun destinatario valido per assenza id=%s",
            record.get("id"),
        )
        return False

    data_inizio = _humanize_dt(record.get("data_inizio"))
    data_fine = _humanize_dt(record.get("data_fine"))
    periodo = f"{data_inizio} - {data_fine}".strip(" -") or "n/d"
    motivazione = str(record.get("motivazione_richiesta") or "").strip()
    eseguita_da = (deleted_by_name or "").strip() or (deleted_by_email or "").strip() or "n/d"

    facts: list[tuple[str, str]] = [
        ("Dipendente", dipendente_nome),
        ("Tipo richiesta", tipo_display or "—"),
        ("Periodo", periodo),
    ]
    if motivazione:
        facts.append(("Motivazione", motivazione))
    facts.append(("Eliminata da", eseguita_da))

    rows_html = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;'
        f'white-space:nowrap;vertical-align:top;">{name}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{value}</td></tr>'
        for name, value in facts
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        "&Egrave; stata <strong>eliminata</strong> la seguente richiesta, "
        "che risultava gi&agrave; <strong>approvata</strong>:"
        "</p>"
        '<table style="border-collapse:collapse;width:100%;margin:4px 0 8px;">'
        f"{rows_html}</table>"
    )

    subject = f"Eliminazione richiesta approvata di {dipendente_nome}"

    html_body = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Avviso",
            "section_label": "Assenze e permessi",
            "title": "Richiesta approvata eliminata",
            "body_content": body_content,
            "preheader": f"Eliminata richiesta approvata di {dipendente_nome} ({periodo}).",
            "footer_note": (
                "Messaggio automatico generato da NOVICROM HUB. "
                "La richiesta era stata approvata ed e' stata successivamente eliminata."
            ),
        },
    )

    text_body = "\n".join(
        [
            "E' stata eliminata la seguente richiesta, gia' approvata:",
            "",
            *[f"{name}: {value}" for name, value in facts],
            "",
            "Messaggio automatico generato da NOVICROM HUB.",
        ]
    )

    _from = from_email or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it"
    )
    try:
        msg = EmailMultiAlternatives(
            subject=subject, body=text_body, from_email=_from, to=to_list
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    except Exception:
        logger.warning(
            "send_assenza_deleted_notification: invio fallito per assenza id=%s",
            record.get("id"),
            exc_info=True,
        )
        return False

    logger.info(
        "send_assenza_deleted_notification: avviso inviato per assenza id=%s a %s",
        record.get("id"),
        ", ".join(to_list),
    )
    return True
