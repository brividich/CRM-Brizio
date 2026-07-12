"""
Mailbox ingestion service for Security Center AI.
Handles scheduled import of security reports from mailbox sources.
"""
import hashlib
import logging
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from security.models import (
    SecurityMailboxSource,
    SecurityMailboxIngestionRun,
    SecurityMailboxMessage,
    SecuritySourceFile,
    SecuritySource,
    SourceType,
)
from security.services.mailbox_providers import get_provider, MailboxMessage
from security.services.security_inbox_pipeline import process_mailbox_message, process_source_file, summarize_pipeline_result

logger = logging.getLogger(__name__)


def run_mailbox_ingestion(source: SecurityMailboxSource, *, limit: Optional[int] = None, dry_run: bool = False, process_pipeline: bool = True, force_reprocess: bool = False):
    if not source.enabled:
        logger.warning(f"Source {source.code} is disabled, skipping ingestion")
        return None

    run = SecurityMailboxIngestionRun.objects.create(source=source, status="running")
    _pipeline_summaries = []
    _pipeline_error_count = 0

    try:
        source.last_run_at = timezone.now()
        if not dry_run:
            source.save(update_fields=["last_run_at"])

        provider = get_provider(source)
        max_messages = limit if limit is not None else source.max_messages_per_run
        messages = provider.list_messages(source, limit=max_messages)

        for raw_message in messages:
            try:
                if not should_accept_message(source, raw_message):
                    run.skipped_messages_count += 1
                    continue

                result = ingest_mailbox_message(
                    source,
                    raw_message,
                    dry_run=dry_run,
                    process_pipeline=process_pipeline,
                    force_reprocess=force_reprocess
                )

                if result["status"] == "imported":
                    run.imported_messages_count += 1
                    run.imported_files_count += result.get("files_count", 0)
                    run.processed_items_count += result.get("processed_count", 0)
                    run.generated_alerts_count += result.get("alerts_count", 0)
                    if result.get("pipeline_status") == "error":
                        _pipeline_error_count += 1
                    if result.get("pipeline_summary"):
                        _pipeline_summaries.append(result["pipeline_summary"])
                elif result["status"] == "duplicate":
                    run.duplicate_messages_count += 1
                elif result["status"] == "skipped":
                    run.skipped_messages_count += 1

            except Exception as e:
                logger.exception(f"Error ingesting message {raw_message.subject}: {e}")
                run.skipped_messages_count += 1

        run.status = "success"
        run.finished_at = timezone.now()
        run.details = {
            "pipeline_error_count": _pipeline_error_count,
            "latest_pipeline_status": "error" if _pipeline_error_count > 0 else ("success" if run.processed_items_count > 0 else "skipped"),
            "summaries": _pipeline_summaries[:5],
        }

        source.last_success_at = timezone.now()
        source.last_error_message = ""
        if not dry_run:
            source.save(update_fields=["last_success_at", "last_error_message"])

    except Exception as e:
        logger.exception(f"Mailbox ingestion failed for source {source.code}: {e}")
        run.status = "failed"
        run.error_message = str(e)
        run.finished_at = timezone.now()

        source.last_error_at = timezone.now()
        source.last_error_message = str(e)
        if not dry_run:
            source.save(update_fields=["last_error_at", "last_error_message"])

    if not dry_run:
        run.save()

    return run


def should_accept_message(source: SecurityMailboxSource, raw_message: MailboxMessage) -> bool:
    if source.sender_allowlist_text:
        allowed_senders = [s.strip() for s in source.sender_allowlist_text.split("\n") if s.strip()]
        if allowed_senders and not any(sender in raw_message.sender for sender in allowed_senders):
            return False

    if source.subject_include_text:
        include_patterns = [p.strip() for p in source.subject_include_text.split("\n") if p.strip()]
        if include_patterns and not any(pattern.lower() in raw_message.subject.lower() for pattern in include_patterns):
            return False

    if source.subject_exclude_text:
        exclude_patterns = [p.strip() for p in source.subject_exclude_text.split("\n") if p.strip()]
        if any(pattern.lower() in raw_message.subject.lower() for pattern in exclude_patterns):
            return False

    if source.body_include_text and source.process_email_body:
        include_patterns = [p.strip() for p in source.body_include_text.split("\n") if p.strip()]
        body_combined = f"{raw_message.body_text} {raw_message.body_html}".lower()
        if include_patterns and not any(pattern.lower() in body_combined for pattern in include_patterns):
            return False

    return True


