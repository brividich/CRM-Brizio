import json
import logging
import re
import time
from typing import Any, Optional

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .ai.services.ai_gateway import chat_completion
from .ai.services.context_builder import build_ai_messages
from .ai.services.memory.ai_memory_context_builder import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    build_ai_memory_context,
)
from .ai.services.memory.document_indexer import index_document
from .ai.services.memory.memory_policy import serialize_memory_fact
from .ai.services.redaction import redact_ai_context, redact_list, redact_text
from .ai.services.configuration_copilot import (
    build_configuration_context,
    build_configuration_copilot_prompt,
    context_quality_score,
    parse_ai_response,
    validate_task,
    validate_user_prompt,
    ALLOWED_TASKS,
)
from .ai.providers.base import (
    AIProviderConfigurationError,
    AIProviderResponseError,
    AIProviderUnavailableError,
)
from .models import AIMemoryFact, SecurityAiInteractionLog
from .permissions import CanViewSecurityCenter

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 8000
MAX_HISTORY_MESSAGES = 10
MAX_CONTENT_LENGTH = 4000
MAX_SECONDARY_INPUT_CHARS = 20000
MAX_MEMORY_DOCUMENT_CHARS = 50000
MAX_LOG_ERROR_CHARS = 500
MAX_STATUS_ERROR_CHARS = 200
ALLOWED_CONTEXT_OBJECT_TYPES = {"dashboard", "alert", "report", "ticket", "evidence"}
ALLOWED_CONTEXT_PAGES = {"dashboard", "alert", "report", "ticket", "evidence", "alerts", "reports", "ai", "overview"}

VALID_AI_MEMORY_INSUFFICIENCY_FLAGS = {
    "requested_object_context_unavailable",
    "missing_context_object",
    "insufficient_internal_evidence",
    "no_approved_memory_facts",
    "no_results",
    "below_min_score",
    "ambiguous_results",
    "unsupported_claim_request",
}


def _truncate_text(value, max_length):
    text = str(value or "")
    return text[:max_length]


def _normalize_context_object_id(object_type: str, raw_object_id: Any) -> Optional[str]:
    """Normalize object_id for AI context.

    Rules:
    - For alert/report/ticket: accepts "2", 2, "alert-2", "report-2", "ticket-2"
    - For evidence: keeps UUID/hex-safe validation
    - For dashboard: no object_id required
    - Rejects: "../2", "2;DROP", "report-abc", "", null, mismatched types

    Returns:
        Normalized string ID or None if invalid
    """
    if raw_object_id is None:
        return None

    raw_str = str(raw_object_id).strip()

    if not raw_str:
        return None

    # For alert/report/ticket: handle prefixed IDs
    if object_type in {"alert", "report", "ticket"}:
        # Check for prefixed format: "alert-2", "report-2", "ticket-2"
        prefix = f"{object_type}-"
        if raw_str.startswith(prefix):
            numeric_part = raw_str[len(prefix):]
            if numeric_part.isdigit() and int(numeric_part) > 0:
                return numeric_part

        # Check for underscore format: "report_2" (optional)
        underscore_prefix = f"{object_type}_"
        if raw_str.startswith(underscore_prefix):
            numeric_part = raw_str[len(underscore_prefix):]
            if numeric_part.isdigit() and int(numeric_part) > 0:
                return numeric_part

        # Check for pure numeric: "2" or 2
        if raw_str.isdigit() and int(raw_str) > 0:
            return raw_str

        # Reject mismatched types (e.g., object_type=report but object_id=alert-2)
        return None

    # For evidence: validate UUID/hex-safe
    if object_type == "evidence":
        if re.match(r"^[0-9a-fA-F-]{1,80}$", raw_str):
            return raw_str[:80]
        return None

    # For dashboard: no object_id needed
    if object_type == "dashboard":
        return None

    return None


def _sanitize_context_metadata(raw_context):
    if not isinstance(raw_context, dict):
        return {}

    sanitized = {}
    page = raw_context.get("page")
    if isinstance(page, str):
        page = page.strip().lower()[:80]
        if page in ALLOWED_CONTEXT_PAGES:
            sanitized["page"] = page

    object_type = raw_context.get("object_type")
    if isinstance(object_type, str):
        object_type = object_type.strip().lower()[:80]
        if object_type in ALLOWED_CONTEXT_OBJECT_TYPES:
            sanitized["object_type"] = object_type

    object_type = sanitized.get("object_type")
    object_id = raw_context.get("object_id")
    if object_type and object_type != "dashboard" and object_id is not None:
        normalized_id = _normalize_context_object_id(object_type, object_id)
        if normalized_id:
            sanitized["object_id"] = normalized_id

    return sanitized


def _redacted_error_message(error):
    return _truncate_text(redact_text(str(error)), MAX_LOG_ERROR_CHARS)


def _redacted_payload_for_prompt(payload):
    if isinstance(payload, str):
        return _truncate_text(redact_text(payload), MAX_SECONDARY_INPUT_CHARS)
    if isinstance(payload, dict):
        redacted = redact_ai_context(payload)
    elif isinstance(payload, list):
        redacted = redact_list(payload)
    else:
        redacted = redact_text(str(payload))

    if isinstance(redacted, str):
        return _truncate_text(redacted, MAX_SECONDARY_INPUT_CHARS)
    return _truncate_text(json.dumps(redacted, indent=2, ensure_ascii=False, default=str), MAX_SECONDARY_INPUT_CHARS)


def _payload_too_large(payload) -> bool:
    if isinstance(payload, str):
        return len(payload) > MAX_SECONDARY_INPUT_CHARS
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(payload)
    return len(serialized) > MAX_SECONDARY_INPUT_CHARS


def _can_manage_ai_memory(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.has_perm("security.manage_security_configuration"))
    )


