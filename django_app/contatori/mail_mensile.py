"""Mail di riepilogo delle letture mensili MFC.

Una mail quando tutte le MFC attive con IP hanno la lettura del mese; se al
giro finale del recupero (giorno ``GIORNI_RECUPERO_MENSILE`` dalle 23:00) ne
manca ancora qualcuna, parte una mail con le mancanti e il motivo. La mail
«completa» parte anche dopo quella con le mancanti, se l'ultima MFC rientra.

Destinatari: solo quelli scritti in «Configura mail» del lavoro pianificato
(``SiteConfig`` ``contatori_letture_mensili_emails``). Nessun ripiego su
amministratori o superuser: lista vuota = nessun invio.
"""
from __future__ import annotations

import io
from datetime import timedelta
import logging
from html import escape

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from .models import LetturaMensileContatori, Macchina
from .services import CONTATORI, GIORNI_RECUPERO_MENSILE, copie_mensili

logger = logging.getLogger(__name__)

TASK_NAME = "contatori_letture_mensili"
CHIAVE_DESTINATARI = "contatori_letture_mensili_emails"
CHIAVE_STATO = "contatori_letture_mensili_mail_stato"
ORA_ULTIMO_GIRO = 23

COMPLETA = "completa"
PARZIALE = "parziale"


def _stato_inviato(mese):
    """Esito già inviato per il mese: "", PARZIALE o COMPLETA."""
    from core.models import SiteConfig

    valore = SiteConfig.get(CHIAVE_STATO, "")
    prefisso, _, esito = valore.partition(":")
    return esito if prefisso == f"{mese:%Y-%m}" else ""


def _segna_inviato(mese, esito):
    from core.models import SiteConfig

    # update_or_create e non SiteConfig.set: in contatori ogni «.set()» è vietato dal
    # test di sola lettura SNMP (tests_snmp_capture), che non distingue gli oggetti.
    SiteConfig.objects.update_or_create(chiave=CHIAVE_STATO, defaults={
        "valore": f"{mese:%Y-%m}:{esito}",
        "descrizione": "Ultima mail delle letture mensili MFC (mese:esito)"})


def destinatari():
    from core.models import SiteConfig
    from core.reminder_recipients import split_emails

    return split_emails(SiteConfig.get(CHIAVE_DESTINATARI, ""))


def riepilogo(mese):
    """Letture del mese con le copie rispetto al mese prima e MFC mancanti."""
    macchine = list(Macchina.objects.filter(attiva=True, host__isnull=False).order_by("reparto", "matricola"))
    letture = {l.macchina_id: l for l in LetturaMensileContatori.objects.filter(
        mese=mese, macchina__in=macchine)}
    mese_prima = (mese.replace(day=1) - timedelta(days=1)).replace(day=1)
    precedenti = {l.macchina_id: l for l in LetturaMensileContatori.objects.filter(
        mese=mese_prima, macchina__in=macchine)}
    lette, mancanti = [], []
    for m in macchine:
        lettura = letture.get(m.pk)
        if lettura is None:
            mancanti.append({"macchina": m, "motivo": (m.snmp_ultimo_errore or "").strip()
                             or "Nessuna risposta SNMP finora."})
        else:
            lette.append({"macchina": m, "lettura": lettura,
                          "copie": copie_mensili(lettura, precedenti.get(m.pk))})
    return {"mese": mese, "lette": lette, "mancanti": mancanti, "totale": len(macchine)}


def _num(valore):
    return "—" if valore is None else f"{valore:,}".replace(",", ".")


def _link_pagina():
    from core.accounts.portal_links import portal_link

    return portal_link(reverse("contatori:letture_gestisci") + "?tipo=mensili")


