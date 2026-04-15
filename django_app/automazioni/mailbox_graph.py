"""
automazioni/mailbox_graph.py — Backend Graph per la lettura mailbox approvazioni.

Sostituisce il backend IMAP Basic Auth (bloccato su Microsoft 365 / Exchange Online)
con Microsoft Graph API autenticato via MSAL app-credentials (client_credentials flow).

Riusa acquire_graph_token() da core/graph_utils.py — stessa app registration
già usata per SharePoint/Outlook Calendar nel portale.

Permessi app registration richiesti:
    Mail.ReadWrite    (lettura + mark-as-read, delegato su mailbox specifica)
    oppure Mail.Read  (solo lettura, senza mark-as-read)

    ATTENZIONE: le permission di tipo Application (non Delegated) sono necessarie
    per accedere a /users/{mailbox}/... senza login interattivo.
    Concedere Admin Consent nel tenant Entra ID dopo la configurazione.

Variabili .env utilizzate:
    GRAPH_TENANT_ID           — già presente (condiviso con gli altri moduli)
    GRAPH_CLIENT_ID           — già presente
    GRAPH_CLIENT_SECRET       — già presente
    APPROVAL_MAILBOX_ADDRESS  — mailbox da leggere (es. avviso@costruzioninovicrom.it)
    APPROVAL_MAILBOX_FOLDER   — cartella Graph (default: Inbox)
    APPROVAL_GRAPH_ONLY_UNREAD — 1/true per filtrare solo non letti (default: 1)
    APPROVAL_GRAPH_PAGE_SIZE  — messaggi per richiesta, max 50 (default: 25)
    APPROVAL_GRAPH_MARK_READ  — 1/true per marcare come letti dopo il processing (default: 1)
    APPROVAL_MAILBOX_BACKEND  — 'graph' | 'imap' (default: 'graph')
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from email.utils import parseaddr
from typing import Any

import os

from django.conf import settings

logger = logging.getLogger(__name__)

# ── Regex shared con poll_approval_mailbox ───────────────────────────────────
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_CMD_APPROVE_RE = re.compile(r"\bCMD[:\s]+APPROVO\b", re.IGNORECASE)
_CMD_REJECT_RE = re.compile(r"\bCMD[:\s]+RIFIUTO\b", re.IGNORECASE)
_RID_RE = re.compile(
    r"\bRID[:\s]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(
    r"\bTOKEN[:\s]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)

# Estrae "MOTIVO: ..." dal corpo
_REASON_RE = re.compile(r"MOTIVO[:\s]+(.+)", re.IGNORECASE)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class GraphMailboxMessage:
    """Messaggio normalizzato proveniente dall'API Graph."""
    graph_id: str
    internet_message_id: str
    subject: str
    from_email: str
    received_at: datetime | None
    body_preview: str
    body_text: str          # parte text/plain estratta dal body Graph
    is_read: bool
    # Risultato del parsing
    command: str | None     # 'approvo' | 'rifiuto' | None
    token: str | None       # UUID stringa | None
    reason: str | None = None  # motivo rifiuto se presente nel corpo


@dataclass
class GraphPollResult:
    """Risultato aggregato di una sessione di polling."""
    read: int = 0
    processed: int = 0
    approved: int = 0
    rejected: int = 0
    ignored: int = 0
    error: int = 0
    deduped: int = 0        # messaggi già visti e saltati per idempotenza
    messages: list[dict[str, Any]] = field(default_factory=list)


# ── Helper settings ──────────────────────────────────────────────────────────

def _s(key: str, default: str = "") -> str:
    val = getattr(settings, key, None)
    if val is None:
        val = os.environ.get(key)
    return str(val or default).strip()


def _b(key: str, default: bool = True) -> bool:
    raw = _s(key, "")
    if raw == "":
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def _i(key: str, default: int = 0) -> int:
    try:
        return int(_s(key, str(default)))
    except (TypeError, ValueError):
        return default


# ── Config reader ────────────────────────────────────────────────────────────

