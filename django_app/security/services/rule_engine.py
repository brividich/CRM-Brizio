from django.db.models import Count
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, SecurityAlertRuleConfig, SecurityAlertSuppressionRule, SecurityEventRecord, Severity, Status
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.evidence_builder import build_evidence_container
from security.services.ticketing import create_backup_ticket, create_or_update_remediation_ticket_for_vulnerability_finding


def evaluate_security_rules():
    evaluated = 0
    for event in SecurityEventRecord.objects.filter(decision_trace={}).order_by("occurred_at"):
        evaluated += 1
        suppression = _matching_suppression(event)
        if suppression:
            _mark_suppressed(event, suppression)
            continue
        if event.event_type == "vulnerability_finding":
            _evaluate_vulnerability(event)
        elif event.event_type == "backup_job":
            _evaluate_backup(event)
        elif event.event_type in {"vpn_auth_denied", "vpn_auth_allowed"}:
            _evaluate_vpn(event)
        elif event.event_type == "watchguard_alert_candidate":
            _evaluate_watchguard_alert_candidate(event)
        else:
            event.decision_trace = {"decision": "kpi_only", "reason": "No alert rule matched"}
            event.save(update_fields=["decision_trace"])
    return evaluated


def _matching_suppression(event):
    for rule in SecurityAlertSuppressionRule.objects.filter(is_active=True):
        if rule.matches(event):
            return rule
    return None


def _mark_suppressed(event, rule):
    event.suppressed = True
    event.decision_trace = {"decision": "suppressed_kpi_only", "rule": rule.name, "reason": rule.reason}
    event.save(update_fields=["suppressed", "decision_trace"])
    rule.hit_count += 1
    rule.last_hit_at = timezone.now()
    rule.save(update_fields=["hit_count", "last_hit_at", "updated_at"])


def _evaluate_vulnerability(event):
    payload = event.payload
    cvss = float(payload.get("cvss") or 0)
    critical_rule = _get_rule("defender_critical_cve_cvss_gte_9")
    exposed_rule = _get_rule("defender_critical_cve_exposed_devices_gt_0")
    is_critical = _rule_matches(critical_rule, cvss, payload) if critical_rule else (payload.get("severity") == Severity.CRITICAL or cvss >= 9)
    exposed_count = int(payload.get("exposed_devices", 0))
    exposed = _rule_matches(exposed_rule, exposed_count, payload) if exposed_rule else exposed_count > 0
    if is_critical and exposed:
        trace = {
            "decision": "alert",
            "rule": "CVE Critical/CVSS >= 9/exposed_devices > 0",
            "cvss": payload.get("cvss"),
            "exposed_devices": payload.get("exposed_devices"),
        }
        alert, alert_created = _get_or_create_active_alert(
            source=event.source,
            event=event,
            title=f"Critical exposed vulnerability {payload.get('cve')}",
            severity=(critical_rule.severity if critical_rule else Severity.CRITICAL),
            dedup_hash=event.dedup_hash,
            decision_trace=trace,
        )
        trace["alert_created"] = alert_created
        _store_alert_decision_trace(alert, trace, alert_created)
        event.decision_trace = trace
        event.save(update_fields=["decision_trace"])
        evidence = build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
        create_or_update_remediation_ticket_for_vulnerability_finding(
            event.source,
            alert,
            evidence,
            payload,
            dedup_hash=event.dedup_hash,
        )
        SecurityAlertActionLog.objects.create(
            alert=alert,
            action="alert_created" if alert_created else "alert_reused",
            details=trace,
        )
        _mark_rule_triggered(critical_rule)
        _mark_rule_triggered(exposed_rule)
    else:
        event.decision_trace = {"decision": "kpi_only", "reason": "Vulnerability not both critical and exposed"}
        event.save(update_fields=["decision_trace"])


def _evaluate_backup(event):
    status = event.payload.get("status", "").lower()
    if status == "completed":
        event.decision_trace = {"decision": "kpi_only", "rule": "Backup completed => KPI only"}
        event.save(update_fields=["decision_trace"])
        return
    if status == "unknown":
        event.decision_trace = {"decision": "diagnostic_event", "rule": "Backup status unknown => diagnostic only"}
        event.save(update_fields=["decision_trace"])
        return
    failed_rule = _get_rule("backup_failed_gt_0")
    if failed_rule and not failed_rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "Backup failure rule disabled"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {"decision": "alert", "rule": "Backup missing/failed => alert + evidence", "backup_status": status}
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=f"Backup job requires attention: {event.payload.get('job_name')}",
        severity=(failed_rule.severity if failed_rule else Severity.WARNING),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    evidence = build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    create_backup_ticket(event.source, alert, evidence, event.payload.get("job_name"), event.dedup_hash)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(failed_rule)


