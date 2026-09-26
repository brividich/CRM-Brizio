"""Task periodici django-q2 per il modulo anomalie.

Registrati via automazioni.schedules + setup_q_schedules.
"""
from __future__ import annotations

import logging

from automazioni.system_runlog import system_job_run

logger = logging.getLogger("anomalie.tasks")


@system_job_run("anomalie_pending_notifications")
def run_anomalie_pending_notifications(threshold_minutes: int = 5) -> dict:
    """Invia le mail di conferma per gli OP con modifiche ferme da > threshold_minutes.

    Fallback al tasto 'Salva e notifica': se l'operatore dimentica di notificare,
    la mail di riepilogo parte comunque dopo la soglia di inattività.
    """
    from anomalie.mail_action_service import flush_pending_update_notifications

    try:
        result = flush_pending_update_notifications(threshold_minutes=threshold_minutes)
        if result.get("sent"):
            logger.info(
                "run_anomalie_pending_notifications: inviate=%s controllate=%s",
                result.get("sent"),
                result.get("checked"),
            )
        # Visibilità sui fallimenti (no invii persi in silenzio): finiscono anche
        # nel result_message di AutomationRunLog.
        if result.get("failed") or result.get("given_up"):
            logger.warning(
                "run_anomalie_pending_notifications: falliti=%s dead_letter=%s controllate=%s",
                result.get("failed"),
                result.get("given_up"),
                result.get("checked"),
            )
        return result
    except Exception:
        logger.exception("run_anomalie_pending_notifications: eccezione inattesa")
        raise


@system_job_run("anomalie_cleanup_allegati")
def run_anomalie_cleanup_allegati(*, older_than_days: int = 30, limit: int = 500) -> dict:
    """Pulizia schedulata delle cartelle allegati orfane (id non più in tabella anomalie).

    Esegue il management command `cleanup_anomalie_allegati` in modalità eliminazione,
    limitata alle cartelle ferme da oltre `older_than_days` giorni (conservativo) e a
    un massimo di `limit` cartelle per run. Idempotente: i run successivi non rivedono
    le cartelle già rimosse. Ritorna {"older_than_days", "limit"} per il run-log.
    """
    from io import StringIO

    from django.core.management import call_command

    buf = StringIO()
    call_command(
        "cleanup_anomalie_allegati",
        delete=True,
        older_than_days=older_than_days,
        limit=limit,
        stdout=buf,
    )
    out = buf.getvalue().strip()
    if out:
        logger.info("run_anomalie_cleanup_allegati: %s", out.replace("\n", " | "))
    return {"older_than_days": older_than_days, "limit": limit}


