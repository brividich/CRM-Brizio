"""Task periodici django-q2 del modulo anagrafica.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_idoneita_digest(only_ko: bool = False) -> dict:
    """Digest "idoneità alla mansione" (non idonei / con riserve) per RSPP /
    medico competente / HR.

    Wrappa il management command ``send_idoneita_digest``. È **fail-safe**: se non
    ci sono destinatari configurati (``SiteConfig.idoneita_reminder_emails``) il
    comando non invia nulla e lo schedule resta un no-op, quindi è sicuro tenerlo
    sempre attivo. Privacy: nessun dato clinico (vedi il management command).
    """
    from django.core.management import call_command

    try:
        call_command("send_idoneita_digest", only_ko=only_ko, verbosity=0)
        return {"ok": True, "only_ko": bool(only_ko)}
    except Exception:
        logger.exception("run_idoneita_digest: eccezione inattesa")
        raise


def run_formazione_session_reminders(days: list | None = None) -> dict:
    """Promemoria email + invito calendario (.ics) per le sessioni formative imminenti.

    Wrappa il management command ``send_formazione_session_reminders`` (default T-7 e
    T-1). Fail-safe: senza email di notifica l'iscritto riceve solo la notifica in-app.
    """
    from django.core.management import call_command

    try:
        kwargs = {"verbosity": 0}
        if days:
            kwargs["days"] = list(days)
        call_command("send_formazione_session_reminders", **kwargs)
        return {"ok": True, "days": list(days) if days else [7, 1]}
    except Exception:
        logger.exception("run_formazione_session_reminders: eccezione inattesa")
        raise


def run_archivia_attestati_mancanti(limit: int = 500) -> dict:
    """Archivia nel box documenti gli attestati mancanti per i completamenti.

    Tiene allineato l'archivio anche se un auto-save a fine corso è fallito o se
    l'archiviazione automatica è stata attivata dopo che c'erano già completamenti.

    **Opt-in / fail-safe**: no-op se il salvataggio automatico è disattivato
    (`AttestatoFormazioneConfig.auto_salva_attestato`), coerente con le
    impostazioni; un errore sul singolo record non blocca gli altri.
    """
    from anagrafica.models import DocumentoDipendente
    from anagrafica.models_formazione import AttestatoFormazioneConfig, TrainingEmployeeRecord
    from anagrafica.services.attestato_pdf import RIFERIMENTO_TIPO, archivia_attestato

    cfg = AttestatoFormazioneConfig.get_instance()
    if not cfg.auto_salva_attestato:
        return {"ok": True, "skipped": "auto_salva_attestato disattivato", "archiviati": 0}

    gia_archiviati = DocumentoDipendente.objects.filter(
        oggetto_riferimento_tipo=RIFERIMENTO_TIPO
    ).values_list("oggetto_riferimento_id", flat=True)
    mancanti = list(
        TrainingEmployeeRecord.objects.exclude(pk__in=gia_archiviati)
        .order_by("-data_completamento", "-id")[:limit]
    )

    ok = err = 0
    for rec in mancanti:
        try:
            archivia_attestato(rec, cfg=cfg, user=None)
            ok += 1
        except Exception:
            err += 1
            logger.exception("run_archivia_attestati_mancanti: errore record %s", rec.pk)

    return {"ok": True, "archiviati": ok, "errori": err, "residui": len(mancanti) >= limit}