def _evaluate_vpn(event):
    window_start = timezone.now() - timezone.timedelta(hours=1)
    count = SecurityEventRecord.objects.filter(
        source=event.source,
        event_type=event.event_type,
        occurred_at__gte=window_start,
    ).aggregate(total=Count("id"))["total"]
    threshold = int(event.payload.get("threshold", 10))
    if count > threshold:
        trace = {"decision": "alert", "rule": "VPN reconnect spike above threshold", "count": count, "threshold": threshold}
        alert, alert_created = _get_or_create_active_alert(
            source=event.source,
            event=event,
            title="VPN authentication spike detected",
            severity=Severity.WARNING,
            dedup_hash=event.dedup_hash,
            decision_trace=trace,
        )
        trace["alert_created"] = alert_created
        _store_alert_decision_trace(alert, trace, alert_created)
        SecurityAlertActionLog.objects.create(
            alert=alert,
            action="alert_created" if alert_created else "alert_reused",
            details=trace,
        )
        event.decision_trace = trace
    else:
        event.decision_trace = {"decision": "kpi_only", "reason": "VPN volume below threshold", "count": count, "threshold": threshold}
    event.save(update_fields=["decision_trace"])


def _evaluate_watchguard_alert_candidate(event):
    payload = event.payload
    candidate_type = payload.get("type") or ""
    rule = _get_rule(candidate_type) or _get_rule("watchguard_botnet_detected_gt_baseline")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "WatchGuard alert rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "WatchGuard parser-generated anti-noise alert candidate",
        "candidate_type": payload.get("type"),
        "reason": payload.get("reason"),
    }
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=payload.get("title") or "WatchGuard alert candidate",
        severity=(rule.severity if rule else payload.get("severity", Severity.WARNING)),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(rule)


def test_alert_rule(rule, metrics):
    value = metrics.get(rule.metric_name) if rule.metric_name else metrics.get("value")
    return _rule_matches(rule, value, metrics)


def _get_rule(code):
    try:
        return SecurityAlertRuleConfig.objects.get(code=code)
    except SecurityAlertRuleConfig.DoesNotExist:
        return None


def _rule_matches(rule, value, payload):
    if not rule or not rule.enabled:
        return False
    if rule.code == "defender_critical_cve_cvss_gte_9" and payload.get("severity") == Severity.CRITICAL:
        return True
    threshold = rule.threshold_value
    operator = rule.condition_operator
    if threshold == "" and rule.threshold_json:
        threshold = rule.threshold_json.get("value", "")
    try:
        numeric_value = float(value or 0)
        numeric_threshold = float(threshold or 0)
    except (TypeError, ValueError):
        numeric_value = None
        numeric_threshold = None
    if operator == "gt":
        return numeric_value is not None and numeric_value > numeric_threshold
    if operator == "gte":
        return numeric_value is not None and numeric_value >= numeric_threshold
    if operator == "lt":
        return numeric_value is not None and numeric_value < numeric_threshold
    if operator == "lte":
        return numeric_value is not None and numeric_value <= numeric_threshold
    if operator == "eq":
        return str(value) == str(threshold)
    if operator == "neq":
        return str(value) != str(threshold)
    if operator == "contains":
        return str(threshold).lower() in str(value).lower()
    if operator == "regex":
        import re

        return bool(re.search(str(threshold), str(value), re.I))
    if operator == "baseline_deviation":
        baseline = float(rule.threshold_json.get("baseline", 0) or 0)
        deviation = float(rule.threshold_json.get("deviation", numeric_threshold or 0) or 0)
        return numeric_value is not None and baseline and abs(numeric_value - baseline) >= deviation
    return False


def _mark_rule_triggered(rule):
    if not rule:
        return
    rule.last_triggered_at = timezone.now()
    rule.trigger_count += 1
    rule.save(update_fields=["last_triggered_at", "trigger_count", "updated_at"])


def _get_or_create_active_alert(source, event, title, severity, dedup_hash, decision_trace):
    alert = (
        SecurityAlert.objects.filter(source=source, dedup_hash=dedup_hash, status__in=ACTIVE_ALERT_STATUSES)
        .order_by("-updated_at")
        .first()
    )
    if alert:
        alert.event = event
        alert.save(update_fields=["event", "updated_at"])
        return alert, False
    return (
        SecurityAlert.objects.create(
            source=source,
            event=event,
            title=title,
            severity=severity,
            dedup_hash=dedup_hash,
            decision_trace=decision_trace,
        ),
        True,
    )


def _store_alert_decision_trace(alert, trace, alert_created):
    if alert_created:
        alert.decision_trace = trace
    else:
        alert.decision_trace = {**alert.decision_trace, "latest_decision": trace}
    alert.save(update_fields=["decision_trace", "updated_at"])