@system_job_run("anomalie_escalation")
def run_anomalie_escalation(*, force_email: bool = False) -> dict:
    """Promemoria + escalation per gli OP con anomalie 'In attesa' (da controllare).

    Eseguito orariamente. A ogni run:
    - aggiorna SEMPRE i promemoria in dashboard (core.Notifica) per CC/CAR degli OP
      con anomalie da gestire (promemoria immediato, evidenziato se oltre soglia);
    - invia il RESOCONTO email aggregato solo se `attivo` è on e siamo nel giorno
      lavorativo (lun-ven) all'`ora_invio` configurata — oppure se `force_email=True`.

    Nello stesso run girano le automazioni aggiuntive accese da Configurazione
    (vedi anomalie.automazioni_service): RDC senza numero, difetto ricorrente per P/N,
    OP completato e, il lunedi' all'ora del resoconto, il digest settimanale.

    Ritorna {"reminders": n, "email_sent": bool, "op_da_controllare": m, "op_over": k, ...}.
    """
    from django.utils import timezone

    from anomalie import automazioni_service as auto
    from anomalie.automation_models import AnomalieAutomazioneMarker
    from anomalie.escalation_config import get_escalation_config
    from anomalie.mail_action_service import (
        _fetch_op_da_controllare,
        create_dashboard_reminders,
        send_escalation_resoconto,
    )

    cfg = get_escalation_config()
    soglia = int(cfg["soglia_ore"])
    out = {
        "reminders": 0, "email_sent": False, "op_da_controllare": 0, "op_over": 0,
        "rdc_op": 0, "rdc_reminders": 0, "ricorrenze": 0, "op_completati": 0, "digest_sent": False,
    }

    try:
        op_rows = _fetch_op_da_controllare(soglia, strict=True)
    except Exception:
        logger.exception("run_anomalie_escalation: fetch OP fallito")
        return out

    out["op_da_controllare"] = len(op_rows)
    out["op_over"] = sum(1 for op in op_rows if op.get("over_threshold"))

    # 1) Promemoria dashboard: sempre (anche sotto soglia); chiude quelli superati
    try:
        out["reminders"] = create_dashboard_reminders(op_rows, soglia_ore=soglia)
    except Exception:
        logger.exception("run_anomalie_escalation: reminders falliti")

    # 1b) RDC richiesto senza numero: promemoria a CC/CAR + sezione nel resoconto
    rdc_rows: list[dict] = []
    if cfg["rdc_attivo"]:
        try:
            rdc_rows = auto.find_rdc_senza_numero(giorni=int(cfg["rdc_giorni"]))
            out["rdc_op"] = len(rdc_rows)
            out["rdc_reminders"] = auto.sync_rdc_reminders(rdc_rows)
        except Exception:
            logger.exception("run_anomalie_escalation: automazione RDC fallita")

    # 2) Email resoconto: solo on + giorno lavorativo + ora di invio (o forzata),
    #    una sola volta al giorno anche se il task gira due volte nella stessa ora.
    now = timezone.localtime(timezone.now())
    is_send_window = (
        cfg["attivo"]
        and now.weekday() < 5  # lun(0)..ven(4)
        and now.hour == int(cfg["ora_invio"])
    )
    oggi = now.date().isoformat()
    already_sent = AnomalieAutomazioneMarker.objects.filter(
        tipo=AnomalieAutomazioneMarker.Tipo.RESOCONTO, chiave=oggi,
    ).exists()
    if force_email or (is_send_window and not already_sent):
        try:
            out["email_sent"] = send_escalation_resoconto(
                op_rows, soglia_ore=soglia, rdc_rows=rdc_rows, rdc_giorni=int(cfg["rdc_giorni"]),
            )
            if out["email_sent"] and not force_email:
                AnomalieAutomazioneMarker.objects.create(
                    tipo=AnomalieAutomazioneMarker.Tipo.RESOCONTO, chiave=oggi,
                    dettaglio={"op": out["op_over"], "rdc": out["rdc_op"]},
                )
        except Exception:
            logger.exception("run_anomalie_escalation: invio resoconto fallito")

    # 3) Difetto ricorrente per P/N
    if cfg["ricorrenza_attivo"]:
        try:
            out["ricorrenze"] = auto.notify_ricorrenze_pn(
                soglia_n=int(cfg["ricorrenza_n"]), giorni=int(cfg["ricorrenza_giorni"]),
            )
        except Exception:
            logger.exception("run_anomalie_escalation: automazione ricorrenza P/N fallita")

    # 4) OP completato (rete di sicurezza: di norma parte dal flush delle modifiche)
    if cfg["op_completato_attivo"]:
        try:
            out["op_completati"] = auto.notify_op_completati()
        except Exception:
            logger.exception("run_anomalie_escalation: automazione OP completato fallita")

    # 5) Digest settimanale: lunedi' all'ora del resoconto
    if cfg["digest_attivo"] and now.weekday() == 0 and now.hour == int(cfg["ora_invio"]):
        try:
            out["digest_sent"] = auto.send_digest(soglia_ore=soglia)
        except Exception:
            logger.exception("run_anomalie_escalation: digest settimanale fallito")

    if any(out[k] for k in ("reminders", "email_sent", "rdc_reminders", "ricorrenze", "op_completati", "digest_sent")):
        logger.info("run_anomalie_escalation: %s", out)
    return out
