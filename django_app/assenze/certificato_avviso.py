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
from core.email_utils import invia_con_regole_flusso

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


def _data_breve(value) -> str:
    """«05/10» (giorno/mese): le malattie vanno a giorni interi, l'ora non serve."""
    from .views import _helpers

    label = _helpers._dt_label(value)  # «dd-mm-YYYY HH:MM» in ora locale
    return label[:5].replace("-", "/") if label else "?"


def _periodo_breve(r: dict) -> str:
    dal, al = _data_breve(r.get("data_inizio")), _data_breve(r.get("data_fine"))
    return dal if dal == al else f"{dal}–{al}"


def _raggruppa(righe: list[dict]) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(DIPENDENTE, [(periodo, «#id»), ...]), ...] in ordine alfabetico."""
    gruppi: dict[str, list[tuple[str, str]]] = {}
    for r in sorted(righe, key=lambda x: (str(x.get("copia_nome") or "").upper(), str(x.get("data_inizio") or ""))):
        nome = str(r.get("copia_nome") or "").strip().upper() or "Dipendente"
        gruppi.setdefault(nome, []).append((_periodo_breve(r), f"#{r.get('id')}"))
    return list(gruppi.items())


def _corpo_mail(righe: list[dict], giorni: int) -> tuple[str, str]:
    """Mail compatta: una riga per dipendente, periodi in giorno/mese."""
    from core.accounts.portal_links import portal_link

    percorso = "/assenze/impostazioni/?stato=tutti&certificato=mancante#admin-assenze-panel"
    link = portal_link(percorso) or percorso
    gruppi = _raggruppa(righe)
    righe_html = "".join(
        "<tr>"
        f'<td style="padding:3px 12px 3px 0;color:#0f172a;font-weight:600;white-space:nowrap;vertical-align:top;">{escape(nome)}</td>'
        '<td style="padding:3px 0;color:#334155;">'
        + " &middot; ".join(f'{escape(periodo)} <span style="color:#94a3b8;">{escape(rid)}</span>' for periodo, rid in periodi)
        + "</td></tr>"
        for nome, periodi in gruppi
    )
    body_content = (
        '<p style="color:#334155;line-height:1.5;margin:0 0 10px;">'
        f"Malattie iniziate da almeno {giorni} giorni <strong>senza certificato</strong>:</p>"
        f'<table style="border-collapse:collapse;width:100%;font-size:13px;line-height:1.4;margin:0 0 12px;">{righe_html}</table>'
        '<p style="color:#64748b;font-size:13px;line-height:1.5;margin:0;">'
        f'<a href="{escape(link)}" style="color:#0f766e;font-weight:700;">Segna i certificati arrivati</a>'
        " (anche più insieme, senza mail).</p>"
    )
    html = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Avviso",
            "section_label": "Assenze e permessi",
            "title": "Certificato medico non arrivato",
            "body_content": body_content,
            "preheader": f"{len(righe)} malattie senza certificato medico dopo {giorni} giorni.",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB. Ogni malattia compare in un solo avviso.",
        },
    )
    testo = "\n".join(
        [f"Malattie iniziate da almeno {giorni} giorni senza certificato:", ""]
        + [f"- {nome}: " + ", ".join(f"{periodo} {rid}" for periodo, rid in periodi) for nome, periodi in gruppi]
        + ["", f"Segna i certificati arrivati: {link}", "", "Messaggio automatico generato da NOVICROM HUB."]
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
        invia_con_regole_flusso(msg)
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
