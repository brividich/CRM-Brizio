"""Redaction service for AI context - masks sensitive data"""

import re
from typing import Any, Dict, List, Optional, Union


SENSITIVE_FIELDS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "clientsecret",
    "authorization",
    "bearer",
    "webhook_url",
    "webhookurl",
    "connection_string",
    "connectionstring",
    "private_key",
    "privatekey",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "auth_token",
    "authtoken",
    "session_token",
    "sessiontoken",
    "csrf_token",
    "csrftoken",
    "jwt",
    "oauth_token",
    "oauthtoken",
    "api_secret",
    "apisecret",
    "webhook_secret",
    "webhooksecret",
    "signing_key",
    "signingkey",
    "encryption_key",
    "encryptionkey",
    "database_password",
    "databasepassword",
    "db_password",
    "dbpassword",
    "smtp_password",
    "smtppassword",
    "ftp_password",
    "ftppassword",
    "ssh_key",
    "sshkey",
    "ssh_password",
    "sshpassword",
    "aws_secret_key",
    "awssecretkey",
    "aws_access_key",
    "awsaccesskey",
    "azure_secret",
    "gcp_key",
    "gcpkey",
}

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "api-key",
    "apikey",
    "client_secret",
    "clientsecret",
    "authorization",
    "credential",
    "webhook",
    "connection",
    "connstr",
    "private_key",
    "privatekey",
    "sharedaccesskey",
    "accountkey",
)

SENSITIVE_PATTERNS = [
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"Basic\s+[A-Za-z0-9\-._~+/]+=*",
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",  # JWT
    r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWT-like
    r"https?://[^/\s:@]+:[^/\s:@]+@[^\s]+",  # URLs with embedded credentials
    r"https?://[^\s]*(?:webhook|hooks\.slack(?:\.com)?|teams\.microsoft|outlook\.office|logic\.azure|powerautomate)[^\s]*",
    r"(?:Password|AccountKey|SharedAccessKey|Secret)\s*=\s*[^;,\s]+",
    r"(?:api\s*[_-]?\s*key|secret|password|token)\s*[:=]\s*[A-Za-z0-9_\-./+=]{8,}",  # Fixed pattern
    r"\b(?:xox[baprs]-|gh[pousr]_|glpat-|ya29\.|sk_live-|sk_test-|sk-)[A-Za-z0-9_\-\.]{16,}\b",
    # r"[A-Za-z0-9]{32,}",  # Too aggressive - removed
    r"sk-[a-zA-Z0-9]{32,}",  # OpenAI-style keys
    r"pk-[a-zA-Z0-9]{32,}",  # Stripe public keys
    r"sk_live-[a-zA-Z0-9]{32,}",  # Stripe secret keys
    r"AIza[A-Za-z0-9\-_]{35}",  # Google API keys
    r"ya29\.[A-Za-z0-9\-_]+",  # Google OAuth tokens
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email addresses
    r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",  # IP addresses
]

USEFUL_FIELDS = {
    "cve",
    "cve_ids",
    "cvss",
    "max_cvss",
    "severity",
    "status",
    "exposed_devices",
    "max_exposed_devices",
    "affected_product",
    "source_name",
    "parser_name",
    "event_type",
    "report_type",
    "hostname",
    "ip_address",
    "asset_type",
    "owner",
    "title",
    "description",
    "created_at",
    "updated_at",
    "first_seen_at",
    "last_seen_at",
    "occurrence_count",
    "dedup_hash",
    "decision_trace",
    "parse_status",
    "report_date",
    "metric_name",
    "value",
    "unit",
    "labels",
    "action",
    "actor",
    "details",
    "reason",
    "name",
    "code",
    "enabled",
    "source_type",
    "condition_operator",
    "threshold_value",
    "cooldown_minutes",
    "dedup_window_minutes",
    "auto_create_ticket",
    "auto_create_evidence_container",
    "last_triggered_at",
    "trigger_count",
    "is_active",
    "starts_at",
    "expires_at",
    "hit_count",
    "last_hit_at",
    "scope_type",
    "match_payload",
    "conditions_json",
    "created_by",
    "acknowledged_at",
    "closed_at",
    "snoozed_until",
    "status_reason",
    "organization",
    "source_system",
    "item_type",
    "content",
    "sender_allowlist_text",
    "subject_include_text",
    "subject_exclude_text",
    "mailbox_address",
    "configuration",
    "last_sync_at",
    "parsed_at",
    "parsed_payload",
}


def redact_text(text: str) -> str:
    """Redact sensitive patterns from text"""
    if not isinstance(text, str):
        return text

    redacted = text

    for pattern in SENSITIVE_PATTERNS:
        redacted = re.sub(pattern, "[REDACTED]", redacted, flags=re.IGNORECASE)

    return redacted


def is_sensitive_key(key: str) -> bool:
    """Return True when a dictionary key likely names a secret value."""
    key_lower = str(key).lower()
    return key_lower in SENSITIVE_FIELDS or any(fragment in key_lower for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_dict(data: Dict[str, Any], preserve_structure: bool = True) -> Dict[str, Any]:
    """Redact sensitive fields from dictionary"""
    if not isinstance(data, dict):
        return data

    redacted = {}

    for key, value in data.items():
        key_lower = key.lower()

        if is_sensitive_key(key_lower):
            if preserve_structure:
                redacted[key] = "[REDACTED]"
            continue

        if isinstance(value, dict):
            redacted[key] = redact_dict(value, preserve_structure)
        elif isinstance(value, list):
            redacted[key] = redact_list(value, preserve_structure)
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value

    return redacted


def redact_list(data: List[Any], preserve_structure: bool = True) -> List[Any]:
    """Redact sensitive fields from list"""
    if not isinstance(data, list):
        return data

    redacted = []

    for item in data:
        if isinstance(item, dict):
            redacted.append(redact_dict(item, preserve_structure))
        elif isinstance(item, list):
            redacted.append(redact_list(item, preserve_structure))
        elif isinstance(item, str):
            redacted.append(redact_text(item))
        else:
            redacted.append(item)

    return redacted


def redact_ai_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Redact sensitive data from AI context"""
    if not isinstance(context, dict):
        return context

    redacted = {}

    for key, value in context.items():
        key_lower = key.lower()

        if is_sensitive_key(key_lower):
            redacted[key] = "[REDACTED]"
        elif key_lower in USEFUL_FIELDS:
            if isinstance(value, dict):
                redacted[key] = redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = redact_list(value)
            elif isinstance(value, str):
                redacted[key] = redact_text(value)
            else:
                redacted[key] = value
        else:
            if isinstance(value, dict):
                redacted[key] = redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = redact_list(value)
            elif isinstance(value, str):
                redacted[key] = redact_text(value)
            else:
                redacted[key] = value

    return redacted
