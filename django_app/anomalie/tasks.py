"""Task periodici django-q2 per il modulo anomalie.

Registrati via automazioni.schedules + setup_q_schedules.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("anomalie.tasks")


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
        return result
    except Exception:
        logger.exception("run_anomalie_pending_notifications: eccezione inattesa")
        raise


def run_anomalie_escalation(*, force_email: bool = False) -> dict:
    """Promemoria + escalation per gli OP con anomalie 'In attesa' (da controllare).

    Eseguito orariamente. A ogni run:
    - aggiorna SEMPRE i promemoria in dashboard (core.Notifica) per CC/CAR degli OP
      con anomalie da gestire (promemoria immediato, evidenziato se oltre soglia);
    - invia il RESOCONTO email aggregato solo se `attivo` è on e siamo nel giorno
      lavorativo (lun-ven) all'`ora_invio` configurata — oppure se `force_email=True`.

    Ritorna {"reminders": n, "email_sent": bool, "op_da_controllare": m, "op_over": k}.
    """
    from django.utils import timezone

    from anomalie.escalation_config import get_escalation_config
    from anomalie.mail_action_service import (
        _fetch_op_da_controllare,
        create_dashboard_reminders,
        send_escalation_resoconto,
    )

    cfg = get_escalation_config()
    soglia = int(cfg["soglia_ore"])
    out = {"reminders": 0, "email_sent": False, "op_da_controllare": 0, "op_over": 0}

    try:
        op_rows = _fetch_op_da_controllare(soglia)
    except Exception:
        logger.exception("run_anomalie_escalation: fetch OP fallito")
        return out

    out["op_da_controllare"] = len(op_rows)
    out["op_over"] = sum(1 for op in op_rows if op.get("over_threshold"))

    # 1) Promemoria dashboard: sempre (anche sotto soglia)
    try:
        out["reminders"] = create_dashboard_reminders(op_rows, soglia_ore=soglia)
    except Exception:
        logger.exception("run_anomalie_escalation: reminders falliti")

    # 2) Email resoconto: solo on + giorno lavorativo + ora di invio (o forzata)
    now = timezone.localtime(timezone.now())
    is_send_window = (
        cfg["attivo"]
        and now.weekday() < 5  # lun(0)..ven(4)
        and now.hour == int(cfg["ora_invio"])
    )
    if force_email or is_send_window:
        try:
            out["email_sent"] = send_escalation_resoconto(op_rows, soglia_ore=soglia)
        except Exception:
            logger.exception("run_anomalie_escalation: invio resoconto fallito")

    if out["reminders"] or out["email_sent"]:
        logger.info(
            "run_anomalie_escalation: reminders=%s email_sent=%s op=%s over=%s",
            out["reminders"], out["email_sent"], out["op_da_controllare"], out["op_over"],
        )
    return out
