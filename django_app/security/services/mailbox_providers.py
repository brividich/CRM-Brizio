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
from datetime import datetime, timezone as dt_timezone
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
        top = max(1, min(int(limit or 50), 500))
        folder = str(get_setting("GRAPH_MAIL_FOLDER", "") or "").strip() or os.getenv("GRAPH_MAIL_FOLDER", "").strip() or "Inbox"
        select_fields = "id,internetMessageId,subject,from,toRecipients,receivedDateTime,body,hasAttachments"
        params = urllib.parse.urlencode(
            {
                "$top": top,
                "$select": select_fields,
                "$orderby": "receivedDateTime desc",
            }
        )
        mailbox = urllib.parse.quote(source.mailbox_address, safe="")
        folder_part = self._resolve_folder_part(token, mailbox, folder)
        url = f"{GRAPH_API_BASE_URL}/users/{mailbox}/mailFolders/{folder_part}/messages?{params}"
        data = _request_json(url, headers=_graph_headers(token))
        return data.get("value", [])

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


def _message_from_graph_item(item: dict, mailbox_address: str, attachments: List[MailboxAttachment]) -> MailboxMessage:
    body = item.get("body") or {}
    sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
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
    )