def _check_rate_limit(user, rate_setting: str = "10/m") -> tuple[bool, Optional[str]]:
    """Check if user has exceeded rate limit.

    Args:
        user: The user to check
        rate_setting: Rate limit setting in format "X/m" (requests per minute)

    Returns:
        Tuple of (allowed, error_message). If allowed is True, error_message is None.
    """
    if not user or not user.is_authenticated:
        return True, None

    try:
        parts = rate_setting.strip().lower().split("/")
        if len(parts) != 2:
            return True, None

        limit = int(parts[0])
        period = parts[1]

        if period != "m":
            return True, None

        cache_key = f"ai_memory_index_rate:{user.id}"
        current_time = int(time.time())
        window_start = current_time - 60

        requests = cache.get(cache_key, [])
        requests = [req_time for req_time in requests if req_time > window_start]

        if len(requests) >= limit:
            return False, "Rate limit exceeded"

        requests.append(current_time)
        cache.set(cache_key, requests, 60)

        return True, None
    except (ValueError, TypeError):
        return True, None


def _sanitize_memory_source_references(user, source_references):
    """Sanitize source references to limit exposure for non-manager users.

    For users with manage_security_configuration permission or staff:
    - Keep detailed references but still redacted/truncated

    For normal users:
    - Return only generic labels like "Internal source #1"
    - Do not expose: document_id, chunk_id, primary key, full document title,
      source path, original filename, original email subject
    """
    if not isinstance(source_references, list):
        return []

    if _can_manage_ai_memory(user):
        return source_references

    sanitized = []
    for i, ref in enumerate(source_references, start=1):
        if isinstance(ref, str):
            sanitized.append(ref)
        elif isinstance(ref, dict):
            source_type = ref.get("source_type", "document")
            sanitized.append({
                "label": f"Internal source #{i}",
                "source_type": source_type,
            })
        else:
            sanitized.append(f"Internal source #{i}")

    return sanitized


def _memory_context_response_payload(memory_context: dict, *, user=None, explain: bool = False) -> dict:
    retrieval = memory_context.get("retrieval", {})
    raw_flags = memory_context.get("insufficiency_flags", [])
    validated_flags = []
    if isinstance(raw_flags, list):
        for flag in raw_flags:
            if isinstance(flag, str) and flag in VALID_AI_MEMORY_INSUFFICIENCY_FLAGS:
                validated_flags.append(flag)

    raw_source_references = memory_context.get("source_references", [])
    source_references = _sanitize_memory_source_references(user, raw_source_references)

    payload = {
        "uses_internal_memory": bool(
            memory_context.get("approved_memory_facts") or memory_context.get("retrieved_chunks")
            or source_references
        ),
        "retrieval_used": bool(retrieval.get("retrieval_used")),
        "retrieval_mode": retrieval.get("retrieval_mode", "hybrid_keyword"),
        "retrieval_backend": retrieval.get("retrieval_backend", "keyword"),
        "pgvector_available": bool(retrieval.get("pgvector_available", False)),
        "embeddings_used": bool(retrieval.get("embeddings_used", False)),
        "sources_count": int(retrieval.get("sources_count", 0) or 0),
        "citations": memory_context.get("citations", []),
        "source_references": source_references,
        "insufficiency_flags": validated_flags,
    }
    if explain and _can_manage_ai_memory(user):
        payload["score_components"] = [
            {
                "chunk_id": chunk.get("chunk_id"),
                "document_id": chunk.get("document_id"),
                "score": chunk.get("score"),
                "keyword_score": chunk.get("keyword_score"),
                "vector_score": chunk.get("vector_score"),
                "vector_distance": chunk.get("vector_distance"),
                "retrieval_mode": chunk.get("retrieval_mode"),
                "reason": chunk.get("reason"),
                "components": chunk.get("score_components", {}),
            }
            for chunk in memory_context.get("retrieved_chunks", [])
        ]
    return payload


def _build_memory_task_messages(memory_context: dict, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": memory_context["prompt_context_text"]},
        {"role": "user", "content": user_prompt},
    ]


def _provider_base_url_label(base_url):
    default_url = "https://integrate.api.nvidia.com/v1"
    if not base_url:
        return "missing"
    return "default" if str(base_url).rstrip("/") == default_url else "custom"


def sanitize_chat_history(history):
    """Sanitize chat history from client input"""
    if not isinstance(history, list):
        return []

    sanitized = []
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")

        # Only accept user and assistant roles
        if role not in ("user", "assistant"):
            continue

        # Ensure content is a string and not empty
        if not isinstance(content, str) or not content.strip():
            continue

        # Truncate content
        content = content[:MAX_CONTENT_LENGTH]
        sanitized.append({"role": role, "content": content})

    return sanitized


class AIChatApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        message = request.data.get("message", "")
        history = request.data.get("history", [])
        context = _sanitize_context_metadata(request.data.get("context"))
        explain = bool(request.data.get("explain", False))

        # Validate message
        if not isinstance(message, str):
            return Response({"error": "Invalid AI request"}, status=400)

        message = message.strip()

        if not message:
            return Response({"error": "Invalid AI request"}, status=400)

        if len(message) > MAX_MESSAGE_LENGTH:
            return Response({"error": "Invalid AI request"}, status=400)

        start_time = time.time()
        request_chars = len(message)
        log_entry = None

        try:
            memory_context = build_ai_memory_context(
                question=message,
                context_type=context.get("object_type"),
                context_object_id=context.get("object_id"),
                user=request.user,
            )
            messages = build_ai_messages(
                user=request.user,
                user_message=message,
                history=history,
                runtime_context=context,
            )

            response = chat_completion(
                messages=messages,
                task="chat",
                temperature=0.7,
                max_tokens=2048,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            response_chars = len(response.content)

            # Log successful interaction
            log_entry = SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="chat",
                provider=response.provider,
                model=response.model,
                status="success",
                page=context.get("page", ""),
                object_type=context.get("object_type", ""),
                object_id=context.get("object_id", ""),
                request_chars=request_chars,
                response_chars=response_chars,
                latency_ms=latency_ms,
            )

            return Response({
                "message": response.content,
                "model": response.model,
                "provider": response.provider,
                **_memory_context_response_payload(memory_context, user=request.user, explain=explain),
            })
        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning("AI provider error during chat", extra={"error_class": e.__class__.__name__})

            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="chat",
                status="provider_error",
                page=context.get("page", ""),
                object_type=context.get("object_type", ""),
                object_id=context.get("object_id", ""),
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=_redacted_error_message(e.__class__.__name__),
            )

            error_code = "provider_unavailable"
            if isinstance(e, AIProviderUnavailableError):
                if "timeout" in str(e).lower():
                    error_code = "provider_timeout"
            elif isinstance(e, AIProviderResponseError):
                if "not available" in str(e).lower() or "not found" in str(e).lower():
                    error_code = "model_not_available"
                else:
                    error_code = "provider_response_error"

            return Response({
                "error": "AI service temporarily unavailable",
                "code": error_code,
                "retryable": True,
            }, status=503)
        except AIProviderConfigurationError:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning("AI provider not configured")

            # Log config error
            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="chat",
                status="config_error",
                page=context.get("page", ""),
                object_type=context.get("object_type", ""),
                object_id=context.get("object_id", ""),
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=_redacted_error_message("AI provider not configured"),
            )

            return Response({
                "error": "AI service not configured",
                "code": "provider_not_configured",
                "retryable": False,
            }, status=503)
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = _redacted_error_message(e)
            logger.error("Unexpected error in AI chat", extra={"error_class": e.__class__.__name__})

            # Log error
            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="chat",
                status="error",
                page=context.get("page", ""),
                object_type=context.get("object_type", ""),
                object_id=context.get("object_id", ""),
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=error_msg,
            )

            return Response({
                "error": "AI service temporarily unavailable",
                "code": "ai_internal_error",
                "retryable": True,
            }, status=503)


class AIAnalyzeReportApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        report_id = request.data.get("report_id")
        report_content = request.data.get("content", "")

        if not isinstance(report_content, str) or not report_content.strip() or _payload_too_large(report_content):
            return Response({"error": "Invalid AI request"}, status=400)

        try:
            redacted_report_content = _redacted_payload_for_prompt(report_content)
            system_prompt = """Sei un esperto di sicurezza informatica. Analizza il seguente report di sicurezza e fornisci:
1. Riassunto esecutivo (max 200 parole)
2. Vulnerabilità rilevate (CVE, severità, asset)
3. Raccomandazioni prioritarie
4. Rischi identificati
5. Azioni suggerite

Rispondi in formato JSON con le seguenti chiavi:
{
  "summary": "riassunto esecutivo",
  "vulnerabilities": [{"cve": "CVE-XXXX-XXXX", "severity": "high/medium/low", "asset": "hostname/IP", "description": "descrizione"}],
  "recommendations": ["raccomandazione 1", "raccomandazione 2"],
  "risks": ["rischio 1", "rischio 2"],
  "suggested_actions": ["azione 1", "azione 2"]
}"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analizza questo report:\n\n{redacted_report_content}"},
            ]

            response = chat_completion(
                messages=messages,
                model="meta/llama-3.1-70b-instruct",
                temperature=0.3,
                max_tokens=4096,
            )

            content = response.content

            # Estrai JSON dal contenuto
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            analysis = json.loads(content)

            return Response({
                "report_id": report_id,
                "analysis": analysis,
            })
        except AIProviderConfigurationError:
            logger.warning("AI provider not configured")
            return Response({"error": "AI service not configured"}, status=503)
        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            logger.warning("AI provider error during report analysis", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)
        except Exception as e:
            logger.error("Unexpected error in AI report analysis", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)


class AISuggestAlertRuleApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        context = request.data.get("context", "")

        if not isinstance(context, str) or not context.strip() or _payload_too_large(context):
            return Response({"error": "Invalid AI request"}, status=400)

        try:
            redacted_context = _redacted_payload_for_prompt(context)
            system_prompt = """Sei un esperto di sicurezza informatica. Basandoti sul contesto fornito, suggerisci una regola di alert appropriata.

Rispondi in formato JSON con le seguenti chiavi:
{
  "rule_name": "nome della regola",
  "condition": "condizione che deve attivare l'alert",
  "severity": "critical/high/medium/low",
  "description": "descrizione della regola",
  "recommended_actions": ["azione 1", "azione 2"],
  "rationale": "spiegazione del perché questa regola è appropriata"
}"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Contesto:\n\n{redacted_context}"},
            ]

            response = chat_completion(
                messages=messages,
                model="meta/llama-3.1-8b-instruct",
                temperature=0.5,
                max_tokens=1024,
            )

            content = response.content

            # Estrai JSON dal contenuto (potrebbe essere racchiuso in blocchi di codice markdown)
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            suggestion = json.loads(content)

            return Response({
                "suggestion": suggestion,
            })
        except AIProviderConfigurationError:
            logger.warning("AI provider not configured")
            return Response({"error": "AI service not configured"}, status=503)
        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            logger.warning("AI provider error during alert rule suggestion", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)
        except Exception as e:
            logger.error("Unexpected error in AI alert rule suggestion", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)


class AIAnalyzeEventsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        events = request.data.get("events", [])

        if not isinstance(events, (dict, list)) or not events or _payload_too_large(events):
            return Response({"error": "Invalid AI request"}, status=400)

        try:
            redacted_events_json = _redacted_payload_for_prompt(events)
            system_prompt = """Sei un esperto di sicurezza informatica. Analizza la seguente serie di eventi e fornisci:
1. Pattern rilevati
2. Eventi anomali
3. Correlazioni tra eventi
4. Minacce potenziali
5. Raccomandazioni

Rispondi in formato JSON con le seguenti chiavi:
{
  "patterns": ["pattern 1", "pattern 2"],
  "anomalies": [{"event_id": "ID", "description": "descrizione"}],
  "correlations": ["correlazione 1", "correlazione 2"],
  "potential_threats": ["minaccia 1", "minaccia 2"],
  "recommendations": ["raccomandazione 1", "raccomandazione 2"]
}"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Eventi:\n\n{redacted_events_json}"},
            ]

            response = chat_completion(
                messages=messages,
                model="meta/llama-3.1-70b-instruct",
                temperature=0.4,
                max_tokens=4096,
            )

            content = response.content

            # Estrai JSON dal contenuto
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            analysis = json.loads(content)

            return Response({
                "analysis": analysis,
            })
        except AIProviderConfigurationError:
            logger.warning("AI provider not configured")
            return Response({"error": "AI service not configured"}, status=503)
        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            logger.warning("AI provider error during events analysis", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)
        except Exception as e:
            logger.error("Unexpected error in AI events analysis", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)


class AIGenerateSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        data = request.data.get("data", {})

        if not isinstance(data, (dict, list)) or not data or _payload_too_large(data):
            return Response({"error": "Invalid AI request"}, status=400)

        try:
            redacted_data_json = _redacted_payload_for_prompt(data)
            system_prompt = """Sei un esperto di sicurezza informatica. Genera un riassunto conciso e informativo dei dati forniti.
