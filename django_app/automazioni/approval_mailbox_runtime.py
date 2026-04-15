from __future__ import annotations

import os
import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from config.env_config import update_env_file_values

from .approval_email_templates import (
    APPROVAL_MAILBOX_SETTINGS_KEY,
    APPROVAL_MAILBOX_SITE_CONFIG_KEY,
)

# ── Costanti backend ──────────────────────────────────────────────────────────
MAILBOX_BACKEND_GRAPH = "graph"
MAILBOX_BACKEND_IMAP = "imap"


_SUMMARY_RE = re.compile(
    r"processed=(?P<processed>\d+)\s+approved=(?P<approved>\d+)\s+"
    r"rejected=(?P<rejected>\d+)\s+skipped=(?P<skipped>\d+)\s+error=(?P<error>\d+)",
    re.IGNORECASE,
)


def _string_setting(key: str, default: str = "") -> str:
    # Prima controlla Django settings (per variabili dichiarate esplicitamente),
    # poi os.environ (per variabili caricate da .env ma non esposte come settings attribute).
    val = getattr(settings, key, None)
    if val is None:
        val = os.environ.get(key)
    return str(val or default).strip()


def _bool_setting(key: str, default: bool) -> bool:
    raw = _string_setting(key, "")
    if raw == "":
        return bool(default)
    return raw.lower() not in {"0", "false", "no", "off"}


