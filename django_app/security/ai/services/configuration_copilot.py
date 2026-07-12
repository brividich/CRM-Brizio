"""Configuration Copilot service for AI-assisted configuration

Builds safe context and generates structured configuration drafts.
Never creates/updates/deletes production config automatically.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from django.db.models import Count, Q
from django.utils import timezone

from ..services.ai_gateway import chat_completion
from ..services.redaction import redact_ai_context, redact_text
from ...models import (
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityMailboxSource,
    SecurityParserConfig,
    SecuritySourceConfig,
)
from ...parsers import parser_registry

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 15000
MAX_SAMPLE_CHARS = 10000
MAX_PROMPT_CHARS = 2000

ALLOWED_TASKS = {
    "suggest_source",
    "suggest_rule",
    "improve_rule",
    "explain_rule",
    "suggest_suppression",
    "review_configuration",
    "test_plan",
}

SYSTEM_PROMPT = """Sei Security Center AI Configuration Copilot.

Il tuo compito è aiutare gli operatori a configurare sorgenti, parser e regole di alert.

REGOLE IMPORTANTI:
1. Restituisci SOLO JSON valido, niente altro testo.
2. Non inventare sorgenti o regole esistenti. Usa il contesto fornito.
3. Se non sei sicuro, usa confidence="low" e missing_information.
4. Non includere mai segreti (API key, password, token, webhook URL).
5. Le bozze richiedono revisione operatore. Non salvare automaticamente.
6. Preferisci anti-noise: dedup, cooldown, aggregazione.
7. Per regole critiche/high, suggerisci evidence container e ticket.
8. Per WatchGuard low/closed ad alto volume, preferisci KPI/baseline, non alert storm.
9. Per Defender CVE critical CVSS >= 9 con exposed_devices > 0, suggerisci Critical + evidence + ticket.
10. Per backup completed, tratta come KPI positivo; failed/missing/anomalous possono alert.