Il riassunto deve essere in italiano, massimo 300 parole, e includere:
- Punti chiave
- Metriche importanti
- Raccomandazioni principali"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Dati:\n\n{redacted_data_json}"},
            ]

            response = chat_completion(
                messages=messages,
                model="meta/llama-3.1-8b-instruct",
                temperature=0.5,
                max_tokens=512,
            )

            summary = response.content

            return Response({
                "summary": summary,
            })
        except AIProviderConfigurationError:
            logger.warning("AI provider not configured")
            return Response({"error": "AI service not configured"}, status=503)
        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            logger.warning("AI provider error during summary generation", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)
        except Exception as e:
            logger.error("Unexpected error in AI summary generation", extra={"error_class": e.__class__.__name__})
            return Response({"error": "AI service temporarily unavailable"}, status=503)


class AIUsageSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        try:
            # Get all interaction logs
            logs = SecurityAiInteractionLog.objects.all()

            # Calculate metrics
            total_queries = logs.count()
            successful_queries = logs.filter(status="success").count()
            failed_queries = logs.filter(status__in=["error", "config_error", "provider_error"]).count()

            # Calculate average response time (only for successful queries)
            avg_response_time_result = logs.filter(status="success").aggregate(
                avg_latency=Avg("latency_ms")
            )
            avg_response_time = (
                round(avg_response_time_result["avg_latency"] / 1000, 2)
                if avg_response_time_result["avg_latency"]
                else 0
            )

            # Count analyses completed (successful chat interactions)
            analyses_completed = logs.filter(action="chat", status="success").count()

            # Get recent analyses (last 10 successful interactions)
            recent_analyses = []
            recent_logs = logs.filter(status="success").order_by("-created_at")[:10]
            for log in recent_logs:
                recent_analyses.append({
                    "id": log.id,
                    "title": f"{log.action.replace('_', ' ').title()} - {log.model or 'AI'}",
                    "description": f"{log.provider or 'AI'} interaction",
                    "created_at": log.created_at.isoformat(),
                    "status": "completed",
                })

            return Response({
                "total_queries": total_queries,
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "avg_response_time": avg_response_time,
                "analyses_completed": analyses_completed,
                "recent_analyses": recent_analyses,
            })
        except Exception as e:
            logger.exception("Unexpected error in AI usage summary")
            return Response({"error": "Failed to retrieve usage summary"}, status=500)


class AIProviderStatusApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        try:
            from django.conf import settings

            # Get provider settings without exposing secrets
            api_key = getattr(settings, "NVIDIA_NIM_API_KEY", None)
            if not api_key:
                api_key = getattr(settings, "NVIDIA_API_KEY", None)

            base_url = getattr(settings, "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
            base_url_label = _provider_base_url_label(base_url)
            default_model = getattr(settings, "AI_DEFAULT_MODEL", "meta/llama-3.1-70b-instruct")
            fast_model = getattr(settings, "AI_FAST_MODEL", "meta/llama-3.1-8b-instruct")
            speed_model = getattr(settings, "AI_SPEED_MODEL", "meta/llama-3.2-1b-instruct")
            route_mode = getattr(settings, "AI_MODEL_ROUTE_MODE", "speed")
            timeout_seconds = getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20)
            retries = getattr(settings, "AI_REQUEST_RETRIES", 0)
            retry_backoff_seconds = getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1)
            fast_fallback_enabled = getattr(settings, "AI_ENABLE_FAST_FALLBACK", True)
            copilot_uses_fast_model = getattr(settings, "AI_COPILOT_USE_FAST_MODEL", True)

            # Determine API key status without exposing the key
            api_key_present = bool(api_key)
            api_key_label = "configured"
            configured = True
            provider_status = "ok"

            if not api_key:
                api_key_label = "missing"
                configured = False
                provider_status = "not_configured"
            elif api_key in ("your_nvidia_api_key_here", "placeholder", "test", ""):
                api_key_label = "placeholder"
                configured = False
                provider_status = "not_configured"

            # Get metrics from SecurityAiInteractionLog
            logs = SecurityAiInteractionLog.objects.all()

            # Last success and error
            last_success = logs.filter(status="success").order_by("-created_at").first()
            last_error = logs.filter(status__in=["error", "config_error", "provider_error"]).order_by("-created_at").first()

            # Recent counts (last 24 hours)
            twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
            recent_logs = logs.filter(created_at__gte=twenty_four_hours_ago)
            recent_success_count = recent_logs.filter(status="success").count()
            recent_error_count = recent_logs.filter(status__in=["error", "config_error", "provider_error"]).count()

            # Average latency
            avg_latency_result = logs.filter(status="success").aggregate(avg_latency=Avg("latency_ms"))
            avg_latency_ms = int(avg_latency_result["avg_latency"] or 0)

            # Update status based on recent errors
            if configured and recent_error_count > 0:
                if recent_error_count > recent_success_count:
                    provider_status = "error"
                else:
                    provider_status = "warning"

            # Redact/truncate error message
            last_error_message = ""
            if last_error and last_error.error_message:
                last_error_message = _truncate_text(redact_text(last_error.error_message), MAX_STATUS_ERROR_CHARS)

            return Response({
                "provider": "nvidia_nim",
                "configured": configured,
                "model": default_model,
                "fast_model": fast_model,
                "speed_model": speed_model,
                "route_mode": route_mode,
                "base_url_label": base_url_label,
                "api_key_present": api_key_present,
                "api_key_label": api_key_label,
                "status": provider_status,
                "timeout_seconds": timeout_seconds,
                "retries": retries,
                "retry_backoff_seconds": retry_backoff_seconds,
                "fast_fallback_enabled": fast_fallback_enabled,
                "copilot_uses_fast_model": copilot_uses_fast_model,
                "last_success_at": last_success.created_at.isoformat() if last_success else None,
                "last_error_at": last_error.created_at.isoformat() if last_error else None,
                "last_error_message": last_error_message,
                "recent_success_count": recent_success_count,
                "recent_error_count": recent_error_count,
                "avg_latency_ms": avg_latency_ms,
            })
        except Exception as e:
            logger.exception("Unexpected error in AI provider status")
            return Response({"error": "Failed to retrieve provider status"}, status=500)


class AIOperationsSummaryApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        try:
            from django.conf import settings

            # Get provider status
            api_key = getattr(settings, "NVIDIA_NIM_API_KEY", None)
            if not api_key:
                api_key = getattr(settings, "NVIDIA_API_KEY", None)

            base_url = getattr(settings, "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
            base_url_label = _provider_base_url_label(base_url)
            default_model = getattr(settings, "AI_DEFAULT_MODEL", "meta/llama-3.1-70b-instruct")
            fast_model = getattr(settings, "AI_FAST_MODEL", "meta/llama-3.1-8b-instruct")
            speed_model = getattr(settings, "AI_SPEED_MODEL", "meta/llama-3.2-1b-instruct")
            route_mode = getattr(settings, "AI_MODEL_ROUTE_MODE", "speed")
            timeout_seconds = getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20)
            retries = getattr(settings, "AI_REQUEST_RETRIES", 0)
            retry_backoff_seconds = getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1)
            fast_fallback_enabled = getattr(settings, "AI_ENABLE_FAST_FALLBACK", True)
            copilot_uses_fast_model = getattr(settings, "AI_COPILOT_USE_FAST_MODEL", True)

            api_key_present = bool(api_key)
            api_key_label = "configured"
            configured = True
            provider_status = "ok"

            if not api_key:
                api_key_label = "missing"
                configured = False
                provider_status = "not_configured"
            elif api_key in ("your_nvidia_api_key_here", "placeholder", "test", ""):
                api_key_label = "placeholder"
                configured = False
                provider_status = "not_configured"

            # Get metrics from SecurityAiInteractionLog
            logs = SecurityAiInteractionLog.objects.all()

            # Usage summary
            total_queries = logs.count()
            successful_queries = logs.filter(status="success").count()
            failed_queries = logs.filter(status__in=["error", "config_error", "provider_error"]).count()

            avg_latency_result = logs.filter(status="success").aggregate(avg_latency=Avg("latency_ms"))
            avg_response_time = round((avg_latency_result["avg_latency"] or 0) / 1000, 2)
            analyses_completed = logs.filter(action="chat", status="success").count()

            # Last success and error
            last_success = logs.filter(status="success").order_by("-created_at").first()
            last_error = logs.filter(status__in=["error", "config_error", "provider_error"]).order_by("-created_at").first()

            # Recent counts
            twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
            recent_logs = logs.filter(created_at__gte=twenty_four_hours_ago)
            recent_success_count = recent_logs.filter(status="success").count()
            recent_error_count = recent_logs.filter(status__in=["error", "config_error", "provider_error"]).count()

            avg_latency_ms = int(avg_latency_result["avg_latency"] or 0)

            if configured and recent_error_count > 0:
                if recent_error_count > recent_success_count:
                    provider_status = "error"
                else:
                    provider_status = "warning"

            last_error_message = ""
            if last_error and last_error.error_message:
                last_error_message = _truncate_text(redact_text(last_error.error_message), MAX_STATUS_ERROR_CHARS)

            provider_status_data = {
                "provider": "nvidia_nim",
                "configured": configured,
                "model": default_model,
                "fast_model": fast_model,
                "speed_model": speed_model,
                "route_mode": route_mode,
                "base_url_label": base_url_label,
                "api_key_present": api_key_present,
                "api_key_label": api_key_label,
                "status": provider_status,
                "timeout_seconds": timeout_seconds,
                "retries": retries,
                "retry_backoff_seconds": retry_backoff_seconds,
                "fast_fallback_enabled": fast_fallback_enabled,
                "copilot_uses_fast_model": copilot_uses_fast_model,
                "last_success_at": last_success.created_at.isoformat() if last_success else None,
                "last_error_at": last_error.created_at.isoformat() if last_error else None,
                "last_error_message": last_error_message,
                "recent_success_count": recent_success_count,
                "recent_error_count": recent_error_count,
                "avg_latency_ms": avg_latency_ms,
            }

            usage_summary = {
                "total_queries": total_queries,
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "avg_response_time": avg_response_time,
                "analyses_completed": analyses_completed,
            }

            # Recent interactions (without full prompts/responses)
            recent_interactions = []
            for log in logs.order_by("-created_at")[:20]:
                recent_interactions.append({
                    "id": log.id,
                    "action": log.action,
                    "provider": log.provider or "nvidia_nim",
                    "model": log.model or default_model,
                    "status": log.status,
                    "page": log.page,
                    "object_type": log.object_type,
                    "object_id": log.object_id,
                    "request_chars": log.request_chars,
                    "response_chars": log.response_chars,
                    "latency_ms": log.latency_ms,
                    "created_at": log.created_at.isoformat(),
                })

            # Supported contexts
            supported_contexts = [
                {"type": "dashboard", "label": "Dashboard", "enabled": True},
                {"type": "alert", "label": "Alert", "enabled": True},
                {"type": "report", "label": "Report", "enabled": True},
                {"type": "ticket", "label": "Ticket", "enabled": True},
                {"type": "evidence", "label": "Evidence Container", "enabled": True},
            ]

            # Quick actions
            quick_actions = [
                {"key": "explain_alert", "label": "Spiega alert", "context_type": "alert"},
                {"key": "remediation_plan", "label": "Piano remediation", "context_type": "ticket"},
                {"key": "summarize_report", "label": "Riassumi report", "context_type": "report"},
                {"key": "summarize_evidence", "label": "Riassumi evidenze", "context_type": "evidence"},
                {"key": "daily_summary", "label": "Sintesi giornaliera", "context_type": "dashboard"},
            ]

            # Safety settings
            safety = {
                "redaction_enabled": True,
                "context_builder_enabled": True,
                "audit_log_enabled": True,
                "stores_full_prompts": False,
                "stores_full_responses": False,
            }

            return Response({
                "provider_status": provider_status_data,
                "usage_summary": usage_summary,
                "recent_interactions": recent_interactions,
                "supported_contexts": supported_contexts,
                "quick_actions": quick_actions,
                "safety": safety,
            })
        except Exception as e:
            logger.exception("Unexpected error in AI operations summary")
            return Response({"error": "Failed to retrieve operations summary"}, status=500)


class AIMemoryIndexApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        if not _can_manage_ai_memory(request.user):
            return Response({"error": "Forbidden"}, status=403)

        from django.conf import settings
        rate_setting = getattr(settings, "SECURITY_AI_MEMORY_INDEX_RATE", "10/m")
        allowed, error_message = _check_rate_limit(request.user, rate_setting)
        if not allowed:
            return Response({"error": error_message or "Rate limit exceeded"}, status=429)

        title = request.data.get("title", "")
        raw_text = request.data.get("raw_text", "")
        source_type = request.data.get("source_type", "manual")
        source_object_type = request.data.get("source_object_type", "")
        source_object_id = request.data.get("source_object_id", "")
        metadata = request.data.get("metadata", {})

        if not isinstance(title, str) or not title.strip():
            return Response({"error": "Invalid title"}, status=400)
        if not isinstance(raw_text, str) or not raw_text.strip():
            return Response({"error": "Invalid raw_text"}, status=400)
        if len(raw_text) > MAX_MEMORY_DOCUMENT_CHARS:
            return Response({"error": "Document too large"}, status=400)
        if not isinstance(source_type, str) or not source_type.strip():
            return Response({"error": "Invalid source_type"}, status=400)
        if metadata is not None and not isinstance(metadata, dict):
            return Response({"error": "Invalid metadata"}, status=400)

        try:
            result = index_document(
                source_type=source_type,
                source_object_type=source_object_type if isinstance(source_object_type, str) else "",
                source_object_id=source_object_id,
                title=title,
                raw_text=redact_text(raw_text),
                metadata=metadata,
            )
            return Response(
                {
                    "document_id": result.document.id,
                    "title": result.document.title,
                    "created": result.created,
                    "updated": result.updated,
                    "chunks_count": result.chunks_count,
                    "content_hash": result.document.content_hash,
                },
                status=201 if result.created else 200,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)


class AIMemoryFactsApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        queryset = AIMemoryFact.objects.all()
        if not _can_manage_ai_memory(request.user):
            queryset = queryset.filter(is_approved=True)

        scope = request.query_params.get("scope")
        category = request.query_params.get("category")
        if scope:
            queryset = queryset.filter(scope=scope[:80])
        if category:
            queryset = queryset.filter(category=category[:80])

        facts = [serialize_memory_fact(fact) for fact in queryset.order_by("scope", "category", "key")[:100]]
        return Response({"facts": facts})

    def post(self, request):
        value = request.data.get("value", "")
        key = request.data.get("key", "")
        scope = request.data.get("scope", "global")
        category = request.data.get("category", "")
        confidence = request.data.get("confidence", 1.0)
        is_approved = bool(request.data.get("is_approved", False)) if _can_manage_ai_memory(request.user) else False

        if not isinstance(key, str) or not key.strip():
            return Response({"error": "Invalid key"}, status=400)
        if not isinstance(value, str) or not value.strip():
            return Response({"error": "Invalid value"}, status=400)
        if len(value) > MAX_CONTENT_LENGTH:
            return Response({"error": "Value too large"}, status=400)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return Response({"error": "Invalid confidence"}, status=400)

        fact = AIMemoryFact.objects.create(
            scope=str(scope or "global")[:80],
            key=key.strip()[:160],
            value=redact_text(value.strip()),
            category=str(category or "")[:80],
            confidence=max(0.0, min(confidence, 1.0)),
            is_approved=is_approved,
            source=redact_text(str(request.data.get("source", ""))).strip()[:160],
            source_object_type=str(request.data.get("source_object_type", ""))[:80],
            source_object_id=str(request.data.get("source_object_id", ""))[:80],
            metadata=request.data.get("metadata", {}) if isinstance(request.data.get("metadata", {}), dict) else {},
        )
        return Response({"fact": serialize_memory_fact(fact)}, status=201)


class AIExplainAlertApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        alert_id = request.data.get("alert_id")
        if not str(alert_id or "").isdigit():
            return Response({"error": "Invalid alert_id"}, status=400)
        return _run_contextual_ai_task(
            request=request,
            task="alert_explanation",
            question=f"Spiega l'alert #{alert_id} usando solo evidenze interne disponibili.",
            context_type="alert",
            context_object_id=str(alert_id),
            response_key="explanation",
        )


class AISummarizeEvidenceApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        evidence_id = str(request.data.get("evidence_id", "")).strip()
        if not re.match(r"^[0-9a-fA-F-]{1,80}$", evidence_id):
            return Response({"error": "Invalid evidence_id"}, status=400)
        return _run_contextual_ai_task(
            request=request,
            task="report_summary",
            question=f"Riassumi l'Evidence Container #{evidence_id} usando solo fonti disponibili.",
            context_type="evidence",
            context_object_id=evidence_id,
            response_key="summary",
        )


class AIRemediationPlanApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        context_type = str(request.data.get("context_type", "") or "").strip() or "ticket"
        object_id = str(request.data.get("context_object_id", request.data.get("ticket_id", ""))).strip()
        if context_type not in {"alert", "ticket", "report", "evidence"}:
            return Response({"error": "Invalid context_type"}, status=400)
        if context_type in {"alert", "ticket", "report"} and not object_id.isdigit():
            return Response({"error": "Invalid context_object_id"}, status=400)
        if context_type == "evidence" and not re.match(r"^[0-9a-fA-F-]{1,80}$", object_id):
            return Response({"error": "Invalid context_object_id"}, status=400)

        return _run_contextual_ai_task(
            request=request,
            task="alert_explanation",
            question=(
                "Genera un piano remediation operativo usando solo evidenze interne. "
                "Per CVE Critical, CVSS >= 9.0 ed exposed_devices > 0 rispetta deduplica ticket."
            ),
            context_type=context_type,
            context_object_id=object_id,
            response_key="plan",
        )


def _run_contextual_ai_task(*, request, task: str, question: str, context_type: str, context_object_id: str, response_key: str):
    start_time = time.time()
    explain = bool(request.data.get("explain", False))
    memory_context = build_ai_memory_context(
        question=question,
        context_type=context_type,
        context_object_id=context_object_id,
        user=request.user,
    )
    memory_payload = _memory_context_response_payload(memory_context, user=request.user, explain=explain)
    if "requested_object_context_unavailable" in memory_payload["insufficiency_flags"] or (
        "insufficient_internal_evidence" in memory_payload["insufficiency_flags"]
    ):
        return Response(
            {
                response_key: INSUFFICIENT_EVIDENCE_MESSAGE,
                **memory_payload,
            }
        )

    try:
        response = chat_completion(
            messages=_build_memory_task_messages(memory_context, question),
            task=task,
            temperature=0.3,
            max_tokens=2048,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        SecurityAiInteractionLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=task,
            provider=response.provider,
            model=response.model,
            status="success",
            page=context_type,
            object_type=context_type,
            object_id=str(context_object_id),
            request_chars=len(question),
            response_chars=len(response.content),
            latency_ms=latency_ms,
        )
        return Response(
            {
                response_key: response.content,
                "model": response.model,
                "provider": response.provider,
                **memory_payload,
            }
        )
    except AIProviderConfigurationError:
        return Response({"error": "AI service not configured", "code": "provider_not_configured"}, status=503)
    except (AIProviderUnavailableError, AIProviderResponseError):
        return Response({"error": "AI service temporarily unavailable", "code": "provider_unavailable"}, status=503)


class AIConfigurationCopilotApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def post(self, request):
        task = request.data.get("task", "")
        user_prompt = request.data.get("user_prompt", "")
        draft = request.data.get("draft")
        sample = request.data.get("sample")
        scope = request.data.get("scope")

        # Validate task
        if not validate_task(task):
            return Response({
                "error": "Invalid task",
                "code": "invalid_task",
                "allowed_tasks": list(ALLOWED_TASKS),
            }, status=400)

        # Validate user prompt
        if not validate_user_prompt(user_prompt):
            return Response({
                "error": "Invalid user_prompt",
                "code": "invalid_request",
            }, status=400)

        start_time = time.time()
        request_chars = len(user_prompt)
        log_entry = None

        try:
            # Build configuration context
            context = build_configuration_context()

            # Build AI prompt
            messages = build_configuration_copilot_prompt(
                task=task,
                user_prompt=user_prompt,
                context=context,
                draft=draft,
                sample=sample,
                scope=scope,
            )

            # Call AI
            response = chat_completion(
                messages=messages,
                task="configuration_copilot",
                temperature=0.5,
                max_tokens=4096,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            response_chars = len(response.content)

            # Parse AI response
            try:
                result = parse_ai_response(response.content)
            except ValueError as e:
                logger.warning(f"Failed to parse AI response: {e}")
                return Response({
                    "error": "AI response parsing failed",
                    "code": "provider_response_error",
                    "retryable": True,
                }, status=503)

            # Ensure result has required fields
            result.setdefault("task", task)
            result.setdefault("safe_to_apply", False)
            result.setdefault("requires_review", True)

            # Log successful interaction
            log_entry = SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="configuration_copilot",
                provider=response.provider,
                model=response.model,
                status="success",
                page="configuration",
                object_type="config",
                object_id=task,
                request_chars=request_chars,
                response_chars=response_chars,
                latency_ms=latency_ms,
            )

            return Response(result)

        except (AIProviderUnavailableError, AIProviderResponseError) as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning("AI provider error during configuration copilot", extra={"error_class": e.__class__.__name__})

            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="configuration_copilot",
                status="provider_error",
                page="configuration",
                object_type="config",
                object_id=task,
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=_redacted_error_message(e.__class__.__name__),
            )

            error_code = "provider_unavailable"
            if isinstance(e, AIProviderUnavailableError):
                if "timeout" in str(e).lower():
                    error_code = "provider_timeout"
            elif isinstance(e, AIProviderResponseError):
                if "not available" in str(e).lower() or "not found" in str(e).lower():
                    error_code = "model_not_available"
                else:
                    error_code = "provider_response_error"

            return Response({
                "error": "AI service temporarily unavailable",
                "code": error_code,
                "retryable": True,
            }, status=503)

        except AIProviderConfigurationError:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning("AI provider not configured")

            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="configuration_copilot",
                status="config_error",
                page="configuration",
                object_type="config",
                object_id=task,
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=_redacted_error_message("AI provider not configured"),
            )

            return Response({
                "error": "AI service not configured",
                "code": "provider_not_configured",
                "retryable": False,
            }, status=503)

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = _redacted_error_message(e)
            logger.error("Unexpected error in AI configuration copilot", extra={"error_class": e.__class__.__name__})

            SecurityAiInteractionLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="configuration_copilot",
                status="error",
                page="configuration",
                object_type="config",
                object_id=task,
                request_chars=request_chars,
                latency_ms=latency_ms,
                error_message=error_msg,
            )

            return Response({
                "error": "AI service temporarily unavailable",
                "code": "ai_internal_error",
                "retryable": True,
            }, status=503)


