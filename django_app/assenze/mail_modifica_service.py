"""Mail ad assenza@ e al capo reparto quando una richiesta di assenza viene modificata.

Parte dalle view di modifica (`api_evento_update`, `api_mia_assenza_update`) con
l'elenco dei campi cambiati, prima → dopo. Best-effort: un errore mail non
annulla la modifica gia' salvata.
"""
from __future__ import annotations

import logging
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .mail_delete_service import _dedup_recipients, _hr_mailbox, _humanize_dt

logger = logging.getLogger(__name__)

# Casella dell'ufficio assenze, la stessa delle regole automazioni (0030).
# `ASSENZE_HR_MAILBOX` nel .env la sostituisce.
ASSENZE_MAILBOX_DEFAULT = "assenza@costruzioninovicrom.it"


def _assenze_mailbox() -> str:
    return _hr_mailbox() or ASSENZE_MAILBOX_DEFAULT


def send_assenza_modificata_notification(
    record: dict,
    *,
    modifiche: list[dict],
    tipo_display: str,
    capo_email: str = "",
    modificata_da: str = "",
    motivo: str = "",
) -> bool:
    """Ritorna True se la mail e' partita. Non solleva mai."""
    to_list = _dedup_recipients([_assenze_mailbox(), capo_email])
    if not to_list or not modifiche:
        return False

    dipendente = str(record.get("copia_nome") or "").strip().upper() or "Dipendente"
    periodo = f"{_humanize_dt(record.get('data_inizio'))} - {_humanize_dt(record.get('data_fine'))}".strip(" -") or "n/d"
    facts = [
        ("Dipendente", dipendente),
        ("Tipo richiesta", tipo_display or "—"),
        ("Periodo (prima della modifica)", periodo),
        ("Modificata da", modificata_da or "n/d"),
    ]
    if motivo:
        facts.append(("Motivo della modifica", motivo))

    def _val(v):
        return v if v else "—"

    righe_fatti = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;vertical-align:top;">{escape(n)}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{escape(v)}</td></tr>'
        for n, v in facts
    )
    righe_modifiche = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;">{escape(m.get("campo", ""))}</td>'
        f'<td style="padding:6px 12px;color:#64748b;text-decoration:line-through;">{escape(_val(m.get("prima")))}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;font-weight:600;">{escape(_val(m.get("dopo")))}</td></tr>'
        for m in modifiche
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        "&Egrave; stata <strong>modificata</strong> la seguente richiesta:</p>"
        f'<table style="border-collapse:collapse;width:100%;margin:4px 0 12px;">{righe_fatti}</table>'
        '<p style="color:#334155;margin:8px 0 6px;font-weight:600;">Cosa &egrave; cambiato</p>'
        '<table style="border-collapse:collapse;width:100%;margin:4px 0 8px;">'
        '<tr><th style="text-align:left;padding:4px 12px 4px 0;color:#64748b;font-size:12px;">Campo</th>'
        '<th style="text-align:left;padding:4px 12px;color:#64748b;font-size:12px;">Prima</th>'
        '<th style="text-align:left;padding:4px 0 4px 12px;color:#64748b;font-size:12px;">Ora</th></tr>'
        f"{righe_modifiche}</table>"
    )
    html_body = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Aggiornamento",
            "section_label": "Assenze e permessi",
            "title": "Richiesta modificata",
            "body_content": body_content,
            "preheader": f"Modificata la richiesta di {dipendente} ({periodo}).",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB.",
        },
    )
    text_body = "\n".join([
        "E' stata modificata la seguente richiesta:",
        "",
        *[f"{n}: {v}" for n, v in facts],
        "",
        "Cosa e' cambiato:",
        *[f"- {m.get('campo')}: {_val(m.get('prima'))} -> {_val(m.get('dopo'))}" for m in modifiche],
        "",
        "Messaggio automatico generato da NOVICROM HUB.",
    ])
    try:
        msg = EmailMultiAlternatives(
            subject=f"Richiesta modificata: {dipendente} · {tipo_display or 'assenza'}",
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or None,
            to=to_list,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    except Exception:
        logger.warning("send_assenza_modificata_notification: invio fallito per assenza id=%s", record.get("id"), exc_info=True)
        return False
    return True