Risposta JSON deve seguire questo schema:
{
  "task": "...",
  "summary": "...",
  "confidence": "low|medium|high",
  "draft": {...},
  "rationale": [...],
  "warnings": [...],
  "missing_information": [...],
  "simulation_suggestion": {...},
  "safe_to_apply": false,
  "requires_review": true
}
"""


def build_configuration_context() -> Dict[str, Any]:
    """Build safe configuration context for AI

    Returns context with sources, parsers, rules, suppressions, notifications,
    recent activity, capabilities, warnings, and limits.
    """
    try:
        now = timezone.now()

        # Sources summary
        sources = SecurityMailboxSource.objects.all().order_by("-enabled", "name")
        source_configs = SecuritySourceConfig.objects.all().order_by("-enabled", "vendor", "name")
        sources_summary = []
        for source in sources[:20]:
            sources_summary.append({
                "code": source.code,
                "name": source.name,
                "enabled": source.enabled,
                "source_type": source.source_type,
                "parser_names": _detect_parsers_for_source(source),
                "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
                "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
            })
        for source_config in source_configs[:20]:
            sources_summary.append({
                "code": f"source-config-{source_config.id}",
                "name": source_config.name,
                "enabled": source_config.enabled,
                "source_type": source_config.source_type,
                "vendor": source_config.vendor,
                "parser_names": [source_config.parser_name] if source_config.parser_name else [],
                "expected_frequency": source_config.expected_frequency,
                "last_success_at": None,
                "last_error_at": None,
            })

        # Parsers summary
        parsers_summary = []
        for parser in parser_registry.all()[:20]:
            parser_code = getattr(parser, "code", getattr(parser, "__name__", "unknown"))
            parser_name = getattr(parser, "name", parser_code)
            parser_description = getattr(parser, "description", "")
            parsers_summary.append({
                "code": parser_code,
                "name": parser_name,
                "description": parser_description,
            })

        # Rules summary
        rules = SecurityAlertRuleConfig.objects.all().order_by("-enabled", "name")
        rules_summary = []
        for rule in rules[:20]:
            rules_summary.append({
                "code": rule.code,
                "name": rule.name,
                "enabled": rule.enabled,
                "source_type": rule.source_type,
                "severity": rule.severity,
                "metric_name": rule.metric_name,
                "condition_operator": rule.condition_operator,
                "threshold_value": rule.threshold_value,
                "cooldown_minutes": rule.cooldown_minutes,
                "dedup_window_minutes": rule.dedup_window_minutes,
                "auto_create_ticket": rule.auto_create_ticket,
                "auto_create_evidence_container": rule.auto_create_evidence_container,
                "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
                "trigger_count": rule.trigger_count,
            })

        # Suppressions summary
        suppressions = SecurityAlertSuppressionRule.objects.filter(is_active=True).order_by("-created_at")
        suppressions_summary = []
        for supp in suppressions[:10]:
            suppressions_summary.append({
                "code": f"supp-{supp.id}",
                "name": supp.name,
                "event_type": supp.event_type,
                "severity": supp.severity,
                "scope_type": supp.scope_type,
                "expires_at": supp.expires_at.isoformat() if supp.expires_at else None,
                "hit_count": supp.hit_count,
            })

        # Notifications summary (static for now)
        notifications_summary = [
            {"code": "dashboard", "name": "Dashboard Security Center", "enabled": True},
            {"code": "email", "name": "Email operativa", "enabled": True},
            {"code": "teams", "name": "Microsoft Teams", "enabled": False},
            {"code": "ticket", "name": "Sistema ticket operativo", "enabled": True},
        ]

        # Recent activity
        recent_activity = {
            "sources_count": sources.count() + source_configs.count(),
            "enabled_sources_count": sources.filter(enabled=True).count() + source_configs.filter(enabled=True).count(),
            "parsers_count": len(parsers_summary),
            "rules_count": rules.count(),
            "active_rules_count": rules.filter(enabled=True).count(),
            "suppressions_count": suppressions.count(),
            "active_suppressions_count": suppressions.filter(is_active=True).count(),
            "notifications_count": len(notifications_summary),
        }

        # Capabilities
        capabilities = {
            "supported_source_types": ["email", "graph", "manual", "pdf", "csv"],
            "supported_vendors": ["WatchGuard", "Microsoft Defender", "Synology", "custom"],
            "supported_severities": ["critical", "high", "medium", "low", "info"],
            "supported_operators": ["eq", "gte", "lte", "contains", "regex"],
        }

        # Warnings
        warnings = []
        if not sources.filter(enabled=True).exists() and not source_configs.filter(enabled=True).exists():
            warnings.append("Nessuna sorgente abilitata")
        if not rules.filter(enabled=True).exists():
            warnings.append("Nessuna regola abilitata")
        sources_without_parser = [s for s in sources if not _detect_parsers_for_source(s)]
        sources_without_parser.extend([s for s in source_configs if s.enabled and not s.parser_name])
        if sources_without_parser:
            warnings.append(f"{len(sources_without_parser)} sorgenti senza parser rilevato")
        rules_without_cooldown = rules.filter(enabled=True, cooldown_minutes__isnull=True)
        if rules_without_cooldown.exists():
            warnings.append(f"{rules_without_cooldown.count()} regole senza cooldown")

        # Limits
        limits = {
            "truncated": False,
            "max_chars": MAX_CONTEXT_CHARS,
        }

        context = {
            "context_available": True,
            "sources": sources_summary,
            "parsers": parsers_summary,
            "rules": rules_summary,
            "suppressions": suppressions_summary,
            "notifications": notifications_summary,
            "recent_activity": recent_activity,
            "capabilities": capabilities,
            "warnings": warnings,
            "limits": limits,
        }

        # Truncate if too large
        context_json = json.dumps(context, ensure_ascii=False, default=str)
        if len(context_json) > MAX_CONTEXT_CHARS:
            context["limits"]["truncated"] = True
            # Truncate lists proportionally
            context["sources"] = context["sources"][:10]
            context["rules"] = context["rules"][:10]
            context["parsers"] = context["parsers"][:10]

        return context

    except Exception as e:
        logger.exception("Error building configuration context")
        return {
            "context_available": False,
            "error": "error_building_context",
            "warnings": ["Impossibile caricare il contesto completo"],
        }


def _detect_parsers_for_source(source: SecurityMailboxSource) -> List[str]:
    """Detect parsers for a source based on name/code"""
    name_lower = source.name.lower()
    code_lower = source.code.lower()

    parsers = []
    if "watchguard" in name_lower or "epdr" in name_lower or "watchguard" in code_lower:
        parsers.extend(["watchguard_report_parser", "watchguard_epdr_parser"])
    if "defender" in name_lower or "microsoft" in name_lower or "defender" in code_lower:
        parsers.append("microsoft_defender_vulnerability_notification_email_parser")
    if "synology" in name_lower or "backup" in name_lower or "synology" in code_lower:
        parsers.append("synology_active_backup_email_parser")

    return list(set(parsers)) if parsers else ["unknown"]


def build_configuration_copilot_prompt(
    task: str,
    user_prompt: str,
    context: Dict[str, Any],
    draft: Optional[Dict[str, Any]] = None,
    sample: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Build AI prompt for configuration copilot

    Args:
        task: One of the allowed tasks
        user_prompt: User's natural language request
        context: Configuration context
        draft: Optional existing draft to improve
        sample: Optional safe sample data
        scope: Optional scope (source_code, parser_name, rule_code)

    Returns:
        List of messages for AI completion
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add context
    redacted_context = redact_ai_context(context)
    context_str = json.dumps(redacted_context, ensure_ascii=False, default=str)
    messages.append({"role": "system", "content": f"Configuration Context:\n{context_str}"})

    # Build user message
    user_message_parts = [f"Task: {task}", f"Request: {user_prompt}"]

    if draft:
        redacted_draft = redact_ai_context(draft)
        user_message_parts.append(f"Existing Draft:\n{json.dumps(redacted_draft, ensure_ascii=False, default=str)}")

    if sample:
        redacted_sample = redact_text(sample[:MAX_SAMPLE_CHARS])
        user_message_parts.append(f"Sample Data:\n{redacted_sample}")

    if scope:
        user_message_parts.append(f"Scope: {json.dumps(scope, ensure_ascii=False)}")

    messages.append({"role": "user", "content": "\n\n".join(user_message_parts)})

    return messages


def parse_ai_response(response_content: str) -> Dict[str, Any]:
    """Parse AI response and extract JSON

    Args:
        response_content: Raw AI response content

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If JSON cannot be parsed
    """
    import re

    # Try to extract JSON from fenced code block
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_content, re.DOTALL)
    if json_match:
        content = json_match.group(1)
    else:
        content = response_content

    # Clean control characters
    content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI response as JSON: {e}")
        raise ValueError(f"Invalid JSON response: {e}")


def validate_task(task: str) -> bool:
    """Validate task is allowed"""
    return task in ALLOWED_TASKS


def validate_user_prompt(prompt: str) -> bool:
    """Validate user prompt"""
    if not isinstance(prompt, str):
        return False
    if not prompt.strip():
        return False
    if len(prompt) > MAX_PROMPT_CHARS:
        return False
    return True


def context_quality_score(context: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate context quality score

    Returns:
        Dict with score (0-100) and level (empty|poor|partial|good|complete)
    """
    if not context.get("context_available"):
        return {"score": 0, "level": "empty"}

    score = 0
    activity = context.get("recent_activity", {})

    # Sources
    if activity.get("sources_count", 0) > 0:
        score += 20
    if activity.get("enabled_sources_count", 0) > 0:
        score += 10

    # Rules
    if activity.get("rules_count", 0) > 0:
        score += 20
    if activity.get("active_rules_count", 0) > 0:
        score += 10

    # Parsers
    if activity.get("parsers_count", 0) > 0:
        score += 15

    # Notifications
    if activity.get("notifications_count", 0) > 0:
        score += 10

    # Suppressions
    if activity.get("suppressions_count", 0) > 0:
        score += 5

    # Cap at 100
    score = min(score, 100)

    # Determine level
    if score >= 80:
        level = "complete"
    elif score >= 60:
        level = "good"
    elif score >= 40:
        level = "partial"
    elif score >= 20:
        level = "poor"
    else:
        level = "empty"

    return {"score": score, "level": level}