def componi(dati):
    """(oggetto, testo, frammento HTML) della mail."""
    mese, lette, mancanti = dati["mese"], dati["lette"], dati["mancanti"]
    etichetta = f"{mese:%m/%Y}"
    if mancanti:
        oggetto = f"Letture MFC {etichetta}: {len(lette)} di {dati['totale']}, {len(mancanti)} mancanti"
    else:
        oggetto = f"Letture MFC {etichetta}: tutte le {dati['totale']} MFC lette"
    link = _link_pagina()

    righe_testo = [oggetto, ""]
    for r in lette:
        m, l, c = r["macchina"], r["lettura"], r["copie"]
        valori = ", ".join(f"{etichetta_c} {_num(getattr(l, campo))}" for campo, etichetta_c in CONTATORI)
        copie = f" — copie del mese {_num(c['totale'])}" if c else " — copie del mese non calcolabili"
        righe_testo.append(f"- {m.reparto} ({m.matricola}), {timezone.localtime(l.rilevata_il):%d/%m %H:%M}: "
                           f"{valori}{copie}")
    if mancanti:
        righe_testo += ["", "Mancanti:"]
        righe_testo += [f"- {r['macchina'].reparto} ({r['macchina'].matricola}): {r['motivo']}" for r in mancanti]
    if link:
        righe_testo += ["", f"Letture mensili nel portale: {link}"]
    testo = "\n".join(righe_testo)

    th = "padding:6px 8px;text-align:right;border-bottom:2px solid #12395f;font-size:12px;color:#12395f"
    td = "padding:6px 8px;text-align:right;border-bottom:1px solid #e2e8f0;font-size:13px"
    intest = "".join(f"<th style='{th}'>{escape(e)}</th>" for _, e in CONTATORI)
    html = [f"<p style='margin:0 0 12px'>Letture del giorno 1 di <strong>{escape(etichetta)}</strong>: "
            f"{len(lette)} di {dati['totale']} MFC lette.</p>",
            "<table role='presentation' style='width:100%;border-collapse:collapse;margin:0 0 16px'>",
            f"<tr><th style='{th};text-align:left'>MFC</th><th style='{th};text-align:left'>Letta il</th>"
            f"{intest}<th style='{th}'>Copie del mese</th></tr>"]
    for r in lette:
        m, l, c = r["macchina"], r["lettura"], r["copie"]
        celle = "".join(f"<td style='{td}'>{_num(getattr(l, campo))}"
                        + (f"<br><span style='color:#64748b;font-size:11px'>+{_num(c[campo])}</span>" if c else "")
                        + "</td>" for campo, _ in CONTATORI)
        html.append(f"<tr><td style='{td};text-align:left'><strong>{escape(m.reparto)}</strong><br>"
                    f"<span style='color:#64748b;font-size:11px'>{escape(m.matricola)}</span></td>"
                    f"<td style='{td};text-align:left'>{timezone.localtime(l.rilevata_il):%d/%m %H:%M}</td>{celle}"
                    f"<td style='{td}'><strong>{_num(c['totale']) if c else '—'}</strong></td></tr>")
    html.append("</table>")
    if mancanti:
        html.append("<p style='margin:0 0 6px;color:#b91c1c'><strong>Mancanti</strong></p><ul style='margin:0 0 16px;padding-left:18px;font-size:13px'>")
        html += [f"<li><strong>{escape(r['macchina'].reparto)}</strong> ({escape(r['macchina'].matricola)}): "
                 f"{escape(r['motivo'])}</li>" for r in mancanti]
        html.append("</ul>")
    html.append("<p style='margin:0 0 12px;color:#64748b;font-size:12px'>«Copie del mese» = differenza con la "
                "lettura del mese prima; «—» se quella lettura manca o un contatore è sceso. "
                "In allegato le letture in Excel.</p>")
    if link:
        html.append(f"<p style='margin:0'><a href='{escape(link)}'>Apri le letture mensili nel portale</a></p>")
    return oggetto, testo, "".join(html)


def notifica(mese, *, ultimo_giro=False):
    """Invia la mail se è il momento e non è già partita. Ritorna l'esito inviato o ""."""
    dati = riepilogo(mese)
    if not dati["totale"]:
        return ""
    esito = COMPLETA if not dati["mancanti"] else (PARZIALE if ultimo_giro else "")
    if not esito:
        return ""
    gia = _stato_inviato(mese)
    if gia == COMPLETA or gia == esito:
        return ""
    elenco = destinatari()
    if not elenco:
        logger.info("contatori: mail letture mensili %s non inviata, nessun destinatario configurato", mese)
        return ""
    # Due letture che finiscono insieme non devono mandare due mail.
    chiave_lock = f"contatori:mail_mensile:{mese:%Y-%m}"
    if not cache.add(chiave_lock, True, timeout=300):
        return ""
    try:
        if _stato_inviato(mese) in (COMPLETA, esito):
            return ""
        from automazioni.mail_config import apply_mail_overrides
        from core.email_utils import send_hub_mail

        from .export import letture_mensili_xlsx

        oggetto, testo, frammento = componi(dati)
        oggetto, testo, frammento, nota = apply_mail_overrides(
            TASK_NAME, subject=oggetto, body_text=testo, fragment=frammento)
        buffer = io.BytesIO()
        letture_mensili_xlsx(dati).save(buffer)
        send_hub_mail(
            oggetto, testo, elenco,
            email_type="Contatori", section_label="Letture mensili MFC",
            body_html_fragment=frammento, footer_note=nota,
            attachments=[(f"letture_mfc_{mese:%Y-%m}.xlsx", buffer.getvalue(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
        )
        _segna_inviato(mese, esito)
        logger.info("contatori: mail letture mensili %s inviata (%s) a %d destinatari", mese, esito, len(elenco))
        return esito
    finally:
        cache.delete(chiave_lock)


def e_ultimo_giro(adesso=None):
    """Ultimi giri del recupero: giorno GIORNI_RECUPERO_MENSILE (o dopo) dalle 23:00."""
    adesso = timezone.localtime(adesso)
    return adesso.day > GIORNI_RECUPERO_MENSILE or (
        adesso.day == GIORNI_RECUPERO_MENSILE and adesso.hour >= ORA_ULTIMO_GIRO)
