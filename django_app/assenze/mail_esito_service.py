"""Mail al dipendente quando la sua richiesta viene approvata o rifiutata dal portale.

Le decisioni prese dal link nella mail di approvazione hanno già la mail
«Richiesta … approvata/rifiutata» delle regole automazioni; quelle prese nel
portale (pagina del capo, gestione, calendario) passavano solo dalla
campanella. Best-effort: un errore mail non annulla la decisione.
"""
from __future__ import annotations

import logging
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string

from .mail_delete_service import _humanize_dt

logger = logging.getLogger(__name__)


def send_esito_dipendente(record: dict, *, consenso: str, tipo_display: str, note: str = "", deciso_da: str = "") -> bool:
    """Ritorna True se la mail e' partita. Non solleva mai."""
    if consenso not in ("Approvato", "Rifiutato"):
        return False
    email = str(record.get("email_esterna") or "").strip().lower()
    try:
        validate_email(email)
    except Exception:
        logger.info("send_esito_dipendente: richiesta id=%s senza email valida del dipendente", record.get("id"))
        return False

    from automazioni.mail_inviate import registra

    from .mail_certificato import ETICHETTA, certificato_arrivato, etichetta_si_no

    approvata = consenso == "Approvato"
    esito = "approvata" if approvata else "rifiutata"
    tipo = tipo_display or "assenza"
    periodo = f"{_humanize_dt(record.get('data_inizio'))} - {_humanize_dt(record.get('data_fine'))}".strip(" -") or "n/d"
    facts = [("Tipo richiesta", tipo), ("Periodo", periodo), ("Esito", esito.capitalize())]
    arrivato = certificato_arrivato(record.get("tipo_assenza"), record.get("certificato_medico"))
    if arrivato is not None:
        facts.append((ETICHETTA, etichetta_si_no(arrivato)))
    if deciso_da:
        facts.append(("Decisa da", deciso_da))
    if note:
        facts.append(("Nota", note))

    righe = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;vertical-align:top;">{escape(n)}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{escape(v)}</td></tr>'
        for n, v in facts
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        f"La tua richiesta è stata <strong>{esito}</strong>:</p>"
        f'<table style="border-collapse:collapse;width:100%;margin:4px 0 8px;">{righe}</table>'
    )
    subject = f"Richiesta {tipo} {esito}"
    html_body = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Approvata" if approvata else "Rifiutata",
            "section_label": "Assenze e permessi",
            "title": f"Richiesta {esito}",
            "body_content": body_content,
            "preheader": f"La tua richiesta di {tipo} ({periodo}) è stata {esito}.",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB.",
        },
    )
    text_body = "\n".join(
        [f"La tua richiesta è stata {esito}:", "", *[f"{n}: {v}" for n, v in facts], "",
         "Messaggio automatico generato da NOVICROM HUB."]
    )
    try:
        msg = EmailMultiAlternatives(
            subject=subject, body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or None, to=[email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    except Exception as exc:
        logger.warning("send_esito_dipendente: invio fallito per assenza id=%s", record.get("id"), exc_info=True)
        registra(origine="assenze_esito", destinatari=[email], oggetto=subject, sorgente="assenze",
                 record_id=record.get("id"), errore=f"{type(exc).__name__}: {exc}")
        return False
    registra(origine="assenze_esito", destinatari=[email], oggetto=subject, sorgente="assenze", record_id=record.get("id"))
    return True
