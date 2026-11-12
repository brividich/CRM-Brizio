"""Lavori periodici (django-q, ``automazioni/schedules.py``). Attivi solo con ``RECEPTION_NATIVA=1``.

Prendono il posto degli script sul server del GuestPortal: ``mail_worker.php`` (avviso al referente),
``prereg_cleanup.php``. La cancellazione dopo 12 mesi nel GuestPortal non esisteva: si faceva a mano.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from . import servizi
from .models import Visita

logger = logging.getLogger(__name__)


def _attiva() -> bool:
    return bool(getattr(settings, "RECEPTION_NATIVA", False))


def invia_avvisi_referenti() -> dict:
    from core.email_utils import send_hub_mail

    esito = {"inviate": 0, "fallite": 0}
    # La riga si prende con un UPDATE condizionato: due giri insieme non mandano la mail due volte.
    for visita in Visita.objects.select_related("ospite").filter(mail_stato=Visita.MAIL_DA_INVIARE).order_by("ingresso")[:50]:
        if not Visita.objects.filter(pk=visita.pk, mail_stato=Visita.MAIL_DA_INVIARE).update(mail_stato=Visita.MAIL_IN_CORSO):
            continue
        if "@" not in visita.referente_email:
            Visita.objects.filter(pk=visita.pk).update(mail_stato=Visita.MAIL_FALLITA)
            esito["fallite"] += 1
            continue
        ora = timezone.localtime(visita.ingresso).strftime("%H:%M del %d/%m/%Y") if visita.ingresso else "adesso"
        azienda = visita.ospite.azienda or "non indicata"
        testo = (f"{visita.ospite.nome_completo} è arrivato in reception alle {ora}.\n"
                 f"Azienda: {azienda}\nMotivo: {visita.motivo or 'non indicato'}\nCartellino: {visita.cartellino}")
        try:
            send_hub_mail(f"Visitatore in reception: {visita.ospite.nome_completo}", testo, [visita.referente_email],
                          title="Un visitatore ti aspetta in reception", email_type="Reception")
        except Exception:  # noqa: BLE001 - una mail che non parte non ferma le altre
            logger.exception("Avviso al referente non inviato (visita %s)", visita.pk)
            Visita.objects.filter(pk=visita.pk).update(mail_stato=Visita.MAIL_FALLITA)
            esito["fallite"] += 1
            continue
        Visita.objects.filter(pk=visita.pk).update(mail_stato=Visita.MAIL_INVIATA)
        esito["inviate"] += 1
    return esito


def run_avvisi_referenti():
    if not _attiva():
        return {"ok": True, "saltato": "reception non attiva"}
    try:
        return {"ok": True, **invia_avvisi_referenti()}
    except Exception:
        logger.exception("Avvisi ai referenti falliti")
        return {"ok": False}


def run_pulizia():
    """Ogni notte: pre-registrazioni passate, richieste di appuntamento scadute e dati oltre il termine dell'informativa."""
    if not _attiva():
        return {"ok": True, "saltato": "reception non attiva"}
    try:
        mesi = int(getattr(settings, "RECEPTION_CONSERVAZIONE_MESI", 12))
        esito = {"preregistrazioni_passate": servizi.pulizia_preregistrazioni(), "richieste": servizi.pulizia_richieste(),
                 **servizi.pulizia_conservazione(mesi)}
    except Exception:
        logger.exception("Pulizia della reception fallita")
        return {"ok": False}
    logger.info("Pulizia reception: %s", esito)
    return {"ok": True, **esito}
