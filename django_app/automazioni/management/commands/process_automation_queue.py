from __future__ import annotations

from django.core.management.base import BaseCommand

from automazioni.services import process_pending_queue_events
from monitoring.automation import monitored_automation
from monitoring.models import AutomationExecution


@monitored_automation(
    job_code="automazioni_process_queue",
    job_name="Processo queue automazioni",
    module_name="automazioni",
    critical=False,
    description="Processa la queue SQL automation_event_queue e invoca il runtime automazioni.",
    schedule_hint="Ogni 1-5 minuti",
    expected_max_interval_minutes=10,
    expected_max_duration_seconds=120,
    alert_after_consecutive_failures=3,
    re_raise=False,
)
def _monitored_process_queue(*, limit: int, source_code: str | None, dry_run: bool) -> dict:
    summary = process_pending_queue_events(limit=limit, source_code=source_code, dry_run=dry_run)
    mode = "dry-run" if dry_run else "run"
    return {
        **summary,
        "monitoring_message": (
            f"[{mode}] fetched={summary['fetched']} done={summary['done']} "
            f"error={summary['error']} rule_runs={summary['rule_runs']}"
        ),
        "monitoring_payload": {
            "fetched": summary["fetched"],
            "done": summary["done"],
            "error": summary["error"],
            "rule_runs": summary["rule_runs"],
            "limit": limit,
            "source_code": source_code,
            "dry_run": dry_run,
        },
    }


class Command(BaseCommand):
    help = "Processa la queue SQL automation_event_queue e invoca il runtime automazioni."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--source-code", dest="source_code", default=None)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Legge e valuta gli eventi pending senza aggiornare la queue e senza eseguire azioni runtime.",
        )
        parser.add_argument(
            "--no-monitoring",
            action="store_true",
            help="Salta la registrazione monitoring (utile per test/debug).",
        )

    def handle(self, *args, **options):
        limit = max(int(options.get("limit") or 0), 1)
        source_code = options.get("source_code") or None
        dry_run = bool(options.get("dry_run"))
        no_monitoring = bool(options.get("no_monitoring"))

        if no_monitoring:
            summary = process_pending_queue_events(limit=limit, source_code=source_code, dry_run=dry_run)
        else:
            summary = _monitored_process_queue(
                limit=limit,
                source_code=source_code,
                dry_run=dry_run,
                monitoring_trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            ) or {}

        mode_label = "dry-run" if dry_run else "run"
        self.stdout.write(
            f"[{mode_label}] fetched={summary.get('fetched', 0)} done={summary.get('done', 0)} "
            f"error={summary.get('error', 0)} rule_runs={summary.get('rule_runs', 0)}"
        )

        for event in summary.get("events", []):
            queue_id = event.get("queue_id")
            status = event.get("status")
            message = event.get("message") or ""
            candidate_rule_codes = event.get("candidate_rule_codes")
            if candidate_rule_codes is not None:
                self.stdout.write(
                    f"queue_id={queue_id} status={status} candidate_rules={','.join(candidate_rule_codes) or '-'}"
                )
            else:
                self.stdout.write(f"queue_id={queue_id} status={status} {message}".rstrip())
