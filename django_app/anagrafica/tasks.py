"""Task periodici django-q2 del modulo anagrafica.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_attiva_assegnazioni_programmate() -> dict:
    """Applica gli spostamenti organizzativi la cui decorrenza è arrivata.

    Uno spostamento registrato con data futura resta *programmato*: il portale
    continua a vedere reparto/mansione vecchi finché questo task, la mattina
    della decorrenza, non allinea i campi vivi del dipendente.

    Idempotente (salta le assegnazioni già attivate) e resiliente: un errore su
    una persona non blocca le altre, così un dato sporco non ferma tutti gli
    spostamenti del giorno.
    """
    from .services.assegnazioni import attiva_programmate_scadute

    try:
        esito = attiva_programmate_scadute()
        if esito["attivate"] or esito["errori"]:
            logger.info(
                "run_attiva_assegnazioni_programmate: %s attivate, %s errori",
                esito["attivate"], esito["errori"],
            )
        return esito
    except Exception:
        logger.exception("run_attiva_assegnazioni_programmate: eccezione inattesa")
        raise


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


def run_visite_expiry_reminders(days: int = 60) -> dict:
    """Reminder visite mediche scadute/in scadenza (digest HR + notifica al dipendente).

    Wrappa ``send_visite_expiry_reminders``. **Fail-safe**: senza destinatari
    configurati (``SiteConfig.visite_reminder_emails``) è un no-op, quindi sicuro
    da tenere sempre attivo.
    """
    from django.core.management import call_command

    try:
        call_command("send_visite_expiry_reminders", days=days, verbosity=0)
        return {"ok": True, "days": int(days)}
    except Exception:
        logger.exception("run_visite_expiry_reminders: eccezione inattesa")
        raise


def run_contratti_expiry_reminders(days: int = 60, prova_days: int = 15) -> dict:
    """Reminder contratti a termine + periodi di prova in scadenza (digest HR).

    Wrappa ``send_contratti_expiry_reminders``. **Fail-safe**: senza destinatari
    (``SiteConfig.contratti_reminder_emails``) è un no-op.
    """
    from django.core.management import call_command

    try:
        call_command("send_contratti_expiry_reminders", days=days,
                     prova_days=prova_days, verbosity=0)
        return {"ok": True, "days": int(days), "prova_days": int(prova_days)}
    except Exception:
        logger.exception("run_contratti_expiry_reminders: eccezione inattesa")
        raise


def run_formazione_audit_digest(days: int = 90) -> dict:
    """Digest trimestrale formazione (abilitazioni in scadenza) per audit ISO.

    Wrappa ``send_formazione_audit_digest``. **Fail-safe** (no-op senza destinatari).
    NB: i destinatari attuali sono ADMINS/superuser finché non si configura una
    fonte HR/RSPP dedicata (vedi il management command).
    """
    from django.core.management import call_command

    try:
        call_command("send_formazione_audit_digest", days=days, verbosity=0)
        return {"ok": True, "days": int(days)}
    except Exception:
        logger.exception("run_formazione_audit_digest: eccezione inattesa")
        raise


def run_visite_mediche_digest(days: int = 60) -> dict:
    """Digest mensile visite mediche in scadenza (HR).

    Wrappa ``send_visite_mediche_digest``. **Fail-safe**. È in parte ridondante con
    ``run_visite_expiry_reminders`` (disattivabile dalla Centrale di comando);
    destinatari attuali = ADMINS/superuser.
    """
    from django.core.management import call_command

    try:
        call_command("send_visite_mediche_digest", days=days, verbosity=0)
        return {"ok": True, "days": int(days)}
    except Exception:
        logger.exception("run_visite_mediche_digest: eccezione inattesa")
        raise


def run_elearning_reminders() -> dict:
    """Promemoria micro-corsi e-learning non completati (digest HR + notifica in-app).

    Wrappa ``send_elearning_reminders``. Le notifiche in-app partono comunque; il
    digest email è **fail-safe** (no-op senza ``SiteConfig.elearning_reminder_emails``).
    """
    from django.core.management import call_command

    try:
        call_command("send_elearning_reminders", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_elearning_reminders: eccezione inattesa")
        raise


def run_training_expiry_reminders(days: int = 60) -> dict:
    """Reminder scadenze formazione (corsi scaduti/in scadenza): digest HR + notifica.

    Wrappa ``send_training_expiry_reminders``. **Fail-safe**: senza destinatari
    (``SiteConfig.training_reminder_emails``) il digest è un no-op; le notifiche
    in-app al dipendente partono comunque.
    """
    from django.core.management import call_command

    try:
        call_command("send_training_expiry_reminders", days=days, verbosity=0)
        return {"ok": True, "days": int(days)}
    except Exception:
        logger.exception("run_training_expiry_reminders: eccezione inattesa")
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


def run_intake_scansioni_formazione(limit: int | None = None) -> dict:
    """Passa in rassegna la cartella dove la fotocopiatrice deposita i fogli firme.

    **Opt-in / fail-safe**: no-op se l'acquisizione è spenta
    (`TrainingScanIntakeConfig.attiva`) o se la cartella non è raggiungibile —
    una share di rete che non risponde è un contrattempo, non un guasto del
    portale. Un errore sul singolo file non ferma gli altri.
    """
    from anagrafica.services.intake_scansioni import elabora_cartella

    try:
        esito = elabora_cartella(limite=limit)
    except Exception:
        logger.exception("run_intake_scansioni_formazione: passaggio fallito")
        return {"ok": False, "riepilogo": "Errore nel passaggio sulla cartella"}
    return {"ok": True, **esito}


def run_intake_referti_sanitari(limit: int | None = None) -> dict:
    """Passa in rassegna la cartella dei referti di sorveglianza sanitaria.

    **Opt-in / fail-safe**, come l'acquisizione dei fogli firme: no-op se è spenta
    (`RefertoIntakeConfig.attiva`) o se la cartella non risponde.

    Differenza sostanziale rispetto ai fogli firme: lì il QR identifica il
    documento con certezza, qui il dipendente va *riconosciuto*. Perciò l'esito
    normale di questo passaggio non è «registrato» ma «in coda»: le visite si
    scrivono solo quando la conferma automatica è accesa e nulla è dubbio.
    """
    from anagrafica.services.referti_intake import elabora_cartella

    try:
        esito = elabora_cartella(limite=limit)
    except Exception:
        logger.exception("run_intake_referti_sanitari: passaggio fallito")
        return {"ok": False, "riepilogo": "Errore nel passaggio sulla cartella"}
    return {"ok": True, **esito}
