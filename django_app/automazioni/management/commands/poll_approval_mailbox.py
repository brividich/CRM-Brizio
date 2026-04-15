"""
Management command: poll_approval_mailbox

Legge la casella IMAP configurata, cerca email di risposta approvazione
(soggetto/corpo con token UUID) e chiama process_approval_decision().

Formato atteso email in arrivo:
  Soggetto: CMD APPROVO RID <uuid>   oppure   CMD RIFIUTO RID <uuid>
  Corpo:    CMD: APPROVO / CMD: RIFIUTO  +  RID: <uuid>  (fallback se subject non parsato)

Variabili .env necessarie:
  APPROVAL_IMAP_HOST        — hostname server IMAP
  APPROVAL_IMAP_PORT        — porta (default 993)
  APPROVAL_IMAP_USER        — username (tipicamente l'email della mailbox)
  APPROVAL_IMAP_PASSWORD    — password
  APPROVAL_IMAP_SSL         — 1/true per SSL (default 1)
  APPROVAL_IMAP_FOLDER      — cartella da leggere (default INBOX)

Utilizzo:
  python manage.py poll_approval_mailbox
  python manage.py poll_approval_mailbox --dry-run
  python manage.py poll_approval_mailbox --folder "Approvazioni" --limit 100
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
from email.header import decode_header, make_header
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# Regex per estrarre UUID dal soggetto o dal corpo
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Parole chiave comando
_CMD_APPROVE_RE = re.compile(r"\bCMD[:\s]+APPROVO\b", re.IGNORECASE)
_CMD_REJECT_RE = re.compile(r"\bCMD[:\s]+RIFIUTO\b", re.IGNORECASE)


def _get_imap_setting(key: str, default: str = "") -> str:
    return str(getattr(settings, key, None) or default).strip()


def _decode_header_str(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw or "")


def _get_text_parts(msg: email.message.Message) -> list[str]:
    """Estrae tutte le parti text/plain da un messaggio (anche multipart)."""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    payload = part.get_payload(decode=True)
                    parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            try:
                payload = msg.get_payload(decode=True)
                parts.append(payload.decode(charset, errors="replace"))
            except Exception:
                pass
    return parts


def _parse_approval_command(subject: str, body_parts: list[str]) -> tuple[str | None, str | None]:
    """
    Ritorna (token, decision) oppure (None, None) se nessun comando riconosciuto.
    decision: 'approved' | 'rejected'
    """
    # 1. Prova subject: "CMD APPROVO RID <uuid>" / "CMD RIFIUTO RID <uuid>"
    subject_upper = subject.upper()
    if "CMD APPROVO" in subject_upper or "CMD: APPROVO" in subject_upper:
        m = _UUID_RE.search(subject)
        if m:
            return m.group(0), "approved"
    if "CMD RIFIUTO" in subject_upper or "CMD: RIFIUTO" in subject_upper:
        m = _UUID_RE.search(subject)
        if m:
            return m.group(0), "rejected"

    # 2. Fallback: cerca nel corpo
    full_body = "\n".join(body_parts)
    decision: str | None = None
    if _CMD_APPROVE_RE.search(full_body):
        decision = "approved"
    elif _CMD_REJECT_RE.search(full_body):
        decision = "rejected"

    if decision:
        # Cerca "RID: <uuid>" nel corpo, poi qualsiasi UUID
        rid_match = re.search(r"RID[:\s]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", full_body, re.IGNORECASE)
        if rid_match:
            return rid_match.group(1), decision
        m = _UUID_RE.search(full_body)
        if m:
            return m.group(0), decision

    return None, None


def _connect_imap(host: str, port: int, use_ssl: bool) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    if use_ssl:
        ctx = ssl.create_default_context()
        return imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    return imaplib.IMAP4(host, port)


class Command(BaseCommand):
    help = "Legge la mailbox IMAP e processa le risposte di approvazione/rifiuto automazioni."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe elaborato senza chiamare process_approval_decision né marcare le email come lette.",
        )
        parser.add_argument(
            "--folder",
            default=None,
            help="Cartella IMAP da leggere (default: APPROVAL_IMAP_FOLDER da .env oppure INBOX).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Numero massimo di email non lette da processare per run (default 50).",
        )
        parser.add_argument(
            "--mark-read",
            action="store_true",
            default=True,
            help="Marca come lette le email processate (default: sì).",
        )
        parser.add_argument(
            "--no-mark-read",
            dest="mark_read",
            action="store_false",
            help="Non marcare come lette le email processate.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        folder: str = options["folder"] or _get_imap_setting("APPROVAL_IMAP_FOLDER", "INBOX")
        limit: int = max(int(options.get("limit") or 1), 1)
        mark_read: bool = options.get("mark_read", True)

        host = _get_imap_setting("APPROVAL_IMAP_HOST")
        port_raw = _get_imap_setting("APPROVAL_IMAP_PORT", "993")
        user = _get_imap_setting("APPROVAL_IMAP_USER")
        password = _get_imap_setting("APPROVAL_IMAP_PASSWORD")
        ssl_raw = _get_imap_setting("APPROVAL_IMAP_SSL", "1")
        use_ssl = ssl_raw.lower() not in ("0", "false", "no")

        if not host:
            raise CommandError(
                "APPROVAL_IMAP_HOST non configurato. "
                "Aggiungi APPROVAL_IMAP_HOST (e APPROVAL_IMAP_USER, APPROVAL_IMAP_PASSWORD) nel .env."
            )
        if not user or not password:
            raise CommandError("APPROVAL_IMAP_USER e APPROVAL_IMAP_PASSWORD devono essere configurati nel .env.")

        try:
            port = int(port_raw)
        except ValueError:
            port = 993

        mode_label = "[dry-run]" if dry_run else "[run]"
        self.stdout.write(f"{mode_label} Connessione IMAP {host}:{port} (SSL={use_ssl}) folder={folder!r} limit={limit}")

        try:
            imap = _connect_imap(host, port, use_ssl)
        except Exception as exc:
            raise CommandError(f"Connessione IMAP fallita: {exc}") from exc

        try:
            imap.login(user, password)
        except imaplib.IMAP4.error as exc:
            raise CommandError(f"Login IMAP fallito per {user!r}: {exc}") from exc

        try:
            status, _ = imap.select(folder)
            if status != "OK":
                raise CommandError(f"Cartella IMAP {folder!r} non trovata o non accessibile.")

            _, msg_ids_raw = imap.search(None, "UNSEEN")
            msg_ids: list[bytes] = (msg_ids_raw[0].split() if msg_ids_raw and msg_ids_raw[0] else [])
            msg_ids = msg_ids[:limit]

            self.stdout.write(f"{mode_label} Email non lette trovate: {len(msg_ids_raw[0].split() if msg_ids_raw and msg_ids_raw[0] else [])}, da processare: {len(msg_ids)}")

            stats: dict[str, int] = {"processed": 0, "approved": 0, "rejected": 0, "skipped": 0, "error": 0}

            for msg_id in msg_ids:
                _, msg_data = imap.fetch(msg_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    stats["skipped"] += 1
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_str(msg.get("Subject", ""))
                sender = _decode_header_str(msg.get("From", ""))
                # Estrai solo l'indirizzo email dal campo From
                sender_email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender)
                sender_email = sender_email_match.group(0) if sender_email_match else sender

                body_parts = _get_text_parts(msg)
                token, decision = _parse_approval_command(subject, body_parts)

                if not token or not decision:
                    self.stdout.write(
                        self.style.WARNING(f"  msg_id={msg_id.decode()} — nessun comando riconosciuto, skip. Subject: {subject[:80]!r}")
                    )
                    stats["skipped"] += 1
                    # Marca comunque come letto per non rielaborarla nei run successivi
                    if not dry_run and mark_read:
                        imap.store(msg_id, "+FLAGS", "\\Seen")
                    continue

                self.stdout.write(
                    f"  msg_id={msg_id.decode()} token={token} decision={decision} from={sender_email!r}"
                )

                if dry_run:
                    stats["processed"] += 1
                    stats[decision.replace("approved", "approved").replace("rejected", "rejected")] = \
                        stats.get(decision.replace("approved", "approved").replace("rejected", "rejected"), 0) + 1
                    continue

                try:
                    from automazioni.services import process_approval_decision
                    result: dict[str, Any] = process_approval_decision(
                        token=token,
                        decision=decision,
                        decided_by_email=sender_email,
                    )
                    if result.get("ok"):
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"    ✓ {decision} processato — approval_id={result.get('approval_id')} "
                                f"actions_run={result.get('actions_run', 0)}"
                            )
                        )
                        stats["processed"] += 1
                        if decision == "approved":
                            stats["approved"] += 1
                        else:
                            stats["rejected"] += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(f"    ✗ process_approval_decision ko: {result.get('message')}")
                        )
                        stats["error"] += 1
                except Exception as exc:
                    logger.exception("poll_approval_mailbox: errore processando token=%s", token)
                    self.stdout.write(self.style.ERROR(f"    ✗ eccezione: {exc}"))
                    stats["error"] += 1

                if mark_read:
                    imap.store(msg_id, "+FLAGS", "\\Seen")

        finally:
            try:
                imap.logout()
            except Exception:
                pass

        self.stdout.write(
            f"{mode_label} Completato — processed={stats['processed']} "
            f"approved={stats.get('approved', 0)} rejected={stats.get('rejected', 0)} "
            f"skipped={stats['skipped']} error={stats['error']}"
        )