def get_graph_mailbox_config() -> dict[str, Any]:
    """Restituisce la configurazione runtime per il backend Graph mailbox."""
    tenant_id = _s("GRAPH_TENANT_ID")
    client_id = _s("GRAPH_CLIENT_ID")
    client_secret = _s("GRAPH_CLIENT_SECRET")
    mailbox = _s("APPROVAL_MAILBOX_ADDRESS")
    folder = _s("APPROVAL_MAILBOX_FOLDER", "Inbox") or "Inbox"
    only_unread = _b("APPROVAL_GRAPH_ONLY_UNREAD", True)
    page_size = max(1, min(_i("APPROVAL_GRAPH_PAGE_SIZE", 25), 50))
    mark_read = _b("APPROVAL_GRAPH_MARK_READ", True)
    backend = _s("APPROVAL_MAILBOX_BACKEND", "graph").lower()

    missing: list[str] = []
    if not tenant_id:
        missing.append("GRAPH_TENANT_ID")
    if not client_id:
        missing.append("GRAPH_CLIENT_ID")
    if not client_secret:
        missing.append("GRAPH_CLIENT_SECRET")
    if not mailbox:
        missing.append("APPROVAL_MAILBOX_ADDRESS")

    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret_configured": bool(client_secret),
        "mailbox": mailbox,
        "folder": folder,
        "only_unread": only_unread,
        "page_size": page_size,
        "mark_read": mark_read,
        "backend": backend,
        "missing_fields": missing,
        "is_ready": not missing and backend == "graph",
    }


# ── Parsing soggetto/corpo ───────────────────────────────────────────────────

