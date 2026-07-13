"""
Non-destructive rule simulation for AI-generated configuration drafts.

This module provides simulation capabilities for alert rules without creating
any persistent data (alerts, tickets, evidence, suppressions, or configuration).
"""
import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db.models import Count, Q
from django.utils import timezone

from security.models import (
    SecurityEventRecord,
    SecurityReportMetric,
    SecurityVulnerabilityFinding,
    Severity,
)
from security.ai.services.redaction import redact_ai_context


def simulate_alert_rule(
    rule: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Simulate an alert rule against historical data without creating persistent objects.

    Args:
        rule: Rule configuration with code, name, condition_operator, threshold_value,
              threshold_json, severity, cooldown_minutes, dedup_window_minutes,
              auto_create_ticket, auto_create_evidence_container, source_type, metric_name
        options: Simulation options including lookback_days (default 30) and max_examples (default 10)

    Returns:
        Simulation result with would_create_alerts, raw_matches, deduplicated_matches,
        noise_level, confidence, warnings, recommendations, examples, and coverage
    """
    options = options or {}
    lookback_days = options.get("lookback_days", 30)
    max_examples = options.get("max_examples", 10)

    # Validate rule structure
    validation_error = _validate_rule(rule)
    if validation_error:
        return {
            "simulation_id": _generate_simulation_id(),
            "safe": False,
            "would_create_alerts": 0,
            "raw_matches": 0,
            "deduplicated_matches": 0,
            "suppressed_matches": 0,
            "would_create_tickets": 0,
            "would_create_evidence_containers": 0,
            "noise_level": "low",
            "confidence": "low",
            "summary": f"Invalid rule: {validation_error}",
            "warnings": [validation_error],
            "recommendations": [],
            "examples": [],
            "coverage": {
                "lookback_days": lookback_days,
                "events_checked": 0,
                "metrics_checked": 0,
                "findings_checked": 0,
                "reports_checked": 0,
            },
        }

    # Determine what data to simulate against
    metric_name = rule.get("metric_name", "").strip()
    threshold_json = rule.get("threshold_json", {})
    source_type = rule.get("source_type", "").strip().lower()
    condition_operator = rule.get("condition_operator", "gte")
    threshold_value = str(rule.get("threshold_value", "")).strip()

    # Initialize counters
    raw_matches = 0
    deduplicated_matches = 0
    suppressed_matches = 0
    examples: List[Dict[str, Any]] = []
    coverage = {
        "lookback_days": lookback_days,
        "events_checked": 0,
        "metrics_checked": 0,
        "findings_checked": 0,
        "reports_checked": 0,
    }

    # Simulate against metrics if metric_name is specified
    if metric_name:
        metric_results = _simulate_against_metrics(
            rule, lookback_days, max_examples, coverage
        )
        raw_matches += metric_results["raw_matches"]
        examples.extend(metric_results["examples"])

    # Simulate against vulnerability findings if threshold_json contains vulnerability conditions
    if _has_vulnerability_conditions(threshold_json) or _is_defender_critical_rule(rule):
        vuln_results = _simulate_against_vulnerabilities(
            rule, lookback_days, max_examples, coverage
        )
        raw_matches += vuln_results["raw_matches"]
        examples.extend(vuln_results["examples"])

    # Simulate against events if source_type indicates event-based data
    if _is_event_based_rule(rule):
        event_results = _simulate_against_events(
            rule, lookback_days, max_examples, coverage
        )
        raw_matches += event_results["raw_matches"]
        suppressed_matches += event_results["suppressed_matches"]
        examples.extend(event_results["examples"])

    # Apply deduplication simulation
    dedup_window_minutes = rule.get("dedup_window_minutes", 1440)
    cooldown_minutes = rule.get("cooldown_minutes", 60)
    deduplicated_matches = _simulate_deduplication(
        raw_matches, dedup_window_minutes, cooldown_minutes
    )

    # Calculate noise level
    noise_level = _calculate_noise_level(deduplicated_matches, raw_matches)

    # Calculate confidence
    confidence = _calculate_confidence(rule, coverage, raw_matches)

    # Calculate would_create_tickets and would_create_evidence_containers
    auto_create_ticket = rule.get("auto_create_ticket", False)
    auto_create_evidence = rule.get("auto_create_evidence_container", True)
    would_create_tickets = deduplicated_matches if auto_create_ticket else 0
    would_create_evidence_containers = deduplicated_matches if auto_create_evidence else 0

    # Generate warnings
    warnings = _generate_warnings(
        rule, raw_matches, deduplicated_matches, noise_level, confidence
    )

    # Generate recommendations
    recommendations = _generate_recommendations(
        rule, raw_matches, deduplicated_matches, noise_level, warnings
    )

    # Generate summary
    summary = _generate_summary(
        rule, raw_matches, deduplicated_matches, noise_level, confidence
    )

    # Limit examples
    examples = examples[:max_examples]

    return {
        "simulation_id": _generate_simulation_id(),
        "safe": True,
        "would_create_alerts": deduplicated_matches,
        "raw_matches": raw_matches,
        "deduplicated_matches": deduplicated_matches,
        "suppressed_matches": suppressed_matches,
        "would_create_tickets": would_create_tickets,
        "would_create_evidence_containers": would_create_evidence_containers,
        "noise_level": noise_level,
        "confidence": confidence,
        "summary": summary,
        "warnings": warnings,
        "recommendations": recommendations,
        "examples": examples,
        "coverage": coverage,
    }


def _validate_rule(rule: Dict[str, Any]) -> Optional[str]:
    """Validate rule structure and return error message if invalid."""
    if not rule.get("code"):
        return "code is required"
    if not rule.get("name"):
        return "name is required"

    valid_operators = ["gt", "gte", "lt", "lte", "eq", "neq", "contains", "regex", "baseline_deviation"]
    condition_operator = rule.get("condition_operator", "gte")
    if condition_operator not in valid_operators:
        return f"condition_operator must be one of: {', '.join(valid_operators)}"

    valid_severities = [choice[0] for choice in Severity.choices]
    severity = rule.get("severity", "medium").lower()
    if severity not in valid_severities:
        return f"severity must be one of: {', '.join(valid_severities)}"

    cooldown = rule.get("cooldown_minutes", 60)
    dedup_window = rule.get("dedup_window_minutes", 1440)
    if not isinstance(cooldown, int) or cooldown < 0:
        return "cooldown_minutes must be a non-negative integer"
    if not isinstance(dedup_window, int) or dedup_window < 0:
        return "dedup_window_minutes must be a non-negative integer"

    threshold_json = rule.get("threshold_json", {})
    if threshold_json and not isinstance(threshold_json, dict):
        return "threshold_json must be a JSON object"

    return None


def _has_vulnerability_conditions(threshold_json: Dict[str, Any]) -> bool:
    """Check if threshold_json contains vulnerability-related conditions."""
    vuln_keys = {"severity", "cvss", "exposed_devices", "affected_product", "cve", "status"}
    return any(key in threshold_json for key in vuln_keys)


def _is_defender_critical_rule(rule: Dict[str, Any]) -> bool:
    """Check if rule looks like a Defender critical CVE rule."""
    combined = " ".join([
        rule.get("source_type", ""),
        rule.get("metric_name", ""),
        rule.get("threshold_value", ""),
        json.dumps(rule.get("threshold_json", {}), sort_keys=True),
    ]).lower()
    return (
        rule.get("severity", "").lower() == Severity.CRITICAL
        and "defender" in combined
        and ("cvss" in combined or "exposed" in combined)
    )


def _is_event_based_rule(rule: Dict[str, Any]) -> bool:
    """Check if rule is event-based based on source_type or other indicators."""
    source_type = rule.get("source_type", "").lower()
    event_indicators = {"watchguard", "vpn", "firewall", "network", "endpoint"}
    return any(indicator in source_type for indicator in event_indicators)


def _simulate_against_metrics(
    rule: Dict[str, Any],
    lookback_days: int,
    max_examples: int,
    coverage: Dict[str, int],
) -> Dict[str, Any]:
    """Simulate rule against SecurityReportMetric records."""
    metric_name = rule.get("metric_name", "").strip()
    if not metric_name:
        return {"raw_matches": 0, "examples": []}

    lookback_start = timezone.now() - timedelta(days=lookback_days)
    metrics = SecurityReportMetric.objects.filter(
        name=metric_name,
        created_at__gte=lookback_start,
    ).order_by("-created_at")

    coverage["metrics_checked"] = metrics.count()

    raw_matches = 0
    examples: List[Dict[str, Any]] = []

    for metric in metrics[:max_examples * 2]:  # Check more to find matches
        if _rule_matches_value(
            rule,
            metric.value,
            metric.labels or {},
        ):
            raw_matches += 1
            if len(examples) < max_examples:
                examples.append({
                    "source_model": "SecurityReportMetric",
                    "source_id": str(metric.id),
                    "timestamp": metric.created_at.isoformat(),
                    "source": f"Report {metric.report_id}",
                    "severity": "info",
                    "matched_field": metric_name,
                    "matched_value": str(metric.value),
                    "reason": f"Metric {metric_name} matched condition",
                    "redacted_payload_preview": _redact_metric_preview(metric),
                })

    return {"raw_matches": raw_matches, "examples": examples}


def _simulate_against_vulnerabilities(
    rule: Dict[str, Any],
    lookback_days: int,
    max_examples: int,
    coverage: Dict[str, int],
) -> Dict[str, Any]:
    """Simulate rule against SecurityVulnerabilityFinding records."""
    lookback_start = timezone.now() - timedelta(days=lookback_days)
    findings = SecurityVulnerabilityFinding.objects.filter(
        first_seen_at__gte=lookback_start,
    ).order_by("-first_seen_at")

    coverage["findings_checked"] = findings.count()

    raw_matches = 0
    examples: List[Dict[str, Any]] = []

    for finding in findings[:max_examples * 2]:
        payload = finding.payload or {}
        payload.update({
            "cvss": finding.cvss,
            "exposed_devices": finding.exposed_devices,
            "severity": finding.severity,
            "status": finding.status,
            "cve": finding.cve,
            "affected_product": finding.affected_product,
        })

        if _rule_matches_value(rule, finding.cvss, payload):
            raw_matches += 1
            if len(examples) < max_examples:
                examples.append({
                    "source_model": "SecurityVulnerabilityFinding",
                    "source_id": str(finding.id),
                    "timestamp": finding.first_seen_at.isoformat(),
                    "source": f"Source {finding.source_id}",
                    "severity": finding.severity,
                    "matched_field": "cvss",
                    "matched_value": str(finding.cvss),
                    "reason": f"Vulnerability {finding.cve} matched condition",
                    "redacted_payload_preview": _redact_vulnerability_preview(finding),
                })

    return {"raw_matches": raw_matches, "examples": examples}


def _simulate_against_events(
    rule: Dict[str, Any],
    lookback_days: int,
    max_examples: int,
    coverage: Dict[str, int],
) -> Dict[str, Any]:
    """Simulate rule against SecurityEventRecord records."""
    lookback_start = timezone.now() - timedelta(days=lookback_days)
    events = SecurityEventRecord.objects.filter(
        occurred_at__gte=lookback_start,
    ).order_by("-occurred_at")

    coverage["events_checked"] = events.count()

    raw_matches = 0
    suppressed_matches = 0
    examples: List[Dict[str, Any]] = []

    for event in events[:max_examples * 2]:
        payload = event.payload or {}

        if _rule_matches_value(rule, event.severity, payload):
            if event.suppressed:
                suppressed_matches += 1
            else:
                raw_matches += 1

            if len(examples) < max_examples and not event.suppressed:
                examples.append({
                    "source_model": "SecurityEventRecord",
                    "source_id": str(event.id),
                    "timestamp": event.occurred_at.isoformat(),
                    "source": f"Source {event.source_id}",
                    "severity": event.severity,
                    "matched_field": event.event_type,
                    "matched_value": event.severity,
                    "reason": f"Event {event.event_type} matched condition",
                    "redacted_payload_preview": _redact_event_preview(event),
                })

    return {"raw_matches": raw_matches, "suppressed_matches": suppressed_matches, "examples": examples}


def _rule_matches_value(rule: Dict[str, Any], value: Any, payload: Dict[str, Any]) -> bool:
    """Check if rule matches a value using the same logic as the real rule engine."""
    operator = rule.get("condition_operator", "gte")
    threshold_value = str(rule.get("threshold_value", "")).strip()
    threshold_json = rule.get("threshold_json", {})

    # If threshold_json has conditions, check them
    if threshold_json:
        for key, expected_value in threshold_json.items():
            actual_value = payload.get(key)
            if actual_value is None:
                continue

            # Try numeric comparison
            try:
                numeric_actual = float(actual_value)
                numeric_expected = float(expected_value)
                if operator == "gt" and not (numeric_actual > numeric_expected):
                    return False
                if operator == "gte" and not (numeric_actual >= numeric_expected):
                    return False
                if operator == "lt" and not (numeric_actual < numeric_expected):
                    return False
                if operator == "lte" and not (numeric_actual <= numeric_expected):
                    return False
                if operator == "eq" and not (numeric_actual == numeric_expected):
                    return False
                if operator == "neq" and not (numeric_actual != numeric_expected):
                    return False
            except (TypeError, ValueError):
                # Fall back to string comparison
                if operator == "eq" and str(actual_value) != str(expected_value):
                    return False
                if operator == "neq" and str(actual_value) == str(expected_value):
                    return False
                if operator == "contains" and str(expected_value).lower() not in str(actual_value).lower():
                    return False

    # Use threshold_value for simple comparisons
    if threshold_value:
        try:
            numeric_value = float(value or 0)
            numeric_threshold = float(threshold_value or 0)
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
            return str(value) == str(threshold_value)
        if operator == "neq":
            return str(value) != str(threshold_value)
        if operator == "contains":
            return str(threshold_value).lower() in str(value).lower()
        if operator == "regex":
            return bool(re.search(str(threshold_value), str(value), re.I))
        if operator == "baseline_deviation":
            baseline = float(threshold_json.get("baseline", 0) or 0)
            deviation = float(threshold_json.get("deviation", numeric_threshold or 0) or 0)
            return numeric_value is not None and baseline and abs(numeric_value - baseline) >= deviation

    return False


def _simulate_deduplication(
    raw_matches: int,
    dedup_window_minutes: int,
    cooldown_minutes: int,
) -> int:
    """
    Simulate deduplication and cooldown effects.

    This is an approximation - real deduplication depends on dedup_hash and timing.
    We estimate that deduplication reduces matches by a factor based on the window size.
    """
    if raw_matches == 0:
        return 0

    # Approximate deduplication factor based on window size
    # Larger windows = more deduplication
    dedup_factor = min(0.9, dedup_window_minutes / 10080)  # Max 90% reduction for 1 week window

    # Apply cooldown reduction
    cooldown_factor = min(0.5, cooldown_minutes / 1440)  # Max 50% reduction for 1 day cooldown

    deduplicated = int(raw_matches * (1 - dedup_factor) * (1 - cooldown_factor))
    return max(1, deduplicated) if raw_matches > 0 else 0


def _calculate_noise_level(deduplicated_matches: int, raw_matches: int) -> str:
    """Calculate noise level based on match counts."""
    if deduplicated_matches <= 3:
        return "low"
    if deduplicated_matches <= 10:
        return "medium"
    if deduplicated_matches <= 30:
        return "high"
    return "critical"


def _calculate_confidence(
    rule: Dict[str, Any],
    coverage: Dict[str, int],
    raw_matches: int,
) -> str:
    """Calculate simulation confidence based on data availability and rule specificity."""
    metric_name = rule.get("metric_name", "").strip()
    threshold_json = rule.get("threshold_json", {})
    source_type = rule.get("source_type", "").strip().lower()

    total_checked = (
        coverage["events_checked"]
        + coverage["metrics_checked"]
        + coverage["findings_checked"]
    )

    # High confidence if we have data and rule is specific
    if total_checked > 0 and (metric_name or threshold_json or source_type):
        return "high"

    # Medium confidence if we have some data
    if total_checked > 0:
        return "medium"

    # Low confidence if no data or rule is too generic
    return "low"


def _generate_warnings(
    rule: Dict[str, Any],
    raw_matches: int,
    deduplicated_matches: int,
    noise_level: str,
    confidence: str,
) -> List[str]:
    """Generate warnings based on rule characteristics and simulation results."""
    warnings = []

    if noise_level in ("high", "critical"):
        warnings.append(f"Regola potenzialmente rumorosa ({noise_level} noise level).")

    if raw_matches > 50:
        warnings.append(f"Alto numero di match grezzi ({raw_matches}). Considera di restringere i filtri.")

    if deduplicated_matches > 30:
        warnings.append(f"Molti alert simulati ({deduplicated_matches}). Verifica se questo è intenzionale.")

    if rule.get("severity") == Severity.CRITICAL and deduplicated_matches > 10:
        warnings.append("Regola critical con molti alert simulati. Considera di ridurre la severità.")

    cooldown = rule.get("cooldown_minutes", 60)
    if cooldown < 60 and deduplicated_matches > 5:
        warnings.append("Cooldown molto basso. Considera di aumentarlo per ridurre il rumore.")

    dedup_window = rule.get("dedup_window_minutes", 1440)
    if dedup_window < 60 and deduplicated_matches > 5:
        warnings.append("Finestra dedup molto bassa. Considera di aumentarla per ridurre il rumore.")

    if confidence == "low":
        warnings.append("Simulazione poco affidabile: condizioni insufficienti o dati storici mancanti.")

    if not rule.get("source_type") and not rule.get("metric_name"):
        warnings.append("Regola generica: aggiungi source_type o metric_name per migliorare la specificità.")

    return warnings


def _generate_recommendations(
    rule: Dict[str, Any],
    raw_matches: int,
    deduplicated_matches: int,
    noise_level: str,
    warnings: List[str],
) -> List[str]:
    """Generate deterministic recommendations based on rule characteristics."""
    recommendations = []

    if noise_level in ("high", "critical"):
        recommendations.append("Aumenta cooldown_minutes o dedup_window_minutes per ridurre il rumore.")

    if raw_matches > 50:
        recommendations.append("Aggiungi filtri più specifici (source_type, metric_name, severity).")

    if not rule.get("source_type"):
        recommendations.append("Specifica source_type per limitare la regola a sorgenti specifiche.")

    if not rule.get("metric_name") and rule.get("threshold_json"):
        recommendations.append("Specifica metric_name per rendere la regola più precisa.")

    if deduplicated_matches > 30:
        recommendations.append("Considera di trasformare questa regola in una KPI se è troppo rumorosa.")

    if rule.get("auto_create_ticket") and noise_level in ("high", "critical"):
        recommendations.append("Disabilita auto_create_ticket per regole rumorose.")

    if rule.get("severity") == Severity.CRITICAL and deduplicated_matches > 10:
        recommendations.append("Considera di ridurre la severità a 'high' se ci sono molti alert.")

    if _is_defender_critical_rule(rule):
        recommendations.append("Per Defender critical CVE con CVSS >= 9 e exposed_devices > 0, mantieni ticket ed evidence.")

    return recommendations


def _generate_summary(
    rule: Dict[str, Any],
    raw_matches: int,
    deduplicated_matches: int,
    noise_level: str,
    confidence: str,
) -> str:
    """Generate a human-readable summary of the simulation."""
    rule_name = rule.get("name", "Regola")
    return (
        f"Simulazione per '{rule_name}': {raw_matches} match grezzi, "
        f"{deduplicated_matches} alert simulati dopo deduplicazione. "
        f"Noise level: {noise_level}, Confidence: {confidence}."
    )


def _redact_metric_preview(metric: SecurityReportMetric) -> Dict[str, Any]:
    """Redact sensitive information from metric preview."""
    return {
        "name": metric.name,
        "value": metric.value,
        "unit": metric.unit,
        "labels": redact_ai_context(metric.labels or {}),
    }


def _redact_vulnerability_preview(finding: SecurityVulnerabilityFinding) -> Dict[str, Any]:
    """Redact sensitive information from vulnerability preview."""
    return {
        "cve": finding.cve,
        "affected_product": finding.affected_product,
        "cvss": finding.cvss,
        "exposed_devices": finding.exposed_devices,
        "severity": finding.severity,
        "status": finding.status,
    }


def _redact_event_preview(event: SecurityEventRecord) -> Dict[str, Any]:
    """Redact sensitive information from event preview."""
    return {
        "event_type": event.event_type,
        "severity": event.severity,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": redact_ai_context(event.payload or {}),
    }


def _generate_simulation_id() -> str:
    """Generate a unique simulation ID."""
    import uuid
    return f"sim-{uuid.uuid4().hex[:12]}"
