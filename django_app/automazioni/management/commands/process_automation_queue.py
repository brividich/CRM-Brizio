from __future__ import annotations

from django.core.management.base import BaseCommand

from automazioni.services import process_pending_queue_events


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

    def handle(self, *args, **options):
        limit = max(int(options.get("limit") or 0), 1)
        source_code = options.get("source_code") or None
        dry_run = bool(options.get("dry_run"))

        summary = process_pending_queue_events(limit=limit, source_code=source_code, dry_run=dry_run)

        mode_label = "dry-run" if dry_run else "run"
        self.stdout.write(
            f"[{mode_label}] fetched={summary['fetched']} done={summary['done']} error={summary['error']} "
            f"rule_runs={summary['rule_runs']}"
        )

        for event in summary["events"]:
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
