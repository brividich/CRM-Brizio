"""
Mailbox provider abstraction for Security Center AI.
Supports mock, Microsoft Graph, and IMAP providers.
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.services.configuration import get_setting

logger = logging.getLogger(__name__)

GRAPH_AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_TIMEOUT_SECONDS = 30
GRAPH_WELL_KNOWN_FOLDERS = {"archive", "deleteditems", "drafts", "inbox", "junkemail", "outbox", "sentitems"}
GRAPH_PAGE_SIZE = 50
GRAPH_MAX_PAGES = 20
# Re-read a window before the last success: Graph's clock is not ours, and a message can
# land with a timestamp slightly before the moment we finished the previous run.
# Re-fetching is free - the dedup on provider_message_id drops the duplicates.
INCREMENTAL_OVERLAP_MINUTES = 30


def incremental_since(source):
    """Lower bound for the incremental fetch, or None on the first ever run."""
    last_success = getattr(source, "last_success_at", None)
    if not last_success:
        return None
    return last_success - timedelta(minutes=INCREMENTAL_OVERLAP_MINUTES)


@dataclass
class MailboxAttachment:
    filename: str
    content_type: str
    content_bytes: bytes
    size_bytes: int


@dataclass
class MailboxMessage:
    provider_message_id: str
    internet_message_id: Optional[str]
    sender: str
    recipients: List[str]
    subject: str
    received_at: datetime
    body_text: str
    body_html: str
    attachments: List[MailboxAttachment]
    # Sender authentication (DKIM/SPF/DMARC) as reported by the receiving mail system.
    # Defaults are fail-closed: unknown provenance is NOT considered verified.
    sender_verified: bool = False
    auth_summary: str = ""


class MailboxProvider(ABC):
    @abstractmethod
    def list_messages(self, source, limit: int = 50) -> List[MailboxMessage]:
        pass


class MockMailboxProvider(MailboxProvider):
    def list_messages(self, source, limit: int = 50) -> List[MailboxMessage]:
        logger.info(f"MockMailboxProvider: returning empty list for source {source.code}")
        return []


class GraphMailboxProvider(MailboxProvider):
    def list_messages(self, source, limit: int = 50) -> List[MailboxMessage]:
        if not source.mailbox_address:
            raise MailboxProviderConfigurationError("Microsoft Graph source requires mailbox_address")

        token = self._acquire_token()
        message_items = self._get_messages(token, source, limit)
        messages = []
        for item in message_items:
            attachments = []
            if source.process_attachments and item.get("hasAttachments"):
                attachments = self._get_attachments(token, source.mailbox_address, item["id"])
            messages.append(_message_from_graph_item(item, source.mailbox_address, attachments))
        return messages

    def _acquire_token(self) -> str:
        tenant_id = _required_graph_setting("GRAPH_TENANT_ID")
        client_id = _required_graph_setting("GRAPH_CLIENT_ID")
        client_secret = _required_graph_setting("GRAPH_CLIENT_SECRET")

        body = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": GRAPH_SCOPE,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        url = GRAPH_AUTHORITY_TEMPLATE.format(tenant_id=urllib.parse.quote(tenant_id, safe=""))
        data = _request_json(url, method="POST", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token = data.get("access_token")
        if not token:
            raise MailboxProviderError("Microsoft Graph token response did not include an access token")
        return token

    def _get_messages(self, token: str, source, limit: int) -> List[dict]:
        """Fetch messages incrementally, oldest first, following Graph pagination.

        The previous implementation asked for the newest N messages and stopped there.
        If more than ``max_messages_per_run`` mails arrived between two runs (a nightly
        batch of vendor reports, say), the older ones fell off the window and were never
        imported: the next run again saw only the newest N. Reports were lost silently.

        Two changes fix that:
        - ``$filter`` on ``receivedDateTime`` from the last successful run (minus a safety
          overlap, because Graph timestamps and our clock are not the same clock). Dedup
          on the provider message id makes the overlap harmless.
        - ascending order + ``@odata.nextLink`` pagination, so the backlog is drained from
          the oldest message forward instead of the newest backwards.
        """
        page_size = max(1, min(int(limit or 50), GRAPH_PAGE_SIZE))
        max_messages = max(1, int(limit or 50))
        folder = str(get_setting("GRAPH_MAIL_FOLDER", "") or "").strip() or os.getenv("GRAPH_MAIL_FOLDER", "").strip() or "Inbox"
        # internetMessageHeaders carries Authentication-Results (DKIM/SPF/DMARC), used to
        # tell a genuine vendor notification from a spoofed look-alike.
        select_fields = "id,internetMessageId,subject,from,toRecipients,receivedDateTime,body,hasAttachments,internetMessageHeaders"
        query = {
            "$top": page_size,
            "$select": select_fields,
            # Oldest first: a backlog must be drained from the bottom, never truncated
            # from the top.
            "$orderby": "receivedDateTime asc",
        }
        since = incremental_since(source)
        if since:
            query["$filter"] = f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        mailbox = urllib.parse.quote(source.mailbox_address, safe="")
        folder_part = self._resolve_folder_part(token, mailbox, folder)
        url = f"{GRAPH_API_BASE_URL}/users/{mailbox}/mailFolders/{folder_part}/messages?{urllib.parse.urlencode(query)}"

        items: List[dict] = []
        pages = 0
        while url and len(items) < max_messages and pages < GRAPH_MAX_PAGES:
            data = _request_json(url, headers=_graph_headers(token))
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink") or ""
            pages += 1

        if url and len(items) < max_messages:
            # We stopped on the page cap, not because the mailbox was drained.
            logger.warning(
                "Graph pagination stopped at %s pages for source %s: more messages remain",
                GRAPH_MAX_PAGES, source.code,
            )
        if len(items) > max_messages:
            logger.info(
                "Graph returned %s messages for source %s, capped at max_messages_per_run=%s; "
                "the remainder will be picked up by the next run",
                len(items), source.code, max_messages,
            )
        return items[:max_messages]

    def _resolve_folder_part(self, token: str, mailbox: str, folder: str) -> str:
        folder = folder.strip() or "Inbox"
        if folder.lower() in GRAPH_WELL_KNOWN_FOLDERS:
            return urllib.parse.quote(folder, safe="")

        escaped = _odata_string(folder)
        params = urllib.parse.urlencode({"$top": 1, "$select": "id,displayName", "$filter": f"displayName eq '{escaped}'"})
        for url in [
            f"{GRAPH_API_BASE_URL}/users/{mailbox}/mailFolders?{params}",
            f"{GRAPH_API_BASE_URL}/users/{mailbox}/mailFolders/Inbox/childFolders?{params}",
        ]:
            data = _request_json(url, headers=_graph_headers(token))
            matches = data.get("value", [])
            if matches:
                return urllib.parse.quote(matches[0]["id"], safe="")

        raise MailboxProviderConfigurationError(f"Microsoft Graph mail folder not found: {folder}")

    def _get_attachments(self, token: str, mailbox_address: str, message_id: str) -> List[MailboxAttachment]:
        mailbox = urllib.parse.quote(mailbox_address, safe="")
        encoded_message_id = urllib.parse.quote(message_id, safe="")
        url = f"{GRAPH_API_BASE_URL}/users/{mailbox}/messages/{encoded_message_id}/attachments?$top=25"
        data = _request_json(url, headers=_graph_headers(token))
        attachments = []
        for item in data.get("value", []):
            if item.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            content_bytes = item.get("contentBytes") or ""
            try:
                raw_content = base64.b64decode(content_bytes)
            except (ValueError, TypeError):
                raw_content = b""
            attachments.append(
                MailboxAttachment(
                    filename=item.get("name") or "attachment.bin",
                    content_type=item.get("contentType") or "application/octet-stream",
                    content_bytes=raw_content,
                    size_bytes=int(item.get("size") or len(raw_content)),
                )
            )
        return attachments


class IMAPMailboxProvider(MailboxProvider):
    def list_messages(self, source, limit: int = 50) -> List[MailboxMessage]:
        logger.warning(f"IMAPMailboxProvider not yet implemented for source {source.code}")
        return []


def get_provider(source) -> MailboxProvider:
    if source.source_type == "mock":
        return MockMailboxProvider()
    elif source.source_type == "graph":
        return GraphMailboxProvider()
    elif source.source_type == "imap":
        return IMAPMailboxProvider()
    else:
        return MockMailboxProvider()


class MailboxProviderError(RuntimeError):
    pass


class MailboxProviderConfigurationError(MailboxProviderError):
    pass


def _required_graph_setting(name: str) -> str:
    value = str(get_setting(name, "") or "").strip() or os.getenv(name, "").strip()
    if not value:
        raise MailboxProviderConfigurationError(f"Missing required Microsoft Graph setting: {name}")
    return value


def _graph_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Prefer": 'outlook.body-content-type="text"',
    }


def _odata_string(value: str) -> str:
    return value.replace("'", "''")


def _request_json(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=GRAPH_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = _safe_graph_error(exc)
        raise MailboxProviderError(f"Microsoft Graph request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MailboxProviderError("Microsoft Graph request failed: network error") from exc

    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MailboxProviderError("Microsoft Graph returned invalid JSON") from exc


def _safe_graph_error(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8")
        data = json.loads(payload)
    except Exception:
        return "response body unavailable"
    error = data.get("error") if isinstance(data, dict) else {}
    if isinstance(error, dict):
        return str(error.get("code") or "graph_error")[:120]
    return "graph_error"


def evaluate_sender_authentication(headers) -> tuple[bool, str]:
    """Read Authentication-Results from Graph ``internetMessageHeaders``.

    Returns ``(verified, summary)``. Verified requires DKIM **or** SPF to pass and no
    explicit DMARC failure. Fail-closed: a missing header means not verified.

    The header is written by the receiving mail system (Exchange Online), not by the
    sender, so it cannot be forged by whoever composed the message.
    """
    raw = ""
    for header in headers or []:
        name = str((header or {}).get("name") or "").strip().lower()
        if name in {"authentication-results", "arc-authentication-results"}:
            raw += " " + str((header or {}).get("value") or "")
    text = raw.strip().lower()
    if not text:
        return False, ""

    dkim_pass = "dkim=pass" in text
    spf_pass = "spf=pass" in text
    dmarc_fail = "dmarc=fail" in text
    verified = (dkim_pass or spf_pass) and not dmarc_fail

    parts = []
    for label, ok in (("dkim", dkim_pass), ("spf", spf_pass)):
        parts.append(f"{label}={'pass' if ok else 'not-pass'}")
    if dmarc_fail:
        parts.append("dmarc=fail")
    return verified, " ".join(parts)


def _message_from_graph_item(item: dict, mailbox_address: str, attachments: List[MailboxAttachment]) -> MailboxMessage:
    body = item.get("body") or {}
    sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
    sender_verified, auth_summary = evaluate_sender_authentication(item.get("internetMessageHeaders"))
    recipients = [
        (recipient.get("emailAddress") or {}).get("address")
        for recipient in item.get("toRecipients", [])
        if (recipient.get("emailAddress") or {}).get("address")
    ]
    received_at = parse_datetime(item.get("receivedDateTime") or "") or timezone.now()
    if timezone.is_naive(received_at):
        received_at = timezone.make_aware(received_at, timezone=dt_timezone.utc)

    return MailboxMessage(
        provider_message_id=item.get("id") or "",
        internet_message_id=item.get("internetMessageId") or None,
        sender=sender,
        recipients=recipients or [mailbox_address],
        subject=item.get("subject") or "",
        received_at=received_at,
        body_text=body.get("content") or "",
        body_html="",
        attachments=attachments,
        sender_verified=sender_verified,
        auth_summary=auth_summary,
    )