def _int_setting(key: str, default: int) -> int:
    raw = _string_setting(key, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def get_default_approval_mailbox_details() -> dict[str, str | bool]:
    site_value = ""
    try:
        from core.models import SiteConfig

        site_value = str(SiteConfig.get(APPROVAL_MAILBOX_SITE_CONFIG_KEY, "") or "").strip()
    except Exception:
        site_value = ""

    if site_value:
        return {
            "value": site_value,
            "source": "site_config",
            "source_label": "SiteConfig",
            "configured": True,
        }

    settings_value = _string_setting(APPROVAL_MAILBOX_SETTINGS_KEY, "")
    if settings_value:
        return {
            "value": settings_value,
            "source": "settings",
            "source_label": "settings",
            "configured": True,
        }

    return {
        "value": "",
        "source": "missing",
        "source_label": "non configurata",
        "configured": False,
    }


def get_approval_imap_status() -> dict[str, object]:
    host = _string_setting("APPROVAL_IMAP_HOST", "")
    port = _int_setting("APPROVAL_IMAP_PORT", 993)
    user = _string_setting("APPROVAL_IMAP_USER", "")
    password = _string_setting("APPROVAL_IMAP_PASSWORD", "")
    folder = _string_setting("APPROVAL_IMAP_FOLDER", "INBOX") or "INBOX"
    use_ssl = _bool_setting("APPROVAL_IMAP_SSL", True)
    mailbox = get_default_approval_mailbox_details()

    missing_fields: list[str] = []
    if not host:
        missing_fields.append("APPROVAL_IMAP_HOST")
    if not user:
        missing_fields.append("APPROVAL_IMAP_USER")
    if not password:
        missing_fields.append("APPROVAL_IMAP_PASSWORD")

    mailbox_matches_user = bool(
        mailbox["value"]
        and user
        and str(mailbox["value"]).casefold() == user.casefold()
    )

    rows = [
        {
            "label": "Server IMAP",
            "value": host or "(non configurato)",
            "is_configured": bool(host),
        },
        {
            "label": "Porta",
            "value": str(port),
            "is_configured": True,
        },
        {
            "label": "Username IMAP",
            "value": user or "(non configurato)",
            "is_configured": bool(user),
        },
        {
            "label": "Password IMAP",
            "value": "Configurata" if password else "Non configurata",
            "is_configured": bool(password),
        },
        {
            "label": "SSL",
            "value": "Attivo" if use_ssl else "Disattivato",
            "is_configured": True,
        },
        {
            "label": "Cartella",
            "value": folder,
            "is_configured": bool(folder),
        },
    ]

    is_ready = not missing_fields
    if is_ready:
        readiness_message = "Configurazione IMAP pronta: il polling mailbox puo' essere eseguito subito."
    else:
        readiness_message = (
            "Configurazione IMAP incompleta. Mancano: " + ", ".join(missing_fields) + "."
        )

    if mailbox["configured"] and mailbox_matches_user:
        mailbox_message = "La mailbox tecnica predefinita coincide con l'utente IMAP."
    elif mailbox["configured"]:
        mailbox_message = "La mailbox tecnica predefinita e' diversa dall'utente IMAP configurato."
    else:
        mailbox_message = (
            "Mailbox tecnica globale non configurata: i template possono comunque usare un valore per-template."
        )

    return {
        "host": host,
        "port": port,
        "user": user,
        "folder": folder,
        "use_ssl": use_ssl,
        "password_configured": bool(password),
        "rows": rows,
        "missing_fields": missing_fields,
        "is_ready": is_ready,
        "readiness_message": readiness_message,
        "mailbox": mailbox,
        "mailbox_matches_user": mailbox_matches_user,
        "mailbox_message": mailbox_message,
        "suggested_schedule": (
            "python django_app/manage.py poll_approval_mailbox --settings=config.settings.prod"
        ),
    }


def get_approval_imap_form_defaults() -> dict[str, object]:
    status = get_approval_imap_status()
    return {
        "host": str(status.get("host") or ""),
        "port": int(status.get("port") or 993),
        "user": str(status.get("user") or ""),
        "password": "",
        "folder": str(status.get("folder") or "INBOX"),
        "use_ssl": bool(status.get("use_ssl")),
        "password_configured": bool(status.get("password_configured")),
    }


def save_approval_imap_settings(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    use_ssl: bool,
    folder: str,
    dotenv_path: Path | None = None,
) -> tuple[bool, str]:
    normalized_host = str(host or "").strip()
    normalized_user = str(user or "").strip()
    normalized_folder = str(folder or "INBOX").strip() or "INBOX"

    try:
        normalized_port = max(int(port), 1)
    except (TypeError, ValueError):
        normalized_port = 993

    current_password = _string_setting("APPROVAL_IMAP_PASSWORD", "")
    effective_password = str(password or "").strip() or current_password
    assignments = {
        "APPROVAL_IMAP_HOST": normalized_host,
        "APPROVAL_IMAP_PORT": str(normalized_port),
        "APPROVAL_IMAP_USER": normalized_user,
        "APPROVAL_IMAP_PASSWORD": effective_password,
        "APPROVAL_IMAP_SSL": "1" if use_ssl else "0",
        "APPROVAL_IMAP_FOLDER": normalized_folder,
    }

    try:
        update_env_file_values(assignments, dotenv_path=dotenv_path)
        for key, value in assignments.items():
            setattr(settings, key, value)
    except Exception as exc:
        return False, f"Errore scrittura config IMAP: {exc}"

    return True, "Configurazione IMAP salvata in .env e aggiornata nel runtime corrente."


def _parse_summary(output: str) -> dict[str, int]:
    match = _SUMMARY_RE.search(output or "")
    if not match:
        return {}
    return {key: int(value) for key, value in match.groupdict().items()}


def get_approval_mailbox_backend() -> str:
    """Ritorna il backend configurato: 'graph' (default) o 'imap'."""
    raw = _string_setting("APPROVAL_MAILBOX_BACKEND", MAILBOX_BACKEND_GRAPH).lower()
    if raw == MAILBOX_BACKEND_IMAP:
        return MAILBOX_BACKEND_IMAP
    return MAILBOX_BACKEND_GRAPH


# ── Graph backend status / config ─────────────────────────────────────────────

def get_approval_graph_status() -> dict[str, object]:
    """Stato runtime del backend Graph mailbox."""
    from .mailbox_graph import get_graph_mailbox_config
    from core.graph_utils import is_placeholder_value

    cfg = get_graph_mailbox_config()
    tenant_id = _string_setting("GRAPH_TENANT_ID", "")
    client_id = _string_setting("GRAPH_CLIENT_ID", "")
    client_secret_raw = _string_setting("GRAPH_CLIENT_SECRET", "")
    mailbox = _string_setting("APPROVAL_MAILBOX_ADDRESS", "")
    folder = _string_setting("APPROVAL_MAILBOX_FOLDER", "Inbox") or "Inbox"
    only_unread = _bool_setting("APPROVAL_GRAPH_ONLY_UNREAD", True)
    page_size = _int_setting("APPROVAL_GRAPH_PAGE_SIZE", 25)
    mark_read = _bool_setting("APPROVAL_GRAPH_MARK_READ", True)

    tenant_ok = bool(tenant_id) and not is_placeholder_value(tenant_id)
    client_ok = bool(client_id) and not is_placeholder_value(client_id)
    secret_ok = bool(client_secret_raw) and not is_placeholder_value(client_secret_raw)
    mailbox_ok = bool(mailbox)

    rows = [
        {"label": "Tenant ID", "value": tenant_id or "(non configurato)", "is_configured": tenant_ok},
        {"label": "Client ID", "value": client_id or "(non configurato)", "is_configured": client_ok},
        {"label": "Client Secret", "value": "Configurato" if secret_ok else "Non configurato", "is_configured": secret_ok},
        {"label": "Mailbox target", "value": mailbox or "(non configurata)", "is_configured": mailbox_ok},
        {"label": "Cartella", "value": folder, "is_configured": True},
        {"label": "Solo non letti", "value": "Sì" if only_unread else "No", "is_configured": True},
        {"label": "Mark read", "value": "Sì" if mark_read else "No", "is_configured": True},
        {"label": "Page size", "value": str(page_size), "is_configured": True},
    ]

    is_ready = cfg["is_ready"]
    if is_ready:
        readiness_message = (
            f"Configurazione Graph pronta: mailbox {mailbox!r} verrà letta tramite Microsoft Graph."
        )
    else:
        missing = ", ".join(cfg.get("missing_fields", []))
        readiness_message = f"Configurazione Graph incompleta. Mancano: {missing}."

    return {
        "mailbox": mailbox,
        "folder": folder,
        "only_unread": only_unread,
        "page_size": page_size,
        "mark_read": mark_read,
        "tenant_configured": tenant_ok,
        "client_configured": client_ok,
        "secret_configured": secret_ok,
        "rows": rows,
        "missing_fields": cfg.get("missing_fields", []),
        "is_ready": is_ready,
        "readiness_message": readiness_message,
        "suggested_schedule": (
            "python django_app/manage.py process_approval_mailbox --settings=config.settings.prod"
        ),
    }


def get_approval_graph_form_defaults() -> dict[str, object]:
    status = get_approval_graph_status()
    return {
        "mailbox": str(status.get("mailbox") or ""),
        "folder": str(status.get("folder") or "Inbox"),
        "only_unread": bool(status.get("only_unread")),
        "page_size": int(status.get("page_size") or 25),
        "mark_read": bool(status.get("mark_read")),
    }


def save_approval_graph_settings(
    *,
    mailbox: str,
    folder: str,
    only_unread: bool,
    page_size: int,
    mark_read: bool,
    dotenv_path: Path | None = None,
) -> tuple[bool, str]:
    """Persiste la configurazione Graph mailbox in .env."""
    normalized_mailbox = str(mailbox or "").strip()
    normalized_folder = str(folder or "Inbox").strip() or "Inbox"

    try:
        normalized_page_size = max(1, min(int(page_size), 50))
    except (TypeError, ValueError):
        normalized_page_size = 25

    assignments = {
        "APPROVAL_MAILBOX_ADDRESS": normalized_mailbox,
        "APPROVAL_MAILBOX_FOLDER": normalized_folder,
        "APPROVAL_GRAPH_ONLY_UNREAD": "1" if only_unread else "0",
        "APPROVAL_GRAPH_PAGE_SIZE": str(normalized_page_size),
        "APPROVAL_GRAPH_MARK_READ": "1" if mark_read else "0",
        "APPROVAL_MAILBOX_BACKEND": MAILBOX_BACKEND_GRAPH,
    }

    try:
        update_env_file_values(assignments, dotenv_path=dotenv_path)
        for key, value in assignments.items():
            setattr(settings, key, value)
    except Exception as exc:
        return False, f"Errore scrittura configurazione Graph mailbox: {exc}"

    return True, "Configurazione Graph mailbox salvata in .env e aggiornata nel runtime corrente."


def run_approval_graph_poll_now(*, limit: int = 25) -> dict[str, object]:
    """Esegue subito il polling Graph (chiama process_approval_mailbox)."""
    status = get_approval_graph_status()
    if not status["is_ready"]:
        return {
            "ok": False,
            "message": str(status["readiness_message"]),
            "output": "",
            "stats": {},
        }

    stdout = StringIO()
    stderr = StringIO()

    try:
        call_command(
            "process_approval_mailbox",
            limit=max(int(limit), 1),
            stdout=stdout,
            stderr=stderr,
            verbosity=0,
        )
        output = "\n".join(
            part for part in (stdout.getvalue().strip(), stderr.getvalue().strip()) if part
        ).strip()
        stats = _parse_summary_graph(output)
        message = "Polling Graph mailbox completato."
        if stats:
            message = (
                "Polling Graph mailbox completato: "
                f"{stats.get('processed', 0)} processate, "
                f"{stats.get('approved', 0)} approvate, "
                f"{stats.get('rejected', 0)} rifiutate, "
                f"{stats.get('ignored', 0)} ignorate, "
                f"{stats.get('deduped', 0)} duplicate, "
                f"{stats.get('error', 0)} errori."
            )
        return {"ok": True, "message": message, "output": output, "stats": stats}
    except (CommandError, Exception) as exc:
        output = "\n".join(
            part
            for part in (stdout.getvalue().strip(), stderr.getvalue().strip(), str(exc).strip())
            if part
        ).strip()
        return {
            "ok": False,
            "message": f"Polling Graph fallito: {exc}",
            "output": output,
            "stats": _parse_summary_graph(output),
        }


_SUMMARY_GRAPH_RE = re.compile(
    r"processed=(?P<processed>\d+)\s+approved=(?P<approved>\d+)\s+"
    r"rejected=(?P<rejected>\d+)\s+ignored=(?P<ignored>\d+)\s+"
    r"deduped=(?P<deduped>\d+)\s+error=(?P<error>\d+)",
    re.IGNORECASE,
)


def _parse_summary_graph(output: str) -> dict[str, int]:
    match = _SUMMARY_GRAPH_RE.search(output or "")
    if not match:
        return {}
    return {key: int(value) for key, value in match.groupdict().items()}


# ── Dispatcher unificato ──────────────────────────────────────────────────────

def run_approval_poll_now(*, limit: int | None = None) -> dict[str, object]:
    """
    Esegue il polling usando il backend configurato (graph o imap).
    Punto di ingresso unificato usato dalla view impostazioni.
    """
    backend = get_approval_mailbox_backend()
    if backend == MAILBOX_BACKEND_IMAP:
        return run_approval_imap_poll_now(limit=limit or 50)
    return run_approval_graph_poll_now(limit=limit or 25)


def run_approval_imap_poll_now(*, limit: int = 50) -> dict[str, object]:
    status = get_approval_imap_status()
    if not status["is_ready"]:
        return {
            "ok": False,
            "message": str(status["readiness_message"]),
            "output": "",
            "stats": {},
        }

    stdout = StringIO()
    stderr = StringIO()

    try:
        call_command(
            "poll_approval_mailbox",
            limit=max(int(limit), 1),
            stdout=stdout,
            stderr=stderr,
            verbosity=0,
        )
        output = "\n".join(part for part in (stdout.getvalue().strip(), stderr.getvalue().strip()) if part).strip()
        stats = _parse_summary(output)
        message = "Polling mailbox completato."
        if stats:
            message = (
                "Polling mailbox completato: "
                f"{stats.get('processed', 0)} processate, "
                f"{stats.get('approved', 0)} approvate, "
                f"{stats.get('rejected', 0)} rifiutate, "
                f"{stats.get('skipped', 0)} ignorate, "
                f"{stats.get('error', 0)} errori."
            )
        return {
            "ok": True,
            "message": message,
            "output": output,
            "stats": stats,
        }
    except (CommandError, Exception) as exc:
        output = "\n".join(
            part for part in (stdout.getvalue().strip(), stderr.getvalue().strip(), str(exc).strip()) if part
        ).strip()
        return {
            "ok": False,
            "message": f"Polling mailbox fallito: {exc}",
            "output": output,
            "stats": _parse_summary(output),
        }
