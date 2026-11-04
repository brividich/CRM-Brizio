"""Task django-q del modulo Presenti in azienda (schedule in ``automazioni/schedules.py``)."""
from __future__ import annotations

import logging

from django.utils import timezone

from . import impostazioni, pdf, services

logger = logging.getLogger(__name__)


def pubblica_pdf(*, forza: bool = False) -> dict:
    """Genera il PDF dei presenti e lo carica su SharePoint (se attivo nelle impostazioni)."""
    if not forza and not impostazioni.attivo("presenti_sp_attivo"):
        return {"ok": True, "saltato": True, "messaggio": "Pubblicazione su SharePoint disattivata."}
    s = services.stato(forza=True)
    if s["errore"]:
        # Mai sovrascrivere il file buono con un PDF vuoto per un problema di rete.
        esito = {"ok": False, "messaggio": f"PDF non pubblicato: {s['errore']}"}
    else:
        try:
            url = impostazioni.pubblica_su_sharepoint(pdf.genera_pdf(s["presenti"], s["aggiornato_il"]))
            esito = {"ok": True, "messaggio": f"PDF pubblicato ({len(s['presenti'])} presenti).", "url": url}
        except Exception as exc:
            logger.exception("Pubblicazione PDF presenti su SharePoint fallita")
            esito = {"ok": False, "messaggio": f"PDF non pubblicato: {exc}"}
    impostazioni.scrivi("presenti_sp_ultimo_esito",
                        f"{timezone.localtime():%d/%m/%Y %H:%M} · {esito['messaggio']}"[:250])
    return esito


def run_pubblica_pdf_presenti():
    return pubblica_pdf()


def run_avvisi_uscite_mancanti():
    from .uscite import invia_avvisi

    return invia_avvisi()