class AIConfigurationContextPreviewApiView(APIView):
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        try:
            context = build_configuration_context()
            quality = context_quality_score(context)

            return Response({
                "context_available": context.get("context_available", False),
                "sources_count": context.get("recent_activity", {}).get("sources_count", 0),
                "parsers_count": context.get("recent_activity", {}).get("parsers_count", 0),
                "rules_count": context.get("recent_activity", {}).get("rules_count", 0),
                "suppressions_count": context.get("recent_activity", {}).get("suppressions_count", 0),
                "notifications_count": context.get("recent_activity", {}).get("notifications_count", 0),
                "warnings": context.get("warnings", []),
                "quality": quality,
            })
        except Exception as e:
            logger.exception("Unexpected error in AI configuration context preview")
            return Response({"error": "Failed to retrieve context preview"}, status=500)


class AIContextPreviewApiView(APIView):
    """Preview AI context for any object type"""
    permission_classes = [CanViewSecurityCenter]

    def get(self, request):
        try:
            from .ai.services.context_builder import get_report_context, get_alert_context, get_ticket_context, get_evidence_context, get_dashboard_context

            object_type = request.query_params.get("object_type", "")
            object_id = request.query_params.get("object_id", "")

            if not object_type or not object_id:
                return Response(
                    {"error": "object_type and object_id are required"},
                    status=http_status.HTTP_400_BAD_REQUEST
                )

            # Get context based on object type
            if object_type == "report":
                try:
                    report_id = int(object_id)
                    context = get_report_context(report_id)
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid report ID"},
                        status=http_status.HTTP_400_BAD_REQUEST
                    )
            elif object_type == "alert":
                try:
                    alert_id = int(object_id)
                    context = get_alert_context(alert_id)
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid alert ID"},
                        status=http_status.HTTP_400_BAD_REQUEST
                    )
            elif object_type == "ticket":
                try:
                    ticket_id = int(object_id)
                    context = get_ticket_context(ticket_id)
                except (ValueError, TypeError):
                    return Response(
                        {"error": "Invalid ticket ID"},
                        status=http_status.HTTP_400_BAD_REQUEST
                    )
            elif object_type == "evidence":
                context = get_evidence_context(object_id)
            elif object_type == "dashboard":
                context = get_dashboard_context()
            else:
                return Response(
                    {"error": f"Unsupported object_type: {object_type}"},
                    status=http_status.HTTP_400_BAD_REQUEST
                )

            # Check for errors
            if "error" in context:
                return Response({
                    "context_available": False,
                    "object_type": object_type,
                    "object_id": object_id,
                    "error": context["error"],
                })

            # Build response based on object type
            if object_type == "report":
                # Rich report context preview
                sections = []

                # Parsed payload
                if context.get("context_quality", {}).get("has_parsed_payload"):
                    sections.append({
                        "name": "parsed_payload",
                        "available": True,
                        "chars": value_char_len(context.get("main_object", {}).get("parsed_payload", {})),
                    })
                else:
                    sections.append({
                        "name": "parsed_payload",
                        "available": False,
                        "chars": 0,
                    })

                # Metrics
                metrics = context.get("main_object", {}).get("metrics", [])
                sections.append({
                    "name": "metrics",
                    "available": len(metrics) > 0,
                    "count": len(metrics),
                })

                # Events
                events = context.get("related", {}).get("events", [])
                sections.append({
                    "name": "events",
                    "available": len(events) > 0,
                    "count": len(events),
                })

                # Event payload
                has_event_payload = context.get("context_quality", {}).get("has_event_payload")
                sections.append({
                    "name": "event_payload",
                    "available": has_event_payload,
                    "count": 1 if has_event_payload else 0,
                })

                # Mailbox body
                mailbox = context.get("raw_extracts", {}).get("mailbox_message", {})
                sections.append({
                    "name": "mailbox_body",
                    "available": mailbox.get("body_available", False),
                    "chars": value_char_len(mailbox.get("body_preview", "")),
                })

                # Pipeline result
                sections.append({
                    "name": "pipeline_result",
                    "available": mailbox.get("pipeline_result_available", False),
                    "chars": value_char_len(mailbox.get("pipeline_result", {})),
                })

                # Source file content
                source_file = context.get("raw_extracts", {}).get("source_file", {})
                sections.append({
                    "name": "source_file_content",
                    "available": source_file.get("content_available", False),
                    "chars": value_char_len(source_file.get("content_preview", "")),
                })

                # Vulnerabilities
                vulnerabilities = context.get("related", {}).get("vulnerabilities", [])
                sections.append({
                    "name": "vulnerabilities",
                    "available": len(vulnerabilities) > 0,
                    "count": len(vulnerabilities),
                })

                # Evidence items
                evidence_items = context.get("related", {}).get("evidence_items", [])
                sections.append({
                    "name": "evidence_items",
                    "available": len(evidence_items) > 0,
                    "count": len(evidence_items),
                })

                # Linked alerts
                linked_alerts = context.get("related", {}).get("linked_alerts", [])
                sections.append({
                    "name": "linked_alerts",
                    "available": len(linked_alerts) > 0,
                    "count": len(linked_alerts),
                })

                return Response({
                    "context_available": True,
                    "object_type": object_type,
                    "object_id": object_id,
                    "title": context.get("summary", {}).get("title", ""),
                    "context_quality": context.get("context_quality", {}),
                    "sections": sections,
                    "warnings": context.get("warnings", []),
                })
            else:
                # Simple context preview for other object types
                return Response({
                    "context_available": True,
                    "object_type": object_type,
                    "object_id": object_id,
                    "title": context.get("title", ""),
                    "context": context,
                })

        except Exception as e:
            logger.exception("Unexpected error in AI context preview")
            return Response({"error": "Failed to retrieve context preview"}, status=500)


def value_char_len(value):
    """Calculate character length of a value"""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (dict, list)):
        return len(json.dumps(value, default=str, ensure_ascii=False))
    return len(str(value))
