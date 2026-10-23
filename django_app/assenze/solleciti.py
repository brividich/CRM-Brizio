"""Solleciti ai capi per le richieste di assenza ferme «In attesa».

Ogni mattina feriale il job ``assenze_solleciti`` cerca le richieste in attesa
da almeno ``sollecito_dopo_giorni`` e manda **una mail per capo** con l'elenco.
Una stessa richiesta non viene risollecitata prima di ``sollecito_ripeti_giorni``.

Esclusioni: le richieste nate su SharePoint (le approva il flusso Power
Automate) e quelle finite da più di una settimana. Il capo è quello che approva
davvero: il capo scelto nella richiesta, se c'è, altrimenti quello
dell'organigramma.
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


def _email_capo_scelto(capo_legacy_user_id: int) -> str:
    """Email per le notifiche del capo scelto: ``email_notifica`` dell'anagrafica, poi la login."""
    from core.legacy_models import AnagraficaDipendente, UtenteLegacy

    for valore in AnagraficaDipendente.objects.filter(utente_id=capo_legacy_user_id).values_list(
        "email_notifica", "email"
    ):
        for email in valore:
            if email and "@" in str(email):
                return str(email).strip().lower()
    utente = UtenteLegacy.objects.filter(id=capo_legacy_user_id).first()
    email = str(getattr(utente, "email", "") or "").strip()
    return email.lower() if "@" in email else ""


def richieste_da_sollecitare(now=None, imp=None) -> list[dict]:
    """Richieste in attesa da sollecitare adesso, con l'email del capo in ``capo_email``."""
    from .hr import impostazioni
    from .models import AssenzaCapoScelto, AssenzaOrigineSharePoint, AssenzaSollecito
    from .views import _helpers

    now = now or timezone.now()
    imp = imp or impostazioni()
    if not _helpers._table_exists("assenze") or not _helpers._has_assenze_column("created_datetime"):
        return []
    soglia = now - timedelta(days=int(imp.sollecito_dopo_giorni or 0))
    oggi = timezone.localdate()
    cols = [c for c in (
        "id", "copia_nome", "email_esterna", "utente_id", "aliasusername", "tipo_assenza",
        "data_inizio", "data_fine", "motivazione_richiesta", "capo_reparto_id", "created_datetime",
    ) if _helpers._has_assenze_column(c)]
    rows = _helpers._fetch_all_dict(
        f"SELECT {_helpers._quoted_columns(cols)} FROM assenze "
        "WHERE COALESCE(moderation_status, 2) = 2 AND created_datetime <= %s AND data_fine >= %s",
        [soglia, datetime(oggi.year, oggi.month, oggi.day) - timedelta(days=7)],
    )
    if not rows:
        return []
    ids = [int(r["id"]) for r in rows]
    gestite_sp = set(
        AssenzaOrigineSharePoint.objects.filter(assenza_id__in=ids, creata_su_sharepoint=True)
        .values_list("assenza_id", flat=True)
    )
    ripeti = now - timedelta(days=max(1, int(imp.sollecito_ripeti_giorni or 1)))
    recenti = set(
        AssenzaSollecito.objects.filter(assenza_id__in=ids, ultimo_invio__gt=ripeti)
        .values_list("assenza_id", flat=True)
    )
    scelti = dict(
        AssenzaCapoScelto.objects.filter(assenza_id__in=ids).values_list("assenza_id", "capo_legacy_user_id")
    )
    out = []
    for r in rows:
        rid = int(r["id"])
        if rid in gestite_sp or rid in recenti:
            continue
        if rid in scelti:
            r["capo_email"] = _email_capo_scelto(scelti[rid])
        else:
            r["capo_email"] = _helpers._capo_email_for_row(r)
        if r["capo_email"]:
            out.append(r)
        else:
            logger.info("assenze.solleciti: richiesta %s senza capo con email, nessun sollecito", rid)
    return out


