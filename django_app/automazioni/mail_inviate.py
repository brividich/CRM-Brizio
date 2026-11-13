"""Registro «Mail inviate»: una riga per ogni mail partita, con esito.

Ogni ``EmailMessage.send`` del portale scrive la sua riga da sé (``core.mail_registro``,
origine «modulo»). Le azioni delle automazioni, le mail dirette delle assenze, le mail
Anomalie e ``core.email_utils.send_hub_mail`` chiamano poi :func:`registra`, che
completa quella riga con tipo di mail, regola, run log e richiesta. Best-effort:
un errore di scrittura viene solo loggato, l'invio non ne risente.
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction

logger = logging.getLogger(__name__)

ORIGINI = {
    "automazione": "Automazione",
    "modulo": "Mail dei moduli",
    "hub": "Promemoria e avvisi dei moduli",
    "approvazione": "Richiesta di approvazione",
    "assenze_modifica": "Assenze · richiesta modificata",
    "assenze_eliminazione": "Assenze · richiesta eliminata",
    "assenze_sollecito": "Assenze · sollecito al capo",
    "assenze_esito": "Assenze · esito al dipendente",
    "assenze_certificato": "Assenze · certificato medico mancante",
    # Modulo Anomalie: "anomalie_" + AnomalieEmailLog.Kind.
    "anomalie_mail_action": "Anomalie · link di decisione al capocommessa",
    "anomalie_conferma_aggiornamenti": "Anomalie · conferma aggiornamenti",
    "anomalie_escalation_resoconto": "Anomalie · resoconto escalation",
    "anomalie_ricorrenza_pn": "Anomalie · difetto ricorrente per P/N",
    "anomalie_digest_settimanale": "Anomalie · digest settimanale",
    "anomalie_op_completato": "Anomalie · OP completato",
    "anomalie_alert_admin": "Anomalie · avviso invio non riuscito",
    "anomalie_altro": "Anomalie · altre mail",
}


def _elenco(indirizzi: Iterable[str] | str | None) -> str:
    if not indirizzi:
        return ""
    if isinstance(indirizzi, str):
        indirizzi = [indirizzi]
    return ", ".join(dict.fromkeys(str(i).strip().lower() for i in indirizzi if str(i or "").strip()))


def _crea_riga(*, origine, destinatari, oggetto="", copia=None, sorgente="", record_id=None,
               errore="", regola=None, run_log=None):
    """Crea la riga (savepoint); None se la scrittura fallisce."""
    try:
        from .models import EmailInviata

        with transaction.atomic():
            return EmailInviata.objects.create(
                origine=str(origine)[:40],
                sorgente=str(sorgente or "")[:60],
                record_id="" if record_id in (None, "") else str(record_id)[:60],
                destinatari=_elenco(destinatari),
                copia=_elenco(copia),
                oggetto=str(oggetto or "")[:255],
                esito=EmailInviata.ESITO_ERRORE if errore else EmailInviata.ESITO_INVIATA,
                errore=str(errore or "")[:2000],
                regola=regola if getattr(regola, "pk", None) else None,
                run_log=run_log if getattr(run_log, "pk", None) else None,
            )
    except Exception:
        logger.warning("mail_inviate: riga del registro non scritta (%s)", origine, exc_info=True)
        return None


def registra(
    *,
    origine: str,
    destinatari: Iterable[str] | str | None,
    oggetto: str = "",
    copia: Iterable[str] | str | None = None,
    sorgente: str = "",
    record_id=None,
    errore: str = "",
    regola=None,
    run_log=None,
) -> None:
    """Scrive la riga del registro, o completa quella appena scritta dall'invio. Non solleva mai."""
    try:
        from core.mail_registro import prendi_pendente

        pk = prendi_pendente(oggetto, destinatari)
    except Exception:
        pk = None
    if pk:
        try:
            from .models import EmailInviata

            campi = {"origine": str(origine)[:40]}
            if sorgente:
                campi["sorgente"] = str(sorgente)[:60]
            if record_id not in (None, ""):
                campi["record_id"] = str(record_id)[:60]
            if getattr(regola, "pk", None):
                campi["regola"] = regola
            if getattr(run_log, "pk", None):
                campi["run_log"] = run_log
            if errore:
                campi.update(esito=EmailInviata.ESITO_ERRORE, errore=str(errore)[:2000])
            with transaction.atomic():
                if EmailInviata.objects.filter(pk=pk).update(**campi):
                    return
        except Exception:
            logger.warning("mail_inviate: riga dell'invio non completata (%s)", origine, exc_info=True)
    _crea_riga(origine=origine, destinatari=destinatari, oggetto=oggetto, copia=copia, sorgente=sorgente,
               record_id=record_id, errore=errore, regola=regola, run_log=run_log)
