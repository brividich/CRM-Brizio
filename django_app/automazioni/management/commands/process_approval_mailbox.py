"""
Management command: process_approval_mailbox

Legge la mailbox approvazioni tramite Microsoft Graph (autenticazione moderna,
no Basic Auth) e processa le risposte APPROVO / RIFIUTO.

Sostituisce poll_approval_mailbox (IMAP Basic Auth) che non funziona su
Microsoft 365 / Exchange Online dove Basic Auth è bloccata per policy.

Prerequisiti:
    - App registration Entra ID con Mail.ReadWrite (o Mail.Read) Application permission
    - Admin Consent concesso nel tenant
    - .env configurato con GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    - APPROVAL_MAILBOX_ADDRESS = mailbox da leggere
    - APPROVAL_MAILBOX_BACKEND = graph

Formato atteso email in arrivo:
    Soggetto: CMD APPROVO RID <uuid>   oppure   CMD RIFIUTO RID <uuid>
    Corpo:    CMD: APPROVO / CMD: RIFIUTO  +  RID: <uuid>  (fallback)

Utilizzo:
    python manage.py process_approval_mailbox
    python manage.py process_approval_mailbox --dry-run
    python manage.py process_approval_mailbox --limit 50 --since-hours 24
    python manage.py process_approval_mailbox --folder "Inbox" --no-mark-read
    python manage.py process_approval_mailbox --only-unread
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Legge la mailbox approvazioni via Microsoft Graph e processa "
        "le risposte APPROVO / RIFIUTO automazioni."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe elaborato senza applicare decisioni né marcare come letti.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Numero massimo di messaggi da leggere per run (default 25, max 50).",
        )
        parser.add_argument(
            "--since-hours",
            type=int,
            default=None,
            dest="since_hours",
            help="Filtra solo i messaggi ricevuti nelle ultime N ore.",
        )
        parser.add_argument(
            "--folder",
            default=None,
            help="Cartella mailbox da leggere (default: APPROVAL_MAILBOX_FOLDER da .env oppure Inbox).",
        )
        parser.add_argument(
            "--only-unread",
            action="store_true",
            default=None,
            dest="only_unread",
            help="Leggi solo messaggi non letti (sovrascrive APPROVAL_GRAPH_ONLY_UNREAD).",
        )
        parser.add_argument(
            "--mark-read",
            action="store_true",
            default=None,
            dest="mark_read",
            help="Marca come letti i messaggi processati (sovrascrive APPROVAL_GRAPH_MARK_READ).",
        )
        parser.add_argument(
            "--no-mark-read",
            action="store_false",
            dest="mark_read",
            help="Non marcare come letti i messaggi processati.",
        )

    def handle(self, *args, **options):
        from automazioni.mailbox_graph import get_graph_mailbox_config, poll_graph_mailbox

        dry_run: bool = bool(options.get("dry_run"))
        limit: int = max(1, min(int(options.get("limit") or 25), 50))
        since_hours: int | None = options.get("since_hours")
        folder: str | None = options.get("folder")
        only_unread: bool | None = options.get("only_unread")
        mark_read: bool | None = options.get("mark_read")

        config = get_graph_mailbox_config()

        if not config["is_ready"]:
            missing = ", ".join(config.get("missing_fields", []))
            raise CommandError(
                f"Configurazione Graph mailbox incompleta. Mancano: {missing}. "
                "Configurare .env con GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET "
                "e APPROVAL_MAILBOX_ADDRESS, poi impostare APPROVAL_MAILBOX_BACKEND=graph."
            )

        mode_label = "[dry-run]" if dry_run else "[run]"
        effective_folder = folder or config["folder"]
        effective_only_unread = only_unread if only_unread is not None else config["only_unread"]
        effective_mark_read = mark_read if mark_read is not None else config["mark_read"]

        self.stdout.write(
            f"{mode_label} Graph mailbox={config['mailbox']!r} "
            f"folder={effective_folder!r} "
            f"only_unread={effective_only_unread} "
            f"mark_read={effective_mark_read} "
            f"limit={limit}"
            + (f" since_hours={since_hours}" if since_hours else "")
        )

        try:
            result = poll_graph_mailbox(
                limit=limit,
                dry_run=dry_run,
                only_unread=only_unread,
                folder=folder,
                mark_read=mark_read,
                since_hours=since_hours,
            )
        except RuntimeError as exc:
            raise CommandError(f"Polling Graph fallito: {exc}") from exc
        except Exception as exc:
            logger.exception("process_approval_mailbox: eccezione inattesa")
            raise CommandError(f"Eccezione inattesa: {exc}") from exc

        # ── Report per messaggio ──────────────────────────────────────────────
        for msg in result.messages:
            outcome = msg.get("outcome", "?")
            subject = (msg.get("subject") or "")[:70]
            from_addr = msg.get("from", "")
            token = msg.get("token", "")
            approval_id = msg.get("approval_id", "")
            error = msg.get("error", "")

            if outcome.startswith("processed_approved"):
                line = self.style.SUCCESS(
                    f"  ✓ APPROVO — approval_id={approval_id} from={from_addr!r} token={token}"
                )
            elif outcome.startswith("processed_rejected"):
                line = self.style.SUCCESS(
                    f"  ✓ RIFIUTO — approval_id={approval_id} from={from_addr!r} token={token}"
                )
            elif outcome.startswith("dry_run"):
                line = f"  ~ dry-run {outcome} — from={from_addr!r} subject={subject!r}"
            elif "ignored" in outcome:
                line = self.style.WARNING(
                    f"  ⚠ ignorato ({outcome}) — from={from_addr!r} subject={subject!r}"
                    + (f" [{error}]" if error else "")
                )
            elif "error" in outcome:
                line = self.style.ERROR(
                    f"  ✗ errore — from={from_addr!r} token={token} [{error}]"
                )
            else:
                line = f"  ? {outcome} — subject={subject!r}"

            self.stdout.write(line)

        # ── Riepilogo finale (stesso formato di poll_approval_mailbox per compatibilità) ──
        self.stdout.write(
            f"{mode_label} Completato — "
            f"read={result.read} "
            f"processed={result.processed} "
            f"approved={result.approved} "
            f"rejected={result.rejected} "
            f"ignored={result.ignored} "
            f"deduped={result.deduped} "
            f"error={result.error}"
        )