def _corpo_mail(righe: list[dict]) -> tuple[str, str]:
    from .views import _helpers

    base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    link = f"{base}/assenze/car/dashboard" if base else "/assenze/car/dashboard"
    voci = []
    for r in righe:
        tipo = _helpers._tipo_for_display(r.get("tipo_assenza"), r.get("motivazione_richiesta"))
        voci.append((
            str(r.get("copia_nome") or "").upper(),
            tipo,
            f"{_helpers._dt_label(r.get('data_inizio'))} - {_helpers._dt_label(r.get('data_fine'))}",
            _helpers._dt_label(r.get("created_datetime")),
        ))
    righe_html = "".join(
        '<tr>'
        f'<td style="padding:6px 10px 6px 0;color:#0f172a;font-weight:600;">{escape(nome)}</td>'
        f'<td style="padding:6px 10px;color:#334155;">{escape(tipo)}</td>'
        f'<td style="padding:6px 10px;color:#334155;">{escape(periodo)}</td>'
        f'<td style="padding:6px 0 6px 10px;color:#64748b;">{escape(creata)}</td>'
        '</tr>'
        for nome, tipo, periodo, creata in voci
    )
    body_content = (
        '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">'
        f"Ci sono <strong>{len(voci)}</strong> richieste di assenza che aspettano la tua decisione:"
        "</p>"
        '<table style="border-collapse:collapse;width:100%;margin:4px 0 14px;">'
        '<tr><th align="left" style="padding:0 10px 6px 0;color:#64748b;">Dipendente</th>'
        '<th align="left" style="padding:0 10px 6px;color:#64748b;">Tipo</th>'
        '<th align="left" style="padding:0 10px 6px;color:#64748b;">Periodo</th>'
        '<th align="left" style="padding:0 0 6px 10px;color:#64748b;">Inviata il</th></tr>'
        f"{righe_html}</table>"
        f'<p style="margin:0;"><a href="{escape(link)}" style="color:#0f766e;font-weight:700;">'
        "Apri «Assenze del reparto» per approvare o rifiutare</a></p>"
    )
    html = render_to_string(
        "core/email/base_email.html",
        {
            "email_type": "Automazioni",
            "badge": "Promemoria",
            "section_label": "Assenze e permessi",
            "title": "Richieste di assenza in attesa",
            "body_content": body_content,
            "preheader": f"{len(voci)} richieste di assenza aspettano la tua decisione.",
            "footer_note": "Messaggio automatico generato da NOVICROM HUB. "
                           "Il promemoria si ripete finché la richiesta resta in attesa.",
        },
    )
    testo = "\n".join(
        ["Richieste di assenza che aspettano la tua decisione:", ""]
        + [f"- {n} | {t} | {p} | inviata il {c}" for n, t, p, c in voci]
        + ["", f"Apri: {link}", "", "Messaggio automatico generato da NOVICROM HUB."]
    )
    return html, testo


def invia_solleciti(now=None) -> dict:
    """Manda i solleciti dovuti. Ritorna i contatori per il Run-log."""
    from .hr import impostazioni
    from .models import AssenzaSollecito

    now = now or timezone.now()
    imp = impostazioni()
    if not imp.sollecito_attivo:
        return {"skipped": "solleciti spenti nelle impostazioni HR"}
    righe = richieste_da_sollecitare(now, imp)
    per_capo: dict[str, list[dict]] = {}
    for r in righe:
        per_capo.setdefault(r["capo_email"], []).append(r)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or "noreply@costruzioninovicrom.it"
    inviate = 0
    richieste = 0
    errori = 0
    for email, elenco in per_capo.items():
        html, testo = _corpo_mail(elenco)
        try:
            msg = EmailMultiAlternatives(
                subject=f"Promemoria: {len(elenco)} richieste di assenza in attesa",
                body=testo, from_email=from_email, to=[email],
            )
            msg.attach_alternative(html, "text/html")
            msg.send(fail_silently=False)
        except Exception:
            errori += 1
            logger.warning("assenze.solleciti: invio a %s non riuscito", email, exc_info=True)
            continue
        inviate += 1
        for r in elenco:
            richieste += 1
            obj, _ = AssenzaSollecito.objects.get_or_create(
                assenza_id=int(r["id"]), defaults={"ultimo_invio": now, "destinatario": email[:200]},
            )
            obj.ultimo_invio = now
            obj.invii = (obj.invii or 0) + 1
            obj.destinatario = email[:200]
            obj.save(update_fields=["ultimo_invio", "invii", "destinatario"])
    return {"email_sent": inviate, "reminders": richieste, "errori": errori}