def build_message_dedup_key(source: SecurityMailboxSource, raw_message: MailboxMessage) -> str:
    if raw_message.provider_message_id:
        seed = f"{source.id}:provider:{raw_message.provider_message_id}"
    elif raw_message.internet_message_id:
        seed = f"{source.id}:internet:{raw_message.internet_message_id}"
    else:
        body_snippet = raw_message.body_text[:200] if raw_message.body_text else ""
        seed = f"{source.id}:{raw_message.sender}:{raw_message.subject}:{raw_message.received_at.isoformat()}:{body_snippet}"

    return hashlib.sha256(seed.encode()).hexdigest()


def ingest_mailbox_message(source: SecurityMailboxSource, raw_message: MailboxMessage, *, dry_run: bool = False, process_pipeline: bool = True, force_reprocess: bool = False):
    dedup_key = build_message_dedup_key(source, raw_message)

    if not dry_run:
        existing = SecurityMailboxMessage.objects.filter(fingerprint=dedup_key).first()
        if existing:
            logger.debug(f"Duplicate message detected: {raw_message.subject}")
            if process_pipeline and force_reprocess:
                logger.info(f"Force reprocessing message: {raw_message.subject}")
                existing.parse_status = "pending"
                existing.save(update_fields=["parse_status"])
                message_result = process_mailbox_message(existing, source=source, dry_run=False)
                return {
                    "status": "reprocessed",
                    "files_count": 0,
                    "processed_count": 1 if message_result.get("processed", True) else 0,
                    "alerts_count": message_result.get("alerts_created", 0),
                }
            return {"status": "duplicate"}

    result = {
        "status": "imported",
        "files_count": 0,
        "processed_count": 0,
        "alerts_count": 0,
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would import message: {raw_message.subject}")
        result["files_count"] = len(raw_message.attachments) if source.process_attachments else 0
        return result

    with transaction.atomic():
        security_source, _ = SecuritySource.objects.get_or_create(
            name=source.name,
            defaults={"source_type": SourceType.EMAIL, "vendor": "mailbox"}
        )

        message = SecurityMailboxMessage.objects.create(
            source=security_source,
            external_id=raw_message.provider_message_id or raw_message.internet_message_id or "",
            sender=raw_message.sender,
            subject=raw_message.subject,
            body=raw_message.body_text or raw_message.body_html,
            received_at=raw_message.received_at,
            fingerprint=dedup_key,
            raw_payload={
                "recipients": raw_message.recipients,
                "body_html": raw_message.body_html[:1000] if raw_message.body_html else "",
                "mailbox_source_code": source.code,
            }
        )

        if source.process_attachments and raw_message.attachments:
            allowed_extensions = [ext.strip().lower() for ext in source.attachment_extensions.split(",") if ext.strip()]

            for attachment in raw_message.attachments:
                if allowed_extensions:
                    ext = attachment.filename.split(".")[-1].lower() if "." in attachment.filename else ""
                    if ext not in allowed_extensions:
                        continue

                source_file = SecuritySourceFile.objects.create(
                    source=security_source,
                    original_name=attachment.filename,
                    file_type=SourceType.PDF if attachment.filename.lower().endswith(".pdf") else SourceType.EMAIL,
                    content=attachment.content_bytes.decode("utf-8", errors="ignore")[:10000],
                    raw_payload={
                        "size_bytes": attachment.size_bytes,
                        "content_type": attachment.content_type,
                        "mailbox_message_id": message.id,
                        "mailbox_source_code": source.code,
                    }
                )
                result["files_count"] += 1

                if process_pipeline:
                    file_result = process_source_file(source_file, message=message, source=source, dry_run=False)
                    if file_result.get("processed", True):
                        result["processed_count"] += 1
                        result["alerts_count"] += file_result.get("alerts_created", 0)

        if source.process_email_body and message.body and process_pipeline:
            message_result = process_mailbox_message(message, source=source, dry_run=False)
            if message_result.get("processed", True):
                result["processed_count"] += 1
                result["alerts_count"] += message_result.get("alerts_created", 0)
            result["pipeline_status"] = message_result.get("status", "unknown")
            result["pipeline_summary"] = summarize_pipeline_result(message_result)

    return result
