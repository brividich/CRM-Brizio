"""Outbound notification delivery for Security Center alerts and tickets.

Until now ``SecurityNotificationChannel`` was configuration with no delivery behind it:
the whole backend contained no ``send_mail`` and no webhook call. A critical CVE raised
at 22:00 produced an alert, an evidence container and a ticket that nobody would see
until somebody happened to open the dashboard. This module closes that gap.

Design rules:

- **Never break the pipeline.** Delivery is best-effort: any failure is logged as a
  ``SecurityNotificationLog`` row with ``outcome=failed`` and swallowed. Detection must
  keep working even when the mail server is down.
- **Every attempt is auditable.** ``SecurityNotificationLog`` records what was sent,
  to which channel, for which alert, and why it was suppressed when it was.
- **Cooldown is per (channel, dedup_hash, event kind)**, so a recurring alert does not
  turn into a mail flood, while a *different* alert is never silenced by an unrelated one.
- **No sensitive content leaves the system.** Messages carry the alert title, severity,
  source, the decision rule that fired and identifiers - never raw report bodies,
  mailbox payloads, evidence internals or secrets.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from security.models import (
    SecurityNotificationChannel,
    SecurityNotificationLog,
    Severity,
)
from security.services.configuration import get_setting

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.WARNING: 3,
    Severity.HIGH: 4,
    Severity.CRITICAL: 5,
}

EVENT_ALERT_CREATED = "alert_created"
EVENT_TICKET_CREATED = "ticket_created"

WEBHOOK_TIMEOUT_SECONDS = 10


# -- public API ---------------------------------------------------------------

def notify_alert_created(alert) -> list[SecurityNotificationLog]:
    """Deliver a newly created alert to every eligible channel. Never raises."""
    return _dispatch(
        event_kind=EVENT_ALERT_CREATED,
        severity=alert.severity,
        dedup_hash=alert.dedup_hash or "",
        subject=_alert_subject(alert),
        body=_alert_body(alert),
        alert=alert,
        ticket=None,
    )


def notify_ticket_created(ticket) -> list[SecurityNotificationLog]:
    """Deliver a newly created remediation ticket. Never raises."""
    return _dispatch(
        event_kind=EVENT_TICKET_CREATED,
        severity=ticket.severity,
        dedup_hash=ticket.dedup_hash or "",
        subject=_ticket_subject(ticket),
        body=_ticket_body(ticket),
        alert=getattr(ticket, "alert", None),
        ticket=ticket,
    )


def eligible_channels(event_kind: str, severity: str):
    """Enabled channels subscribed to this event kind and at or below this severity."""
    level = SEVERITY_ORDER.get(severity, SEVERITY_ORDER[Severity.INFO])
    flag = {
        EVENT_ALERT_CREATED: "notify_on_new_alert",
        EVENT_TICKET_CREATED: "notify_on_ticket_created",
    }.get(event_kind)

    channels = []
    for channel in SecurityNotificationChannel.objects.filter(enabled=True):
        if flag and not getattr(channel, flag, False):
            continue
        if SEVERITY_ORDER.get(channel.severity_min, SEVERITY_ORDER[Severity.WARNING]) > level:
            continue
        channels.append(channel)
    return channels


# -- dispatch -----------------------------------------------------------------

def _dispatch(*, event_kind, severity, dedup_hash, subject, body, alert, ticket):
    logs = []
    for channel in eligible_channels(event_kind, severity):
        try:
            logs.append(
                _deliver_to_channel(
                    channel, event_kind=event_kind, severity=severity, dedup_hash=dedup_hash,
                    subject=subject, body=body, alert=alert, ticket=ticket,
                )
            )
        except Exception as exc:  # fail-safe: detection must survive a broken channel
            logger.exception("Notification channel %s failed for %s: %s", channel.name, event_kind, exc)
            logs.append(
                _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                     SecurityNotificationLog.Outcome.FAILED, error=str(exc)[:500])
            )
    return logs


def _deliver_to_channel(channel, *, event_kind, severity, dedup_hash, subject, body, alert, ticket):
    if _in_cooldown(channel, event_kind, dedup_hash):
        logger.info("Notification suppressed by cooldown: channel=%s event=%s", channel.name, event_kind)
        return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                    SecurityNotificationLog.Outcome.COOLDOWN)

    if channel.channel_type == "dashboard":
        # The alert is already visible in the UI: nothing to deliver, but record the fact
        # so the audit trail is uniform across channel types.
        return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                    SecurityNotificationLog.Outcome.SENT)

    if channel.channel_type == "email":
        recipients = parse_recipients(channel.recipients)
        if not recipients:
            return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                        SecurityNotificationLog.Outcome.FAILED, error="Email channel has no recipients")
        _send_email(subject, body, recipients)
        return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                    SecurityNotificationLog.Outcome.SENT, recipients_count=len(recipients))

    if channel.channel_type == "teams_webhook":
        url = resolve_webhook_url(channel)
        if not url:
            return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                        SecurityNotificationLog.Outcome.FAILED, error="Teams channel has no webhook URL configured")
        _post_teams_webhook(url, subject, body, severity)
        return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                    SecurityNotificationLog.Outcome.SENT, recipients_count=1)

    return _log(channel, event_kind, severity, dedup_hash, alert, ticket,
                SecurityNotificationLog.Outcome.FAILED, error=f"Unsupported channel type: {channel.channel_type}")


def _in_cooldown(channel, event_kind, dedup_hash) -> bool:
    """A recurring alert must not become a mail flood. Scoped to this alert's dedup_hash
    so an unrelated alert is never silenced by a noisy one."""
    minutes = int(channel.cooldown_minutes or 0)
    if minutes <= 0 or not dedup_hash:
        return False
    since = timezone.now() - timezone.timedelta(minutes=minutes)
    return SecurityNotificationLog.objects.filter(
        channel=channel,
        event_kind=event_kind,
        dedup_hash=dedup_hash,
        outcome=SecurityNotificationLog.Outcome.SENT,
        created_at__gte=since,
    ).exists()


def _log(channel, event_kind, severity, dedup_hash, alert, ticket, outcome, *, error="", recipients_count=0):
    return SecurityNotificationLog.objects.create(
        channel=channel,
        alert=alert,
        ticket=ticket,
        event_kind=event_kind,
        severity=severity or "",
        dedup_hash=dedup_hash or "",
        outcome=outcome,
        recipients_count=recipients_count,
        error_message=error,
    )


# -- transports ---------------------------------------------------------------

def parse_recipients(raw: str) -> list[str]:
    """Recipients may be separated by newline, comma or semicolon."""
    text = str(raw or "").replace(";", ",").replace("\n", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def resolve_webhook_url(channel) -> str:
    """``webhook_url_secret_ref`` holds either the URL itself or the key of a
    ``SecurityCenterSetting`` holding it. Both are treated as secrets and never logged."""
    ref = str(channel.webhook_url_secret_ref or "").strip()
    if not ref:
        return ""
    if ref.lower().startswith(("http://", "https://")):
        return ref
    return str(get_setting(ref, "") or "").strip()


def _send_email(subject: str, body: str, recipients: list[str]) -> None:
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=recipients,
        fail_silently=False,
    )


def _post_teams_webhook(url: str, subject: str, body: str, severity: str) -> None:
    colors = {
        Severity.CRITICAL: "D93025",
        Severity.HIGH: "E8710A",
        Severity.WARNING: "F9AB00",
        Severity.MEDIUM: "F9AB00",
    }
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": colors.get(severity, "1A73E8"),
        "summary": subject,
        "title": subject,
        "text": body.replace("\n", "\n\n"),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise RuntimeError(f"webhook returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        # Never echo the URL: it is the secret.
        raise RuntimeError(f"webhook returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("webhook unreachable") from exc


# -- message composition (no raw payloads, no secrets) ------------------------

def _alert_subject(alert) -> str:
    return f"[Security Center][{str(alert.severity).upper()}] {alert.title}"


def _alert_body(alert) -> str:
    trace = alert.decision_trace or {}
    lines = [
        f"Severity : {alert.severity}",
        f"Source   : {getattr(alert.source, 'name', '') or alert.source_id}",
        f"Status   : {alert.status}",
        f"Rule     : {trace.get('rule') or trace.get('decision') or 'n/a'}",
        f"Alert id : {alert.pk}",
    ]
    reason = trace.get("reason")
    if reason:
        lines.append(f"Reason   : {reason}")
    lines.append("")
    lines.append(_link(f"/security/alerts/{alert.pk}/"))
    return "\n".join(lines)


def _ticket_subject(ticket) -> str:
    return f"[Security Center][ticket][{str(ticket.severity).upper()}] {ticket.title}"


def _ticket_body(ticket) -> str:
    lines = [
        f"Severity  : {ticket.severity}",
        f"Product   : {ticket.affected_product or 'n/a'}",
        f"CVE       : {', '.join(ticket.cve_ids or ([ticket.cve] if ticket.cve else [])) or 'n/a'}",
        f"Max CVSS  : {ticket.max_cvss}",
        f"Exposed   : {ticket.max_exposed_devices} device(s)",
        f"Ticket id : {ticket.pk}",
        "",
        _link(f"/security/tickets/{ticket.pk}/"),
    ]
    return "\n".join(lines)


def _link(path: str) -> str:
    # In the HUB the canonical absolute base is SITE_URL (used by every other module's
    # notifications); SECURITY_CENTER_BASE_URL stays supported for the standalone deploy.
    base = str(
        getattr(settings, "SECURITY_CENTER_BASE_URL", "")
        or getattr(settings, "SITE_URL", "")
        or ""
    ).rstrip("/")
    return f"{base}{path}" if base else f"(open Security Center: {path})"
