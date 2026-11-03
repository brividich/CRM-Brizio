"""Avviso ad assenza@ per le malattie ancora senza certificato medico.

Ogni mattina il job ``assenze_certificato_avviso`` cerca le malattie iniziate da
almeno ``certificato_avviso_giorni`` giorni (Impostazioni HR, default 2) senza la
spunta «Certificato arrivato» e manda **una mail sola** all'ufficio assenze con
l'elenco. Ogni richiesta compare in un solo avviso (``AssenzaAvvisoCertificato``).

Esclusioni: le richieste rifiutate e quelle iniziate da più di
``FINESTRA_GIORNI`` giorni, così all'accensione non parte lo storico intero.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

FINESTRA_GIORNI = 30


def malattie_senza_certificato(now=None, imp=None) -> list[dict]:
    """Malattie da segnalare adesso (non ancora avvisate)."""
    from .hr import impostazioni
    from .mail_certificato import certificato_arrivato
    from .models import AssenzaAvvisoCertificato
    from .views import _helpers

    now = now or timezone.now()
    imp = imp or impostazioni()
    if not _helpers._table_exists("assenze") or not _helpers._has_assenze_column("certificato_medico"):
        return []
    oggi = timezone.localdate(now)
    giorni = max(1, int(imp.certificato_avviso_giorni or 2))
    ultimo_giorno = oggi - timedelta(days=giorni)
    dal = datetime(oggi.year, oggi.month, oggi.day) - timedelta(days=FINESTRA_GIORNI)
    al = datetime(ultimo_giorno.year, ultimo_giorno.month, ultimo_giorno.day) + timedelta(days=1)
    cols = [c for c in (
        "id", "copia_nome", "email_esterna", "tipo_assenza", "data_inizio", "data_fine",
        "motivazione_richiesta", "certificato_medico", "moderation_status", "capo_reparto_id",
    ) if _helpers._has_assenze_column(c)]
    rows = _helpers._fetch_all_dict(
        f"SELECT {_helpers._quoted_columns(cols)} FROM assenze "
        "WHERE COALESCE(moderation_status, 2) <> 1 AND data_inizio >= %s AND data_inizio < %s",
        [dal, al],
    )
    rows = [r for r in rows if certificato_arrivato(r.get("tipo_assenza"), r.get("certificato_medico")) is False]
    if not rows:
        return []
    gia = set(
        AssenzaAvvisoCertificato.objects.filter(assenza_id__in=[int(r["id"]) for r in rows])
        .values_list("assenza_id", flat=True)
    )
    return [r for r in rows if int(r["id"]) not in gia]


def _corpo_mail(righe: list[dict], giorni: int) -> tuple[str, str]:
    from core.accounts.portal_links import portal_link

    from .views import _helpers

    link = portal_link("/assenze/calendario") or "/assenze/calendario"
    voci = [
        (
            str(r.get("copia_nome") or "").upper() or "Dipendente",
            f"{_helpers._dt_label(r.get('data_inizio'))} - {_helpers._dt_label(r.get('data_fine'))}",
            f"#{r.get('id')}",
        )
        for r in righe
    ]
    righe_html = "".join(
        "<tr>"
        f'<td style="padding:6px 10px 6px 0;color:#0f172a;font-weight:600;">{escape(nome)}</td>'
        f'<td style="padding:6px 10px;color:#334155;">{escape(periodo)}</td>'
        f'<td style="padding:6px 0 6px 10px;color:#64748b;">{escape(rid)}</td>'
        "</tr>"
        for nome, periodo, rid in voci
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        f"Per queste malattie, iniziate da almeno <strong>{giorni} giorni</strong>, "
        "il certificato medico <strong>non risulta arrivato</strong>:</p>"
        '<table style="border-collapse:collapse;width:100%;margin:4px 0 14px;">'
        '<tr><th align="left" style="padding:0 10px 6px 0;color:#64748b;">Dipendente</th>'
        '<th align="left" style="padding:0 10px 6px;color:#64748b;">Periodo</th>'
        '<th align="left" style="padding:0 0 6px 10px;color:#64748b;">Richiesta</th></tr>'
        f"{righe_html}</table>"
        '<p style="color:#334155;line-height:1.6;margin:0 0 10px;">Quando arriva, apri la richiesta con '
        "«Modifica» e spunta «Certificato arrivato».</p>"
        f'<p style="margin:0;"><a href="{escape(link)}" style="color:#0f766e;font-weight:700;">Apri il calendario assenze</a></p>'
    )
    html = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Avviso",
            "section_label": "Assenze e permessi",
            "title": "Certificato medico non arrivato",
            "body_content": body_content,
            "preheader": f"{len(voci)} malattie senza certificato medico dopo {giorni} giorni.",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB. Ogni malattia compare in un solo avviso.",
        },
    )
    testo = "\n".join(
        [f"Malattie iniziate da almeno {giorni} giorni senza certificato medico arrivato:", ""]
        + [f"- {nome} | {periodo} | richiesta {rid}" for nome, periodo, rid in voci]
        + ["", "Quando arriva, apri la richiesta con «Modifica» e spunta «Certificato arrivato».",
           f"Apri: {link}", "", "Messaggio automatico generato da NOVICROM HUB."]
    )
    return html, testo


def invia_avvisi(now=None) -> dict:
    """Manda l'avviso del giorno. Ritorna i contatori per il Run-log."""
    from automazioni.mail_inviate import registra

    from .hr import impostazioni
    from .mail_modifica_service import _assenze_mailbox
    from .models import AssenzaAvvisoCertificato

    now = now or timezone.now()
    imp = impostazioni()
    if not imp.certificato_avviso_attivo:
        return {"skipped": "avviso certificato spento nelle impostazioni HR"}
    righe = malattie_senza_certificato(now, imp)
    if not righe:
        return {"email_sent": 0, "malattie": 0}
    destinatario = _assenze_mailbox()
    giorni = max(1, int(imp.certificato_avviso_giorni or 2))
    html, testo = _corpo_mail(righe, giorni)
    oggetto = f"Certificato medico non arrivato: {len(righe)} malatti{'a' if len(righe) == 1 else 'e'}"
    ids = ", ".join(str(r["id"]) for r in righe)
    try:
        msg = EmailMultiAlternatives(
            subject=oggetto, body=testo,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "") or "noreply@costruzioninovicrom.it",
            to=[destinatario],
        )
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
    except Exception as exc:
        logger.warning("assenze.certificato_avviso: invio a %s non riuscito", destinatario, exc_info=True)
        registra(origine="assenze_certificato", destinatari=[destinatario], oggetto=oggetto, sorgente="assenze",
                 record_id=ids, errore=f"{type(exc).__name__}: {exc}")
        return {"email_sent": 0, "malattie": len(righe), "errori": 1}
    registra(origine="assenze_certificato", destinatari=[destinatario], oggetto=oggetto, sorgente="assenze",
             record_id=ids)
    for r in righe:
        AssenzaAvvisoCertificato.objects.get_or_create(
            assenza_id=int(r["id"]), defaults={"inviato_il": now, "destinatari": destinatario[:300]},
        )
    return {"email_sent": 1, "malattie": len(righe)}
