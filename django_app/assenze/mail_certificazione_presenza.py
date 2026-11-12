"""Conferma della certificazione presenza inserita dalla pagina «Certificazione presenza».

L'inserimento diretto nasce già approvato (``salta_approvazione`` e
``moderation_status=0``): nessuna regola delle automazioni scatta, quindi la
conferma parte da qui. Va al dipendente certificato e a chi l'ha inserita, con
l'ufficio assenze in copia. Best-effort: un errore mail non annulla il salvataggio.
"""
from __future__ import annotations

import logging
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core import naming

from .mail_delete_service import _dedup_recipients
from .mail_modifica_service import _assenze_mailbox
from automazioni.managed_flows import event_flow
from core.email_utils import invia_con_regole_flusso

logger = logging.getLogger(__name__)


def email_dipendente_per_nome(nominativo: str) -> str:
    """Indirizzo di notifica del dipendente attivo con quel nominativo (``COGNOME NOME``).

    Vuoto se il nome non corrisponde a esattamente una persona: meglio nessuna
    mail che una mail alla persona sbagliata.
    """
    from .views import _helpers
    from core.legacy_anagrafica import resolve_notification_email

    target = str(nominativo or "").strip().upper()
    if not target or not _helpers._table_exists("anagrafica_dipendenti"):
        return ""
    cols = _helpers.legacy_table_columns("anagrafica_dipendenti")
    if "nome" not in cols or "cognome" not in cols:
        return ""
    select_cols = [c for c in ("nome", "cognome", "email", "email_notifica", "attivo") if c in cols]
    where = "WHERE attivo = 1" if "attivo" in cols else ""
    rows = _helpers._fetch_all_dict(
        f"SELECT {_helpers._quoted_columns(select_cols)} FROM anagrafica_dipendenti {where}"
    )
    indirizzi = {
        resolve_notification_email(email=str(r.get("email") or ""), email_notifica=str(r.get("email_notifica") or ""))
        for r in rows
        if naming.nome_completo(r.get("nome"), r.get("cognome")).upper() == target
    }
    indirizzi.discard("")
    return indirizzi.pop() if len(indirizzi) == 1 else ""


def _ora(t) -> str:
    return t.strftime("%H:%M") if t else ""


@event_flow("assenze_certificazione_presenza", skipped_result=False)
def send_certificazione_confermata(cert, *, inserito_da_email: str = "", inserito_da_nome: str = "") -> bool:
    """Ritorna True se la mail è partita. Non solleva mai."""
    from automazioni.mail_inviate import registra

    mailbox = _assenze_mailbox()
    to_list = _dedup_recipients([email_dipendente_per_nome(cert.nome_dipendente), inserito_da_email])
    cc_list = [m for m in _dedup_recipients([mailbox]) if m.lower() not in {t.lower() for t in to_list}]
    if not to_list:
        to_list, cc_list = cc_list, []
    if not to_list:
        return False

    dipendente = str(cert.nome_dipendente or "").strip().upper() or "Dipendente"
    data_txt = cert.data.strftime("%d/%m/%Y") if cert.data else "n/d"
    turni = f"{_ora(cert.entrata_mattina)} - {_ora(cert.uscita_mattina)}"
    if cert.turno_pomeriggio and cert.entrata_pomeriggio and cert.uscita_pomeriggio:
        turni += f" · {_ora(cert.entrata_pomeriggio)} - {_ora(cert.uscita_pomeriggio)}"
    facts = [
        ("Dipendente", dipendente),
        ("Giorno", data_txt),
        ("Orari", turni),
        ("Ore totali", f"{cert.ore_totali:g} h"),
        ("Inserita da", inserito_da_nome or "n/d"),
    ]
    if cert.note:
        facts.append(("Note", cert.note))
    facts = [(n, v) for n, v in facts if v]

    righe = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;vertical-align:top;">{escape(n)}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{escape(v)}</td></tr>'
        for n, v in facts
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        "La seguente certificazione presenza &egrave; stata <strong>registrata e approvata</strong>:</p>"
        f'<table style="border-collapse:collapse;width:100%;margin:4px 0 12px;">{righe}</table>'
    )
    html_body = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Approvata",
            "section_label": "Assenze e permessi",
            "title": "Certificazione presenza approvata",
            "body_content": body_content,
            "preheader": f"Certificazione presenza di {dipendente} del {data_txt} approvata.",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB.",
        },
    )
    text_body = "\n".join([
        "La seguente certificazione presenza e' stata registrata e approvata:",
        "",
        *[f"{n}: {v}" for n, v in facts],
        "",
        "Messaggio automatico generato da NOVICROM HUB.",
    ])
    subject = f"Certificazione presenza approvata: {dipendente} · {data_txt}"
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or None,
            to=to_list,
            cc=cc_list,
        )
        msg.attach_alternative(html_body, "text/html")
        invia_con_regole_flusso(msg)
    except Exception as exc:
        logger.warning("send_certificazione_confermata: invio fallito per certificazione id=%s", cert.pk, exc_info=True)
        registra(origine="assenze_certificazione", destinatari=to_list, copia=cc_list, oggetto=subject,
                 sorgente="assenze", record_id=cert.pk, errore=f"{type(exc).__name__}: {exc}")
        return False
    registra(origine="assenze_certificazione", destinatari=to_list, copia=cc_list, oggetto=subject,
             sorgente="assenze", record_id=cert.pk)
    return True