def _extract_text_from_graph_body(body: dict[str, Any]) -> str:
    """Estrae testo plain dal body Graph (content_type text o html → strip tags)."""
    content = str(body.get("content") or "")
    content_type = str(body.get("contentType") or "").lower()
    if content_type == "html":
        # Rimozione tag HTML minimale senza dipendenze pesanti
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"&nbsp;", " ", content)
        content = re.sub(r"&amp;", "&", content)
        content = re.sub(r"&lt;", "<", content)
        content = re.sub(r"&gt;", ">", content)
        content = re.sub(r"[ \t]+", " ", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def _normalize_email_address(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    _display_name, parsed = parseaddr(raw)
    return str(parsed or raw).strip().lower()


def _extract_labeled_token(body_text: str) -> str | None:
    for pattern in (_RID_RE, _TOKEN_RE):
        match = pattern.search(body_text or "")
        if match:
            return match.group(1)
    return None


def _sort_messages_for_processing(messages: list["GraphMailboxMessage"]) -> list["GraphMailboxMessage"]:
    """
    FIRST VALID DECISION WINS:
    anche se Graph restituisce i messaggi piu recenti per primi, il batch viene
    processato in ordine cronologico crescente cosi la prima decisione valida
    applicata all'approval rende le successive reply "already_decided".
    """
    max_dt = datetime.max.replace(tzinfo=dt_timezone.utc)
    return sorted(
        messages,
        key=lambda msg: (
            msg.received_at is None,
            msg.received_at if msg.received_at is not None else max_dt,
        ),
    )


def _is_already_decided_error(message: str) -> bool:
    normalized = str(message or "").casefold()
    return "gia in stato" in normalized or "già in stato" in normalized


def parse_approval_command(subject: str, body_text: str) -> tuple[str | None, str | None, str | None]:
    """
    Ritorna (command, token, reason) dalla coppia subject+body.
    command: 'approvo' | 'rifiuto' | None
    token:   UUID stringa | None
    reason:  motivo testuale (solo per rifiuto) | None
    """
    subject_upper = (subject or "").upper()

    # ── 1. Subject-first (formato canonico) ──────────────────────────────────
    # "CMD APPROVO RID <uuid>" / "CMD RIFIUTO RID <uuid>"
    if "CMD APPROVO" in subject_upper or "CMD: APPROVO" in subject_upper:
        m = _UUID_RE.search(subject)
        if m:
            return "approvo", m.group(0), None

    if "CMD RIFIUTO" in subject_upper or "CMD: RIFIUTO" in subject_upper:
        m = _UUID_RE.search(subject)
        if m:
            reason = _extract_reason(body_text)
            return "rifiuto", m.group(0), reason

    # ── 2. Body fallback ─────────────────────────────────────────────────────
    command: str | None = None
    if _CMD_APPROVE_RE.search(body_text):
        command = "approvo"
    elif _CMD_REJECT_RE.search(body_text):
        command = "rifiuto"

    if command:
        token = _extract_labeled_token(body_text)
        reason = _extract_reason(body_text) if command == "rifiuto" else None
        return command, token, reason

    return None, None, None


def _extract_reason(body_text: str) -> str | None:
    m = _REASON_RE.search(body_text or "")
    if m:
        reason = m.group(1).strip()
        return reason if reason else None
    return None


# ── Graph API client ─────────────────────────────────────────────────────────

def _get_token() -> str:
    from core.graph_utils import acquire_graph_token
    tenant_id = _s("GRAPH_TENANT_ID")
    client_id = _s("GRAPH_CLIENT_ID")
    client_secret = _s("GRAPH_CLIENT_SECRET")
    return acquire_graph_token(tenant_id, client_id, client_secret)


def _graph_request(
    method: str,
    url: str,
    *,
    token: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Wrapper minimale per chiamate Graph.
    Riusa requests (già nel requirements.txt via msal).
    Solleva RuntimeError su HTTP error o problemi di rete.
    """
    try:
        import requests  # noqa: PLC0415 — disponibile via msal/requests
    except ImportError as exc:
        raise RuntimeError(f"Libreria requests non disponibile: {exc}") from exc

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.request(
        method,
        url,
        headers=headers,
        json=json_body,
        params=params,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Graph API {method} {url} → HTTP {resp.status_code}: {resp.text[:300]}"
        )
    if resp.status_code == 204:
        return {}
    try:
        return resp.json()
    except Exception:
        return {}


def fetch_messages(
    *,
    mailbox: str,
    folder: str = "Inbox",
    only_unread: bool = True,
    limit: int = 25,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    """
    Legge i messaggi dalla mailbox tramite Graph.
    Ritorna lista di messaggi raw Graph (dict) pronti per il parsing.
    Gestisce paginazione via @odata.nextLink.
    """
    token = _get_token()

    # Costruiamo i parametri query
    select_fields = ",".join([
        "id",
        "internetMessageId",
        "subject",
        "from",
        "receivedDateTime",
        "bodyPreview",
        "body",
        "isRead",
    ])
    params: dict[str, Any] = {
        "$select": select_fields,
        "$top": min(limit, 50),
        "$orderby": "receivedDateTime desc",
    }

    filters: list[str] = []
    if only_unread:
        filters.append("isRead eq false")
    if since_hours and since_hours > 0:
        from datetime import timedelta
        cutoff = (
            datetime.now(dt_timezone.utc) - timedelta(hours=since_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        filters.append(f"receivedDateTime ge {cutoff}")
    if filters:
        params["$filter"] = " and ".join(filters)

    # Percorso cartella: supporta nomi semplici (Inbox) e percorsi (Inbox/Approvazioni)
    # Graph accetta mailFolders/{folder_name}/messages per nomi wellknown e path
    folder_segment = folder.strip("/")
    url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{folder_segment}/messages"

    messages: list[dict[str, Any]] = []
    collected = 0

    while url and collected < limit:
        try:
            data = _graph_request("GET", url, token=token, params=params if collected == 0 else None)
        except RuntimeError as exc:
            logger.error("mailbox_graph.fetch_messages: errore Graph: %s", exc)
            raise

        batch = data.get("value", [])
        remaining = limit - collected
        messages.extend(batch[:remaining])
        collected += len(batch[:remaining])

        # Paginazione: nextLink già contiene tutti i parametri
        url = data.get("@odata.nextLink", "")
        params = None  # usato solo alla prima richiesta

    return messages


def normalize_message(raw: dict[str, Any]) -> GraphMailboxMessage:
    """Converte un messaggio raw Graph in GraphMailboxMessage normalizzato."""
    graph_id = str(raw.get("id") or "")
    internet_msg_id = str(raw.get("internetMessageId") or "").strip()
    subject = str(raw.get("subject") or "").strip()

    # Mittente
    from_obj = raw.get("from") or {}
    email_addr = from_obj.get("emailAddress") or {}
    from_email = _normalize_email_address(email_addr.get("address") or "")

    # Data ricezione
    received_raw = raw.get("receivedDateTime")
    received_at: datetime | None = None
    if received_raw:
        try:
            # Graph restituisce ISO8601 UTC con Z
            received_at = datetime.fromisoformat(str(received_raw).replace("Z", "+00:00"))
        except ValueError:
            pass

    is_read = bool(raw.get("isRead"))
    body_preview = str(raw.get("bodyPreview") or "")
    body_obj = raw.get("body") or {}
    body_text = _extract_text_from_graph_body(body_obj)

    # Parsing comando
    command, token, reason = parse_approval_command(subject, body_text)

    return GraphMailboxMessage(
        graph_id=graph_id,
        internet_message_id=internet_msg_id,
        subject=subject,
        from_email=from_email,
        received_at=received_at,
        body_preview=body_preview,
        body_text=body_text,
        is_read=is_read,
        command=command,
        token=token,
        reason=reason,
    )


def mark_message_as_read(*, mailbox: str, graph_message_id: str) -> bool:
    """Marca un messaggio come letto via Graph PATCH. Ritorna True se ok."""
    try:
        token = _get_token()
        url = f"{GRAPH_BASE}/users/{mailbox}/messages/{graph_message_id}"
        _graph_request("PATCH", url, token=token, json_body={"isRead": True})
        return True
    except RuntimeError as exc:
        logger.warning("mark_message_as_read fallito per %s: %s", graph_message_id, exc)
        return False


# ── Tracking / deduplica DB ──────────────────────────────────────────────────

def is_already_processed(internet_message_id: str) -> bool:
    """Ritorna True se il messaggio è già stato tracciato (processed o ignored)."""
    if not internet_message_id:
        return False
    try:
        from .models import ApprovalMailboxMessage, ApprovalMailboxMessageStatus
        return ApprovalMailboxMessage.objects.filter(
            internet_message_id=internet_message_id,
            processing_status__in=[
                ApprovalMailboxMessageStatus.PROCESSED,
                ApprovalMailboxMessageStatus.IGNORED,
            ],
        ).exists()
    except Exception as exc:
        logger.warning("is_already_processed DB check fallito: %s", exc)
        return False


def save_message_record(
    msg: GraphMailboxMessage,
    *,
    status: str,
    error: str = "",
    approval_id: int | None = None,
) -> None:
    """
    Crea o aggiorna il record di tracking per il messaggio.
    Usa update_or_create su internet_message_id per idempotenza.
    """
    try:
        from django.utils import timezone
        from .models import ApprovalMailboxMessage, ApprovalMailboxMessageStatus

        approval_obj = None
        if approval_id:
            from .models import AutomationApproval
            try:
                approval_obj = AutomationApproval.objects.get(pk=approval_id)
            except AutomationApproval.DoesNotExist:
                pass

        excerpt = (msg.body_text or msg.body_preview or "")[:500]

        ApprovalMailboxMessage.objects.update_or_create(
            internet_message_id=msg.internet_message_id,
            defaults={
                "graph_message_id": msg.graph_id,
                "mailbox": _s("APPROVAL_MAILBOX_ADDRESS"),
                "folder_name": _s("APPROVAL_MAILBOX_FOLDER", "Inbox"),
                "subject_raw": msg.subject,
                "from_email": msg.from_email,
                "received_at": msg.received_at,
                "command_detected": msg.command or "",
                "token_found": msg.token or "",
                "processing_status": status,
                "processing_error": error,
                "excerpt": excerpt,
                "linked_approval": approval_obj,
                "processed_at": timezone.now() if status in (
                    ApprovalMailboxMessageStatus.PROCESSED,
                    ApprovalMailboxMessageStatus.IGNORED,
                    ApprovalMailboxMessageStatus.ERROR,
                ) else None,
            },
        )
    except Exception as exc:
        logger.error("save_message_record fallito: %s", exc)


# ── Entry point principale ────────────────────────────────────────────────────

def poll_graph_mailbox(
    *,
    limit: int = 25,
    dry_run: bool = False,
    only_unread: bool | None = None,
    folder: str | None = None,
    mark_read: bool | None = None,
    since_hours: int | None = None,
) -> GraphPollResult:
    """
    Esegue un ciclo di polling completo sulla mailbox Graph.
    Ogni messaggio:
        1. Viene deduplica su DB (internet_message_id)
        2. Viene parsato per estrarre comando e token
        3. Viene validato (mittente, stato approval, scadenza)
        4. Viene processato chiamando process_approval_decision()
        5. Viene tracciato su ApprovalMailboxMessage
        6. Viene marcato come letto (se mark_read=True e non dry_run)

    Ritorna GraphPollResult con i contatori aggregati.
    """
    config = get_graph_mailbox_config()
    if not config["is_ready"]:
        raise RuntimeError(
            "Configurazione Graph mailbox incompleta. Mancano: "
            + ", ".join(config.get("missing_fields", []))
        )

    effective_folder = folder or config["folder"]
    effective_only_unread = only_unread if only_unread is not None else config["only_unread"]
    effective_mark_read = mark_read if mark_read is not None else config["mark_read"]
    mailbox = config["mailbox"]

    result = GraphPollResult()

    raw_messages = fetch_messages(
        mailbox=mailbox,
        folder=effective_folder,
        only_unread=effective_only_unread,
        limit=limit,
        since_hours=since_hours,
    )
    result.read = len(raw_messages)

    normalized_messages = _sort_messages_for_processing([normalize_message(raw) for raw in raw_messages])

    for msg in normalized_messages:

        # ── Deduplica ────────────────────────────────────────────────────────
        if not msg.internet_message_id:
            logger.warning("Messaggio senza internetMessageId, skip: subject=%r", msg.subject[:60])
            result.ignored += 1
            continue

        if is_already_processed(msg.internet_message_id):
            logger.debug("Messaggio già processato, skip: %s", msg.internet_message_id)
            result.deduped += 1
            result.messages.append({
                "internet_message_id": msg.internet_message_id,
                "subject": msg.subject[:100],
                "from": msg.from_email,
                "command": msg.command,
                "token": msg.token,
                "outcome": "ignored_already_processed",
            })
            if effective_mark_read and msg.graph_id:
                mark_message_as_read(mailbox=mailbox, graph_message_id=msg.graph_id)
            continue

        msg_log: dict[str, Any] = {
            "internet_message_id": msg.internet_message_id,
            "subject": msg.subject[:100],
            "from": msg.from_email,
            "command": msg.command,
            "token": msg.token,
        }

        # ── Nessun comando riconosciuto ──────────────────────────────────────
        if not msg.command or not msg.token:
            logger.debug(
                "Nessun comando approvazione in messaggio da %s: %r",
                msg.from_email,
                msg.subject[:80],
            )
            result.ignored += 1
            msg_log["outcome"] = "ignored_no_command"
            result.messages.append(msg_log)
            if not dry_run:
                save_message_record(msg, status="ignored", error="Nessun comando riconosciuto")
                if effective_mark_read and msg.graph_id:
                    mark_message_as_read(mailbox=mailbox, graph_message_id=msg.graph_id)
            continue

        # ── Dry run: non applicare ───────────────────────────────────────────
        if dry_run:
            result.processed += 1
            if msg.command == "approvo":
                result.approved += 1
            else:
                result.rejected += 1
            msg_log["outcome"] = f"dry_run_{msg.command}"
            result.messages.append(msg_log)
            continue

        # ── Applica la decisione ─────────────────────────────────────────────
        mark_read_allowed = False
        try:
            from .services import process_approval_decision  # noqa: PLC0415

            # Valida mittente vs approvatori attesi prima di delegare a services
            sender_error = _validate_sender(msg.token, msg.from_email)
            if sender_error:
                logger.warning(
                    "Mittente non autorizzato: %s per token %s — %s",
                    msg.from_email,
                    msg.token,
                    sender_error,
                )
                save_message_record(
                    msg,
                    status="ignored",
                    error=sender_error,
                )
                result.ignored += 1
                if _is_already_decided_error(sender_error):
                    msg_log["outcome"] = "ignored_already_decided"
                    mark_read_allowed = True
                elif "non nella lista approvatori" in sender_error.casefold():
                    msg_log["outcome"] = "ignored_unauthorized_sender"
                else:
                    msg_log["outcome"] = "ignored_validation_error"
                msg_log["error"] = sender_error
                result.messages.append(msg_log)
                if mark_read_allowed and effective_mark_read and msg.graph_id:
                    mark_message_as_read(mailbox=mailbox, graph_message_id=msg.graph_id)
                continue

            decision_str = "approved" if msg.command == "approvo" else "rejected"
            process_result = process_approval_decision(
                token=msg.token,
                decision=decision_str,
                decided_by_email=msg.from_email,
            )

            if process_result.get("ok"):
                approval_id = process_result.get("approval_id")
                save_message_record(msg, status="processed", approval_id=approval_id)
                result.processed += 1
                mark_read_allowed = True
                if decision_str == "approved":
                    result.approved += 1
                else:
                    result.rejected += 1
                msg_log["outcome"] = f"processed_{decision_str}"
                msg_log["approval_id"] = approval_id
            else:
                err = str(process_result.get("message") or "process_approval_decision ko")
                if _is_already_decided_error(err):
                    save_message_record(msg, status="ignored", error=err)
                    result.ignored += 1
                    msg_log["outcome"] = "ignored_already_decided"
                    msg_log["error"] = err
                    mark_read_allowed = True
                else:
                    save_message_record(msg, status="error", error=err)
                    result.error += 1
                    msg_log["outcome"] = "error_process"
                    msg_log["error"] = err
                    logger.error(
                        "process_approval_decision ko: token=%s from=%s error=%s",
                        msg.token,
                        msg.from_email,
                        err,
                    )

        except Exception as exc:
            logger.exception("poll_graph_mailbox: eccezione su msg %s", msg.internet_message_id)
            save_message_record(msg, status="error", error=str(exc))
            result.error += 1
            msg_log["outcome"] = "error_exception"
            msg_log["error"] = str(exc)

        result.messages.append(msg_log)

        if mark_read_allowed and effective_mark_read and msg.graph_id:
            mark_message_as_read(mailbox=mailbox, graph_message_id=msg.graph_id)

    return result


def _validate_sender(token_str: str, from_email: str) -> str | None:
    """
    Verifica che il mittente sia nella lista approvatori attesi.
    Ritorna None se ok, stringa di errore se non autorizzato.
    Chiamata prima di process_approval_decision per un early-exit sicuro.
    """
    normalized_from_email = _normalize_email_address(from_email)
    if not normalized_from_email:
        return "Mittente mancante"
    try:
        import uuid as _uuid
        from .models import AutomationApproval

        token_uuid = _uuid.UUID(str(token_str))
        try:
            approval = AutomationApproval.objects.get(token=token_uuid)
        except AutomationApproval.DoesNotExist:
            return f"Token {token_str} non trovato"

        if approval.status != AutomationApproval.Status.PENDING:
            return f"Approvazione già in stato '{approval.status}'"

        if approval.is_expired():
            return "Approvazione scaduta"

        # Controlla lista approvatori (se configurata)
        approver_emails = approval.approver_emails or []
        normalized = [
            _normalize_email_address(email_value)
            for email_value in approver_emails
            if _normalize_email_address(email_value)
        ]
        if not normalized:
            return "Nessun approvatore configurato per la richiesta"
        if normalized_from_email not in normalized:
            return f"{normalized_from_email!r} non nella lista approvatori"

        return None

    except ValueError:
        return f"Token UUID non valido: {token_str!r}"
    except Exception as exc:
        logger.warning("_validate_sender fallito per token=%s: %s", token_str, exc)
        return "Validazione mittente non disponibile"
