"""
django-q2 task functions per i background job delle automazioni.

Queste funzioni vengono referenziate dai Schedule django-q e devono
restare importabili senza side effect (nessuna logica al modulo-level).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("automazioni.tasks")


def run_automation_queue(
    limit: int = 50,
    source_code: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Processa la queue SQL automation_event_queue."""
    from monitoring.models import AutomationExecution
    from automazioni.management.commands.process_automation_queue import _monitored_process_queue

    try:
        summary = _monitored_process_queue(
            limit=limit,
            source_code=source_code,
            dry_run=dry_run,
            monitoring_trigger_type=AutomationExecution.TriggerType.SCHEDULER,
        ) or {}
        logger.info(
            "run_automation_queue: fetched=%s done=%s error=%s rule_runs=%s",
            summary.get("fetched", 0),
            summary.get("done", 0),
            summary.get("error", 0),
            summary.get("rule_runs", 0),
        )
        return summary
    except Exception:
        logger.exception("run_automation_queue: eccezione inattesa")
        raise


def run_report_scadenze_settimanale(
    giorni: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Check schedulato visite mediche / contratti in scadenza con invio email ai referenti.

    Parametri (giorni, categorie, destinatari, on/off) si leggono da SiteConfig,
    configurabili dalla pagina Impostazioni automazioni. 'giorni' qui e' solo un
    override opzionale; di norma None -> usa il valore della UI.
    """
    from monitoring.models import AutomationExecution
    from automazioni.management.commands.report_scadenze_settimanale import _monitored_report

    try:
        summary = _monitored_report(
            giorni=giorni,
            dry_run=dry_run,
            monitoring_trigger_type=AutomationExecution.TriggerType.SCHEDULER,
        ) or {}
        logger.info(
            "run_report_scadenze_settimanale: visite=%s contratti=%s",
            (summary.get("visite") or {}).get("count", 0),
            (summary.get("contratti") or {}).get("count", 0),
        )
        return summary
    except Exception:
        logger.exception("run_report_scadenze_settimanale: eccezione inattesa")
        raise


def run_approval_mailbox(
    limit: int = 25,
    dry_run: bool = False,
) -> dict:
    """Legge la mailbox approvazioni via Graph e processa le risposte."""
    from automazioni.mailbox_graph import get_graph_mailbox_config, poll_graph_mailbox

    config = get_graph_mailbox_config()
    if not config.get("is_ready"):
        missing = ", ".join(config.get("missing_fields", []))
        logger.warning("run_approval_mailbox: configurazione Graph incompleta — mancano %s", missing)
        return {"skipped": True, "reason": "config_incomplete", "missing": missing}

    try:
        result = poll_graph_mailbox(limit=limit, dry_run=dry_run)
        logger.info(
            "run_approval_mailbox: read=%s processed=%s approved=%s rejected=%s error=%s",
            result.read,
            result.processed,
            result.approved,
            result.rejected,
            result.error,
        )
        return {
            "read": result.read,
            "processed": result.processed,
            "approved": result.approved,
            "rejected": result.rejected,
            "ignored": result.ignored,
            "deduped": result.deduped,
            "error": result.error,
        }
    except Exception:
        logger.exception("run_approval_mailbox: eccezione inattesa")
        raise


def run_cleanup_run_logs() -> dict:
    """Retention giornaliera dei RunLog automazioni (GDPR - limitazione conservazione).

    Elimina i RunLog oltre la finestra configurata (SiteConfig, default 90 giorni).
    Wrappa il management command cleanup_run_logs in modalita' --apply.
    """
    from django.core.management import call_command

    try:
        call_command("cleanup_run_logs", apply=True, verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_cleanup_run_logs: eccezione inattesa")
        raise


def run_approval_branch_task(approval_id: int) -> dict:
    """Esegue il ramo di una decisione di approvazione presa dalla pagina web.

    La pagina registra la decisione e accoda questo task: l'approvatore riceve
    subito la risposta. Presa in carico condizionata come in
    ``recover_approval_branches``: un ramo non viene eseguito due volte in parallelo.
    """
    from django.utils import timezone

    from automazioni.models import AutomationApproval
    from automazioni.services import run_approval_branch

    approval = (
        AutomationApproval.objects.select_related("run_log__rule", "action")
        .filter(pk=int(approval_id))
        .first()
    )
    if approval is None or approval.branch_status != AutomationApproval.BranchStatus.RUNNING:
        return {"skipped": True, "approval_id": int(approval_id)}
    claimed = AutomationApproval.objects.filter(
        pk=approval.pk,
        branch_status=AutomationApproval.BranchStatus.RUNNING,
        branch_updated_at=approval.branch_updated_at,
    ).update(branch_updated_at=timezone.now())
    if not claimed:
        return {"skipped": True, "approval_id": approval.pk}
    result = run_approval_branch(approval)
    logger.info(
        "run_approval_branch_task: approvazione #%s azioni=%s errori=%s",
        approval.pk,
        result.get("actions_run"),
        result.get("actions_errors"),
    )
    return {"approval_id": approval.pk, **result}


def run_queue_event_task(queue_id: int) -> dict:
    """«Riprova» dalla pagina della coda: elabora l'evento nel cluster, non nella richiesta web."""
    from automazioni.services import process_single_queue_event_by_id

    result = process_single_queue_event_by_id(int(queue_id))
    logger.info(
        "run_queue_event_task: evento %s stato=%s regole=%s",
        queue_id,
        result.get("status"),
        result.get("rule_runs"),
    )
    return result
