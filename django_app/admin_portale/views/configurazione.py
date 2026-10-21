"""Viste del Pannello di amministrazione — Configurazione: home, AI, notifiche, checklist, opzioni, voci anagrafica, audit, 2FA, health.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from ai_assistant.models import AiChatFeedback, AiKnowledgeEntry, AiToolPrivacyReview
from ai_assistant.services import clear_knowledge_cache
from ai_assistant.tools import build_runtime_context, get_runtime_tool_catalog
from core.audit import log_action
from core.exporting import export_rows_response
from core.caporeparto_utils import (
    normalize_caporeparto_option,
)
from core.legacy_models import UtenteLegacy
from core.legacy_utils import get_legacy_user
from core.models import (
    AnagraficaRisposta,
    AnagraficaVoce,
    ChecklistEsecuzione,
    ChecklistRisposta,
    ChecklistVoce,
    OptioneConfig,
)

from ..decorators import legacy_admin_required
from core import naming

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _normalize_category(value: str | None, default: str = "Generale") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    return raw[:100]


def _clean_ai_knowledge_text(value: object, *, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _handle_ai_knowledge_post(request: HttpRequest, *, redirect_to: str):
    action = (request.POST.get("action") or "").strip()
    entry_id = request.POST.get("entry_id")
    entry = AiKnowledgeEntry.objects.filter(id=entry_id).first() if entry_id else None

    if action == "save_knowledge":
        question = _clean_ai_knowledge_text(request.POST.get("question"), limit=500)
        answer = _clean_ai_knowledge_text(request.POST.get("answer"), limit=6000)
        source_label = _clean_ai_knowledge_text(request.POST.get("source_label") or "FAQ Portale", limit=120)
        is_active = _helpers._bool_from_any(request.POST.get("is_active"))
        if not question or not answer:
            messages.error(request, "Domanda e risposta sono obbligatorie.")
            return None, entry

        if entry is None:
            entry = AiKnowledgeEntry(created_by=request.user)
            audit_action = "ai_knowledge_create"
        else:
            audit_action = "ai_knowledge_update"
        entry.question = question
        entry.answer = answer
        entry.source_label = source_label or "FAQ Portale"
        entry.is_active = is_active
        entry.updated_by = request.user
        entry.save()
        clear_knowledge_cache()
        log_action(
            request,
            audit_action,
            "ai_assistant",
            {
                "entry_id": entry.id,
                "question_chars": len(question),
                "answer_chars": len(answer),
                "source_label": entry.source_label,
                "is_active": entry.is_active,
            },
        )
        messages.success(request, "FAQ AI salvata.")
        return redirect(redirect_to), None

    if action in {"toggle_knowledge", "delete_knowledge"} and entry:
        if action == "toggle_knowledge":
            entry.is_active = not entry.is_active
            entry.updated_by = request.user
            entry.save(update_fields=["is_active", "updated_by", "updated_at"])
            clear_knowledge_cache()
            log_action(
                request,
                "ai_knowledge_toggle",
                "ai_assistant",
                {"entry_id": entry.id, "is_active": entry.is_active},
            )
            messages.success(request, "Stato FAQ AI aggiornato.")
        else:
            deleted_id = entry.id
            entry.delete()
            clear_knowledge_cache()
            log_action(request, "ai_knowledge_delete", "ai_assistant", {"entry_id": deleted_id})
            messages.success(request, "FAQ AI eliminata.")
        return redirect(redirect_to), None

    if action:
        messages.error(request, "Azione FAQ AI non valida.")
    return None, entry


def _safe_int(value, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _ai_runtime_catalog_index() -> dict[str, object]:
    return {spec.key: spec for spec in get_runtime_tool_catalog()}


def _ai_runtime_tool_names(detail: dict) -> list[str]:
    tools = detail.get("runtime_tools")
    if isinstance(tools, list):
        return [str(item) for item in tools if str(item or "").strip()]
    details = detail.get("runtime_tools_detail")
    if isinstance(details, list):
        return [
            str(item.get("tool") or "")
            for item in details
            if isinstance(item, dict) and str(item.get("tool") or "").strip()
        ]
    return []


def _ai_runtime_allowed_values(detail: dict, selected_tool: str = "") -> list[object]:
    tools = _ai_runtime_tool_names(detail)
    allowed = detail.get("runtime_tools_allowed")
    values = allowed if isinstance(allowed, list) else []
    if not selected_tool:
        return values
    return [
        values[_helpers.index]
        for _helpers.index, tool in enumerate(tools)
        if tool == selected_tool and _helpers.index < len(values)
    ]


def _ai_runtime_outcome(action: str, detail: dict, selected_tool: str = "") -> str:
    if action == "ai_chat_error":
        return "error"
    allowed_values = _ai_runtime_allowed_values(detail, selected_tool)
    if any(value is False for value in allowed_values):
        return "denied"
    if allowed_values:
        return "allowed"
    return "metadata"


def _ai_runtime_sanitized_tools(audit: dict | None) -> list[dict[str, object]]:
    audit = audit if isinstance(audit, dict) else {}
    raw_tools = audit.get("tools") if isinstance(audit.get("tools"), list) else None
    if raw_tools is None and audit.get("tool"):
        raw_tools = [audit]
    result: list[dict[str, object]] = []
    for item in raw_tools or []:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        if not tool:
            continue
        result.append(
            {
                "tool": tool,
                "allowed": item.get("allowed"),
                "reason": str(item.get("reason") or ""),
                "scope": item.get("scope"),
                "row_count": item.get("row_count"),
                "filters": item.get("filters"),
            }
        )
    return result


def _ai_runtime_metrics(days: int = 30) -> dict[str, dict[str, object]]:
    from datetime import timedelta
    from core.models import AuditLog

    since = timezone.now() - timedelta(days=max(1, days))
    metrics: dict[str, dict[str, object]] = {}
    qs = (
        AuditLog.objects.filter(
            modulo="ai_assistant",
            azione__in=["ai_chat", "ai_chat_error", "ai_runtime_tool_test"],
            created_at__gte=since,
        )
        .order_by("-created_at")
        .only("azione", "dettaglio", "created_at")
    )
    for event in qs[:1000]:
        detail = event.dettaglio if isinstance(event.dettaglio, dict) else {}
        tools = _ai_runtime_tool_names(detail)
        elapsed_ms = _safe_int(detail.get("elapsed_ms"), 0, minimum=0)
        context_chars = _safe_int(detail.get("runtime_context_chars"), 0, minimum=0)
        for tool in tools:
            bucket = metrics.setdefault(
                tool,
                {
                    "calls": 0,
                    "errors": 0,
                    "denied": 0,
                    "elapsed_total": 0,
                    "elapsed_count": 0,
                    "context_total": 0,
                    "context_count": 0,
                },
            )
            bucket["calls"] = int(bucket["calls"]) + 1
            if event.azione == "ai_chat_error":
                bucket["errors"] = int(bucket["errors"]) + 1
            if _ai_runtime_outcome(event.azione, detail, selected_tool=tool) == "denied":
                bucket["denied"] = int(bucket["denied"]) + 1
            if elapsed_ms:
                bucket["elapsed_total"] = int(bucket["elapsed_total"]) + elapsed_ms
                bucket["elapsed_count"] = int(bucket["elapsed_count"]) + 1
            if context_chars:
                bucket["context_total"] = int(bucket["context_total"]) + context_chars
                bucket["context_count"] = int(bucket["context_count"]) + 1

    for bucket in metrics.values():
        elapsed_count = int(bucket.pop("elapsed_count"))
        elapsed_total = int(bucket.pop("elapsed_total"))
        context_count = int(bucket.pop("context_count"))
        context_total = int(bucket.pop("context_total"))
        bucket["avg_elapsed_ms"] = round(elapsed_total / elapsed_count) if elapsed_count else 0
        bucket["avg_context_chars"] = round(context_total / context_count) if context_count else 0
    return metrics


def _ai_runtime_catalog_with_metrics(days: int = 30) -> list[dict[str, object]]:
    metrics = _ai_runtime_metrics(days=days)
    rows: list[dict[str, object]] = []
    for spec in get_runtime_tool_catalog():
        metric = metrics.get(spec.audit_tool, {})
        rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "domain": spec.domain,
                "audit_tool": spec.audit_tool,
                "source_prefix": spec.source_prefix,
                "status": spec.status,
                "status_label": "abilitato" if spec.status == "enabled" else "disabilitato",
                "enabled": spec.status == "enabled",
                "sample_prompt": spec.sample_prompt,
                "privacy_note": spec.privacy_note,
                "calls": metric.get("calls", 0),
                "errors": metric.get("errors", 0),
                "denied": metric.get("denied", 0),
                "avg_elapsed_ms": metric.get("avg_elapsed_ms", 0),
                "avg_context_chars": metric.get("avg_context_chars", 0),
            }
        )
    return rows


def _ai_runtime_audit_rows(request: HttpRequest, *, catalog: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    from datetime import timedelta
    from core.models import AuditLog

    valid_tools = sorted({str(item["audit_tool"]) for item in catalog if item.get("audit_tool")})
    selected_tool = (request.GET.get("runtime_tool") or "").strip()
    if selected_tool not in valid_tools:
        selected_tool = ""
    outcome = (request.GET.get("runtime_outcome") or "").strip()
    if outcome not in {"allowed", "denied", "error", "metadata"}:
        outcome = ""
    days = _safe_int(request.GET.get("runtime_days"), 30, minimum=1, maximum=365)
    since = timezone.now() - timedelta(days=days)

    qs = (
        AuditLog.objects.filter(
            modulo="ai_assistant",
            azione__in=["ai_chat", "ai_chat_error", "ai_runtime_tool_test"],
            created_at__gte=since,
        )
        .order_by("-created_at")
        .only("azione", "utente_display", "created_at", "dettaglio")
    )
    rows: list[dict[str, object]] = []
    for event in qs[:300]:
        detail = event.dettaglio if isinstance(event.dettaglio, dict) else {}
        tools = _ai_runtime_tool_names(detail)
        if selected_tool and selected_tool not in tools:
            continue
        row_outcome = _ai_runtime_outcome(event.azione, detail, selected_tool=selected_tool)
        if outcome and row_outcome != outcome:
            continue
        rows.append(
            {
                "created_at": event.created_at,
                "utente_display": event.utente_display or "-",
                "azione": event.azione,
                "tools": tools,
                "outcome": row_outcome,
                "elapsed_ms": _safe_int(detail.get("elapsed_ms"), 0, minimum=0),
                "runtime_context_chars": _safe_int(detail.get("runtime_context_chars"), 0, minimum=0),
                "runtime_sources_count": _safe_int(detail.get("runtime_sources_count"), 0, minimum=0),
                "prompt_chars": _safe_int(detail.get("prompt_chars"), 0, minimum=0),
            }
        )
        if len(rows) >= 50:
            break
    return rows, {
        "tool": selected_tool,
        "outcome": outcome,
        "days": days,
        "tool_options": valid_tools,
    }


def _ai_runtime_user_label(user) -> str:
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = str(user.get_full_name() or "").strip()
    return full_name or str(getattr(user, "username", "") or getattr(user, "email", "") or user.pk)


def _ai_runtime_tool_test(request: HttpRequest) -> dict[str, object]:
    catalog_index = _ai_runtime_catalog_index()
    tool_key = (request.POST.get("runtime_tool_key") or "").strip()
    spec = catalog_index.get(tool_key) or next(iter(catalog_index.values()))
    prompt = _clean_ai_knowledge_text(request.POST.get("runtime_test_prompt"), limit=500)
    if not prompt:
        prompt = spec.sample_prompt

    User = get_user_model()
    simulated_user = request.user
    simulated_user_id = request.POST.get("runtime_simulated_user") or ""
    if simulated_user_id:
        target = User.objects.filter(pk=simulated_user_id, is_active=True).first()
        if target is None:
            messages.error(request, "Utente simulato non trovato o non attivo.")
            return {"ok": False, "error": "Utente simulato non trovato o non attivo."}
        simulated_user = target

    simulated_request = SimpleNamespace(
        user=simulated_user,
        legacy_user=None,
        path=request.path,
        META=getattr(request, "META", {}),
    )
    started = time.monotonic()
    runtime_context = build_runtime_context(simulated_request, prompt)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    sanitized_tools = _ai_runtime_sanitized_tools(runtime_context.audit)
    result = {
        "ok": True,
        "tool_key": spec.key,
        "tool_label": spec.label,
        "simulated_user_id": simulated_user.pk,
        "simulated_user_label": _ai_runtime_user_label(simulated_user),
        "prompt_chars": len(prompt),
        "elapsed_ms": elapsed_ms,
        "runtime_context_chars": len(runtime_context.text),
        "runtime_context_lines": len(runtime_context.text.splitlines()),
        "source_count": len(runtime_context.sources),
        "sources": list(runtime_context.sources)[:8],
        "tools": sanitized_tools,
    }
    _helpers._audit_safe(
        request,
        "ai_runtime_tool_test",
        "ai_assistant",
        {
            "selected_tool": spec.audit_tool,
            "selected_key": spec.key,
            "simulated_user_id": simulated_user.pk,
            "prompt_chars": len(prompt),
            "elapsed_ms": elapsed_ms,
            "runtime_context_chars": len(runtime_context.text),
            "runtime_context_lines": len(runtime_context.text.splitlines()),
            "runtime_sources_count": len(runtime_context.sources),
            "runtime_tools": [item["tool"] for item in sanitized_tools],
            "runtime_tools_allowed": [item.get("allowed") for item in sanitized_tools if "allowed" in item],
            "runtime_tools_detail": sanitized_tools,
        },
    )
    messages.success(request, "Test tool live completato in modalita metadata-only.")
    return result


def _moduli_senza_dati_rows(counter: dict[str, int]) -> list[dict]:
    """Moduli più chiesti dall'assistente senza dati live, con nome leggibile."""
    try:
        from ai_assistant.permessi_utente import MODULI

        nomi = {m.slug: (m.nome, bool(m.tool_prefix)) for m in MODULI}
    except Exception:
        nomi = {}
    righe = []
    for slug, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
        nome, ha_tool = nomi.get(slug, (slug, False))
        righe.append({"slug": slug, "nome": nome, "count": count, "ha_tool": ha_tool})
    return righe


def _faq_gruppi() -> list:
    try:
        from ai_assistant.faq_suggerite import gruppi_da_rivedere

        return gruppi_da_rivedere()
    except Exception:
        return []


def _ai_conversazioni_stats() -> dict | None:
    """Conteggi aggregati dello storico chat AI (mai i contenuti); None se non disponibile."""
    try:
        from ai_assistant.conversazioni import abilitato, statistiche

        return {**statistiche(), "abilitato": abilitato()}
    except Exception:
        return None


@legacy_admin_required
def ai_settings(request: HttpRequest):
    ollama_defaults = _helpers._ollama_diag_defaults()
    result_ollama = None
    edit_entry = None
    runtime_test_result = None
    active_tab = (request.GET.get("tab") or "runtime").strip() or "runtime"

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        active_tab = (request.POST.get("tab") or active_tab).strip() or active_tab
        if action in ("test_ollama_config", "save_ollama_config"):
            ollama_defaults = _helpers._ollama_posted_config(request.POST, ollama_defaults)
            if action == "test_ollama_config":
                ok, msg, metadata = _helpers._ollama_test_connect(ollama_defaults)
                result_ollama = {"ok": ok, "message": msg}
                _helpers._audit_safe(
                    request,
                    "ollama_config_test",
                    "admin_portale",
                    {
                        "ok": ok,
                        "provider": str(ollama_defaults.get("provider") or "ollama"),
                        "base_url_host": urlsplit(str(ollama_defaults.get("base_url") or "")).netloc,
                        "model": str(ollama_defaults.get("model") or ""),
                        "rag_enabled": bool(ollama_defaults.get("rag_enabled")),
                        "version": metadata.get("version") if isinstance(metadata, dict) else "",
                        "model_available": metadata.get("model_available") if isinstance(metadata, dict) else None,
                    },
                )
            else:
                ok, msg, normalized = _helpers._ollama_save_settings(ollama_defaults)
                result_ollama = {"ok": ok, "message": msg}
                ollama_defaults = _helpers._ollama_diag_defaults() if ok else normalized
                _helpers._audit_safe(
                    request,
                    "ollama_config_save",
                    "admin_portale",
                    {
                        "ok": ok,
                        "enabled": bool(ollama_defaults.get("enabled")),
                        "provider": str(ollama_defaults.get("provider") or "ollama"),
                        "base_url_host": urlsplit(str(ollama_defaults.get("base_url") or "")).netloc,
                        "model": str(ollama_defaults.get("model") or ""),
                        "rag_enabled": bool(ollama_defaults.get("rag_enabled")),
                        "rag_max_chunks": ollama_defaults.get("rag_max_chunks"),
                        "rag_max_db_entries": ollama_defaults.get("rag_max_db_entries"),
                    },
                )
        elif action in {"save_knowledge", "toggle_knowledge", "delete_knowledge"}:
            response, edit_entry = _handle_ai_knowledge_post(request, redirect_to="admin_portale:ai_settings")
            if response is not None:
                return response
        elif action == "test_ai_runtime_tool":
            active_tab = "tools"
            runtime_test_result = _ai_runtime_tool_test(request)
        elif action == "clear_ai_runtime_cache":
            clear_knowledge_cache()
            _helpers._audit_safe(
                request,
                "ai_runtime_cache_clear",
                "ai_assistant",
                {"cache": "rag_runtime", "scope": "metadata_only"},
            )
            messages.success(request, "Cache RAG/runtime svuotata.")
            return redirect(f"{reverse('admin_portale:ai_settings')}?tab=tools")
        elif action in {"faq_genera_bozza", "faq_approva_gruppo", "faq_scarta_gruppo"}:
            # Fase 4: FAQ suggerite dai 👎. Solo chi gestisce la knowledge base.
            from ai_assistant import faq_suggerite
            from ai_assistant.views import _can_manage_knowledge

            redirect_url = f"{reverse('admin_portale:ai_settings')}?tab=suggerimenti"
            if not _can_manage_knowledge(request):
                messages.error(request, "Serve il permesso «Assistente AI - Gestione knowledge base».")
                return redirect(redirect_url)
            ids = faq_suggerite.parse_ids(request.POST.get("ids"))
            if action == "faq_genera_bozza":
                bozza, esito = faq_suggerite.genera_bozza(request, ids)
                (messages.success if bozza else messages.warning)(request, esito)
                _helpers._audit_safe(request, "ai_faq_bozza", "ai_assistant",
                            {"feedback": len(ids), "bozza_id": getattr(bozza, "pk", None)})
            elif action == "faq_approva_gruppo":
                entry = faq_suggerite.approva(
                    request, ids, request.POST.get("question") or "", request.POST.get("answer") or "",
                )
                if entry is None:
                    messages.error(request, "Domanda e risposta sono obbligatorie.")
                else:
                    messages.success(request, "FAQ attivata: l'assistente la usa da subito.")
                    _helpers._audit_safe(request, "ai_faq_approvata", "ai_assistant",
                                {"feedback": len(ids), "knowledge_entry_id": entry.pk})
            else:
                numero = faq_suggerite.scarta(ids)
                messages.success(request, f"Gruppo scartato ({numero} feedback chiusi).")
                _helpers._audit_safe(request, "ai_faq_scartata", "ai_assistant", {"feedback": numero})
            return redirect(redirect_url)
        elif action == "purge_ai_conversations":
            # Storico chat: l'admin non legge i contenuti, può solo svuotarlo per tutti.
            from ai_assistant.models import AiConversation

            if (request.POST.get("conferma") or "") != "1":
                messages.error(request, "Spunta la conferma per cancellare lo storico chat di tutti gli utenti.")
            else:
                numero = AiConversation.objects.count()
                AiConversation.objects.all().delete()
                _helpers._audit_safe(
                    request,
                    "ai_conversazioni_svuotate",
                    "ai_assistant",
                    {"conversazioni": numero, "scope": "tutti_gli_utenti"},
                )
                messages.success(request, f"Storico chat svuotato: {numero} conversazioni cancellate.")
            return redirect(f"{reverse('admin_portale:ai_settings')}?tab=governance")
        elif action == "save_governance_review":
            active_tab = "governance"
            tool_key = (request.POST.get("tool_key") or "").strip()[:80]
            privacy_status = (request.POST.get("privacy_status") or "pending").strip()
            if privacy_status not in {"pending", "approved", "restricted", "blocked"}:
                privacy_status = "pending"
            allowed_fields = (request.POST.get("allowed_fields") or "").strip()[:1000]
            blocked_fields = (request.POST.get("blocked_fields") or "").strip()[:1000]
            notes = (request.POST.get("notes") or "").strip()[:2000]
            retention_raw = (request.POST.get("retention_days") or "").strip()
            retention_days = None
            if retention_raw:
                try:
                    retention_days = max(1, min(3650, int(retention_raw)))
                except (ValueError, TypeError):
                    retention_days = None
            catalog_keys = {spec.key for spec in get_runtime_tool_catalog()}
            if not tool_key or tool_key not in catalog_keys:
                messages.error(request, "Chiave tool non valida.")
            else:
                spec = next((s for s in get_runtime_tool_catalog() if s.key == tool_key), None)
                review, _ = AiToolPrivacyReview.objects.get_or_create(tool_key=tool_key)
                review.tool_label = spec.label if spec else tool_key
                review.privacy_status = privacy_status
                review.allowed_fields = allowed_fields
                review.blocked_fields = blocked_fields
                review.notes = notes
                review.retention_days = retention_days
                review.reviewed_by = request.user
                review.reviewed_at = timezone.now()
                review.save()
                _helpers._audit_safe(
                    request,
                    "ai_governance_review_save",
                    "ai_assistant",
                    {
                        "tool_key": tool_key,
                        "privacy_status": privacy_status,
                        "has_allowed_fields": bool(allowed_fields),
                        "has_blocked_fields": bool(blocked_fields),
                        "has_retention": retention_days is not None,
                    },
                )
                messages.success(request, f"Revisione privacy per '{tool_key}' salvata.")
                return redirect(f"{reverse('admin_portale:ai_settings')}?tab=governance")
        elif action:
            messages.error(request, "Azione Gestione AI non valida.")

    edit_id = request.GET.get("edit")
    if edit_id and edit_entry is None:
        edit_entry = AiKnowledgeEntry.objects.filter(id=edit_id).first()

    q = (request.GET.get("q") or "").strip()
    active = (request.GET.get("active") or "").strip()
    entries = AiKnowledgeEntry.objects.select_related("created_by", "updated_by").all()
    if q:
        entries = entries.filter(Q(question__icontains=q) | Q(answer__icontains=q) | Q(source_label__icontains=q))
    if active == "1":
        entries = entries.filter(is_active=True)
    elif active == "0":
        entries = entries.filter(is_active=False)

    page_obj = Paginator(entries, 10).get_page(request.GET.get("page"))
    runtime_metric_days = _safe_int(request.GET.get("runtime_days"), 30, minimum=1, maximum=365)
    runtime_catalog = _ai_runtime_catalog_with_metrics(days=runtime_metric_days)
    runtime_audit_rows, runtime_audit_filters = _ai_runtime_audit_rows(request, catalog=runtime_catalog)
    User = get_user_model()

    # Governance tab context
    governance_reviews = {r.tool_key: r for r in AiToolPrivacyReview.objects.select_related("reviewed_by").all()}
    governance_rows = [
        {"spec": spec, "review": governance_reviews.get(spec.key)}
        for spec in get_runtime_tool_catalog()
    ]
    governance_edit_key = (request.GET.get("edit_review") or "").strip()[:80] or None
    catalog_keys = {spec.key for spec in get_runtime_tool_catalog()}
    if governance_edit_key and governance_edit_key not in catalog_keys:
        governance_edit_key = None
    governance_edit_review = governance_reviews.get(governance_edit_key) if governance_edit_key else None

    # Feedback tab context
    feedback_filter = (request.GET.get("feedback_filter") or "pending").strip()
    feedback_qs = AiChatFeedback.objects.select_related("user", "knowledge_entry").order_by("-created_at")
    if feedback_filter == "pending":
        feedback_qs = feedback_qs.filter(is_reviewed=False)
    feedback_page_obj = Paginator(feedback_qs, 20).get_page(request.GET.get("feedback_page"))
    feedback_pending_count = AiChatFeedback.objects.filter(is_reviewed=False).count()

    # Suggerimenti tab context: aggregazione statistica ultimi 30 giorni
    from core.models import AuditLog
    import datetime as _dt
    thirty_days_ago = timezone.now() - _dt.timedelta(days=30)
    ai_chat_logs = AuditLog.objects.filter(
        azione="ai_chat",
        created_at__gte=thirty_days_ago,
    )
    total_chat_sessions = ai_chat_logs.count()
    # Sessioni senza dati: nessun tool live (runtime_sources_count=0) e nessun RAG (rag_sources_count=0)
    # I valori sono in dettaglio (JSONField). Conta le sessioni con entrambi a 0.
    no_data_sessions = 0
    moduli_senza_dati_counter: dict[str, int] = {}
    prompt_short = 0   # < 50 char
    prompt_medium = 0  # 50-200 char
    prompt_long = 0    # > 200 char
    for log_row in ai_chat_logs.iterator():
        detail = log_row.dettaglio or {}
        runtime_cnt = detail.get("runtime_sources_count", None)
        rag_cnt = detail.get("rag_sources_count", None)
        prompt_chars = detail.get("prompt_chars", 0) or 0
        if runtime_cnt == 0 and rag_cnt == 0:
            no_data_sessions += 1
        for slug in detail.get("moduli_senza_dati") or []:
            slug = str(slug)[:40]
            moduli_senza_dati_counter[slug] = moduli_senza_dati_counter.get(slug, 0) + 1
        if prompt_chars < 50:
            prompt_short += 1
        elif prompt_chars <= 200:
            prompt_medium += 1
        else:
            prompt_long += 1

    return render(
        request,
        "admin_portale/pages/ai_settings.html",
        {
            "ollama_cfg": ollama_defaults,
            "result_ollama": result_ollama,
            "dotenv_target_label": _helpers._dotenv_target_label(_helpers._dotenv_path()),
            "page_obj": page_obj,
            "edit_entry": edit_entry,
            "q": q,
            "active": active,
            "active_count": AiKnowledgeEntry.objects.filter(is_active=True).count(),
            "total_count": AiKnowledgeEntry.objects.count(),
            "active_tab": active_tab,
            "runtime_catalog": runtime_catalog,
            "runtime_audit_rows": runtime_audit_rows,
            "runtime_audit_filters": runtime_audit_filters,
            "runtime_test_result": runtime_test_result,
            "runtime_simulated_users": User.objects.filter(is_active=True).order_by("username")[:100],
            "governance_rows": governance_rows,
            "governance_edit_key": governance_edit_key,
            "governance_edit_review": governance_edit_review,
            "governance_doc_url": "../../docs/ai/13_AI_GOVERNANCE.md",
            "conversazioni_stats": _ai_conversazioni_stats(),
            "faq_gruppi": _faq_gruppi() if active_tab == "suggerimenti" else [],
            # Feedback tab
            "feedback_page_obj": feedback_page_obj,
            "feedback_filter": feedback_filter,
            "feedback_pending_count": feedback_pending_count,
            # Suggerimenti tab
            "no_data_sessions": no_data_sessions,
            "moduli_senza_dati": _moduli_senza_dati_rows(moduli_senza_dati_counter),
            "total_chat_sessions": total_chat_sessions,
            "prompt_short": prompt_short,
            "prompt_medium": prompt_medium,
            "prompt_long": prompt_long,
        },
    )


@legacy_admin_required
def ai_knowledge(request: HttpRequest):
    edit_entry = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        entry_id = request.POST.get("entry_id")
        entry = AiKnowledgeEntry.objects.filter(id=entry_id).first() if entry_id else None

        if action == "save":
            question = _clean_ai_knowledge_text(request.POST.get("question"), limit=500)
            answer = _clean_ai_knowledge_text(request.POST.get("answer"), limit=6000)
            source_label = _clean_ai_knowledge_text(request.POST.get("source_label") or "FAQ Portale", limit=120)
            is_active = _helpers._bool_from_any(request.POST.get("is_active"))
            if not question or not answer:
                messages.error(request, "Domanda e risposta sono obbligatorie.")
                if entry:
                    edit_entry = entry
            else:
                if entry is None:
                    entry = AiKnowledgeEntry(created_by=request.user)
                    audit_action = "ai_knowledge_create"
                else:
                    audit_action = "ai_knowledge_update"
                entry.question = question
                entry.answer = answer
                entry.source_label = source_label or "FAQ Portale"
                entry.is_active = is_active
                entry.updated_by = request.user
                entry.save()
                clear_knowledge_cache()
                log_action(
                    request,
                    audit_action,
                    "ai_assistant",
                    {
                        "entry_id": entry.id,
                        "question_chars": len(question),
                        "answer_chars": len(answer),
                        "source_label": entry.source_label,
                        "is_active": entry.is_active,
                    },
                )
                messages.success(request, "FAQ AI salvata.")
                return redirect("admin_portale:ai_knowledge")
        elif action in {"toggle", "delete"} and entry:
            if action == "toggle":
                entry.is_active = not entry.is_active
                entry.updated_by = request.user
                entry.save(update_fields=["is_active", "updated_by", "updated_at"])
                clear_knowledge_cache()
                log_action(
                    request,
                    "ai_knowledge_toggle",
                    "ai_assistant",
                    {"entry_id": entry.id, "is_active": entry.is_active},
                )
                messages.success(request, "Stato FAQ AI aggiornato.")
            else:
                deleted_id = entry.id
                entry.delete()
                clear_knowledge_cache()
                log_action(request, "ai_knowledge_delete", "ai_assistant", {"entry_id": deleted_id})
                messages.success(request, "FAQ AI eliminata.")
            return redirect("admin_portale:ai_knowledge")
        elif action:
            messages.error(request, "Azione FAQ AI non valida.")

    edit_id = request.GET.get("edit")
    if edit_id and edit_entry is None:
        edit_entry = AiKnowledgeEntry.objects.filter(id=edit_id).first()

    q = (request.GET.get("q") or "").strip()
    active = (request.GET.get("active") or "").strip()
    entries = AiKnowledgeEntry.objects.select_related("created_by", "updated_by").all()
    if q:
        entries = entries.filter(Q(question__icontains=q) | Q(answer__icontains=q) | Q(source_label__icontains=q))
    if active == "1":
        entries = entries.filter(is_active=True)
    elif active == "0":
        entries = entries.filter(is_active=False)

    paginator = Paginator(entries, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admin_portale/pages/ai_knowledge.html",
        {
            "page_obj": page_obj,
            "edit_entry": edit_entry,
            "q": q,
            "active": active,
            "active_count": AiKnowledgeEntry.objects.filter(is_active=True).count(),
            "total_count": AiKnowledgeEntry.objects.count(),
        },
    )


def _django_user_is_privileged(django_user) -> bool:
    if django_user is None:
        return False
    if getattr(django_user, "is_superuser", False) or getattr(django_user, "is_staff", False):
        return True
    try:
        from core.legacy_utils import is_legacy_admin

        return bool(is_legacy_admin(get_legacy_user(django_user)))
    except Exception:
        return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CHECKLIST â€” Onboarding / Offboarding
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _checklist_last_per_user(tipo: str, user_ids: list[int]) -> dict[int, "ChecklistEsecuzione"]:
    """Ritorna l'ultima esecuzione del tipo dato, una per user_id. 2 query totali per entrambi i tipi."""
    # Django non supporta GROUP BY + ORDER BY direttamente; usiamo ordinamento + seen set.
    seen: set[int] = set()
    result: dict[int, ChecklistEsecuzione] = {}
    for esec in ChecklistEsecuzione.objects.filter(
        tipo_checklist=tipo, legacy_user_id__in=user_ids
    ).order_by("legacy_user_id", "-data_esecuzione"):
        if esec.legacy_user_id not in seen:
            seen.add(esec.legacy_user_id)
            result[esec.legacy_user_id] = esec
    return result


@legacy_admin_required
@require_GET
def checklist_index(request):
    """Vista globale: configurazione voci + panoramica utenti."""
    voci_checkin  = list(ChecklistVoce.objects.filter(tipo_checklist="checkin").order_by("categoria", "ordine", "id"))
    voci_checkout = list(ChecklistVoce.objects.filter(tipo_checklist="checkout").order_by("categoria", "ordine", "id"))
    # Pre-serialize scelte as JSON so the template can output safe data-* attributes
    for v in voci_checkin + voci_checkout:
        v.scelte_json = json.dumps(v.scelte)
    utenti = list(UtenteLegacy.objects.filter(attivo=True).order_by("nome"))

    # Stato check-in/out: 2 query bulk invece di 2N
    user_ids = [u.id for u in utenti]
    checkin_map  = _checklist_last_per_user("checkin",  user_ids)
    checkout_map = _checklist_last_per_user("checkout", user_ids)

    utenti_con_stato = [
        {"utente": u, "checkin": checkin_map.get(u.id), "checkout": checkout_map.get(u.id)}
        for u in utenti
    ]

    return render(request, "admin_portale/pages/checklist_index.html", {
        "page_title": "Onboarding / Offboarding",
        "voci_checkin":  voci_checkin,
        "voci_checkout": voci_checkout,
        "utenti_con_stato": utenti_con_stato,
    })


@legacy_admin_required
@require_GET
def checklist_utente(request, user_id: int):
    """Vista per-utente: form esecuzione + storico."""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    voci_checkin  = list(ChecklistVoce.objects.filter(tipo_checklist="checkin",  is_active=True).order_by("categoria", "ordine", "id"))
    voci_checkout = list(ChecklistVoce.objects.filter(tipo_checklist="checkout", is_active=True).order_by("categoria", "ordine", "id"))
    esecuzioni = list(
        ChecklistEsecuzione.objects.filter(legacy_user_id=user_id)
        .prefetch_related("risposte")
        .order_by("-data_esecuzione")[:50]
    )
    return render(request, "admin_portale/pages/checklist_utente.html", {
        "page_title": f"Checklist â€” {utente.nome}",
        "utente_obj": utente,
        "voci_checkin":  voci_checkin,
        "voci_checkout": voci_checkout,
        "esecuzioni": esecuzioni,
    })


@legacy_admin_required
@require_POST
def api_checklist_voce_create(request):
    """Crea una nuova voce checklist. Payload: {tipo_checklist, label, tipo_campo, scelte[], obbligatorio, ordine}"""
    payload = _helpers._json_payload(request)
    tipo = (payload.get("tipo_checklist") or "").strip()
    label = (payload.get("label") or "").strip()
    if tipo not in ("checkin", "checkout") or not label:
        return JsonResponse({"ok": False, "error": "tipo_checklist e label obbligatori."}, status=400)
    try:
        voce = ChecklistVoce.objects.create(
            tipo_checklist=tipo,
            categoria=_normalize_category(payload.get("categoria"), default="Generale"),
            label=label[:300],
            tipo_campo=(payload.get("tipo_campo") or "check").strip(),
            scelte=payload.get("scelte") or [],
            obbligatorio=bool(payload.get("obbligatorio", False)),
            ordine=int(payload.get("ordine") or 100),
            is_active=True,
        )
        _helpers._audit_safe(
            request,
            "checklist_voce_create",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "tipo_checklist": voce.tipo_checklist,
                "categoria": voce.categoria,
                "label": voce.label,
                "tipo_campo": voce.tipo_campo,
                "scelte": voce.scelte,
                "obbligatorio": voce.obbligatorio,
                "ordine": voce.ordine,
                "is_active": voce.is_active,
            },
        )
        return JsonResponse({"ok": True, "id": voce.id})
    except Exception:
        _helpers.logger.exception("api_checklist_voce_create: errore creazione voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_update(request):
    """Aggiorna una voce checklist. Payload: {id, label, tipo_campo, scelte[], obbligatorio, ordine}"""
    payload = _helpers._json_payload(request)
    voce_id = _helpers._int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    try:
        before = {
            "tipo_checklist": voce.tipo_checklist,
            "categoria": voce.categoria,
            "label": voce.label,
            "tipo_campo": voce.tipo_campo,
            "scelte": voce.scelte,
            "obbligatorio": voce.obbligatorio,
            "ordine": voce.ordine,
            "is_active": voce.is_active,
        }
        if payload.get("categoria") is not None:
            voce.categoria = _normalize_category(payload.get("categoria"), default=voce.categoria or "Generale")
        voce.label       = (payload.get("label") or voce.label).strip()[:300]
        voce.tipo_campo  = (payload.get("tipo_campo") or voce.tipo_campo).strip()
        voce.scelte      = payload.get("scelte") if payload.get("scelte") is not None else voce.scelte
        voce.obbligatorio = bool(payload.get("obbligatorio", voce.obbligatorio))
        voce.ordine      = int(payload.get("ordine") or voce.ordine)
        voce.save()
        _helpers._audit_safe(
            request,
            "checklist_voce_update",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "before": before,
                "after": {
                    "tipo_checklist": voce.tipo_checklist,
                    "categoria": voce.categoria,
                    "label": voce.label,
                    "tipo_campo": voce.tipo_campo,
                    "scelte": voce.scelte,
                    "obbligatorio": voce.obbligatorio,
                    "ordine": voce.ordine,
                    "is_active": voce.is_active,
                },
            },
        )
        return JsonResponse({"ok": True})
    except Exception:
        _helpers.logger.exception("api_checklist_voce_update: errore aggiornamento voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_toggle(request):
    """Attiva/disattiva una voce. Payload: {id, is_active}"""
    payload = _helpers._json_payload(request)
    voce_id = _helpers._int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    try:
        before = bool(voce.is_active)
        voce.is_active = bool(payload.get("is_active", not voce.is_active))
        voce.save(update_fields=["is_active"])
        _helpers._audit_safe(
            request,
            "checklist_voce_toggle",
            "admin_checklist",
            {
                "voce_id": voce.id,
                "before_is_active": before,
                "after_is_active": bool(voce.is_active),
            },
        )
        return JsonResponse({"ok": True, "is_active": voce.is_active})
    except Exception:
        _helpers.logger.exception("api_checklist_voce_toggle: errore toggle voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_voce_delete(request):
    """Elimina una voce (solo se non ha risposte registrate). Payload: {id}"""
    payload = _helpers._json_payload(request)
    voce_id = _helpers._int_or_none(payload.get("id"))
    if not voce_id:
        return JsonResponse({"ok": False, "error": "id mancante."}, status=400)
    voce = get_object_or_404(ChecklistVoce, id=voce_id)
    before = {
        "voce_id": voce.id,
        "tipo_checklist": voce.tipo_checklist,
        "categoria": voce.categoria,
        "label": voce.label,
        "tipo_campo": voce.tipo_campo,
        "scelte": voce.scelte,
        "obbligatorio": voce.obbligatorio,
        "ordine": voce.ordine,
        "is_active": voce.is_active,
    }
    if ChecklistRisposta.objects.filter(voce_id=voce_id).exists():
        return JsonResponse({"ok": False, "error": "Impossibile eliminare: la voce ha risposte registrate. Usa disattiva."}, status=400)
    try:
        voce.delete()
        _helpers._audit_safe(request, "checklist_voce_delete", "admin_checklist", before)
        return JsonResponse({"ok": True})
    except Exception:
        _helpers.logger.exception("api_checklist_voce_delete: errore eliminazione voce")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_checklist_esegui(request, user_id: int):
    """Salva un'esecuzione checklist per un utente.
    Payload: {tipo: "checkin"|"checkout", note: "", risposte: [{voce_id, valore}]}
    """
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    tipo = (payload.get("tipo") or "").strip()
    if tipo not in ("checkin", "checkout"):
        return JsonResponse({"ok": False, "error": "tipo non valido."}, status=400)

    legacy_user = get_legacy_user(request.user)
    admin_id   = legacy_user.id if legacy_user else None
    admin_nome = (legacy_user.nome if legacy_user else request.user.get_full_name()) or request.user.username

    risposte_raw: list = payload.get("risposte") or []
    # Carica snapshot voci
    voce_ids = [r.get("voce_id") for r in risposte_raw if r.get("voce_id")]
    voci_map = {v.id: v for v in ChecklistVoce.objects.filter(id__in=voce_ids)}

    try:
        with transaction.atomic():
            esec = ChecklistEsecuzione.objects.create(
                legacy_user_id=utente.id,
                utente_nome=utente.nome or "",
                tipo_checklist=tipo,
                eseguita_da_id=admin_id,
                eseguita_da_nome=admin_nome,
                note=(payload.get("note") or "").strip(),
                completata=True,
            )
            bulk = []
            for r in risposte_raw:
                vid = _helpers._int_or_none(r.get("voce_id"))
                if not vid:
                    continue
                voce = voci_map.get(vid)
                bulk.append(ChecklistRisposta(
                    esecuzione=esec,
                    voce_id=vid,
                    voce_label=voce.label if voce else f"Voce #{vid}",
                    voce_tipo=voce.tipo_campo if voce else "testo",
                    valore=(r.get("valore") or ""),
                ))
            ChecklistRisposta.objects.bulk_create(bulk)
        _helpers._audit_safe(
            request,
            "checklist_esecuzione_create",
            "admin_checklist",
            {
                "esecuzione_id": esec.id,
                "target_user_id": utente.id,
                "target_user_nome": utente.nome or "",
                "tipo_checklist": tipo,
                "note": (payload.get("note") or "").strip(),
                "risposte_count": len(bulk),
                "risposte": [
                    {
                        "voce_id": r.voce_id,
                        "voce_label": r.voce_label,
                        "voce_tipo": r.voce_tipo,
                        "voce_categoria": (voci_map.get(r.voce_id).categoria if voci_map.get(r.voce_id) else ""),
                        "valore": r.valore,
                    }
                    for r in bulk
                ],
            },
        )
        return JsonResponse({"ok": True, "esecuzione_id": esec.id})
    except Exception:
        _helpers.logger.exception("api_checklist_esegui: errore salvataggio esecuzione")
        return JsonResponse({"ok": False, "error": "Errore interno del server."}, status=500)


@legacy_admin_required
@require_POST
def api_opzione_create(request):
    payload = _helpers._json_payload(request)
    tipo = (payload.get("tipo") or "").strip()[:50]
    valore = (payload.get("valore") or "").strip()[:200]
    if not tipo or not valore:
        return JsonResponse({"ok": False, "error": "tipo e valore obbligatori."}, status=400)
    legacy_user_id = None
    if tipo.lower() == "caporeparto":
        normalized = normalize_caporeparto_option(
            valore,
            legacy_user_id=_helpers._int_or_none(payload.get("legacy_user_id")),
            promote_role=True,
        )
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        legacy_user_id = int(normalized["legacy_user_id"])
        valore = str(normalized["value"] or "").strip()[:200]
        duplicate = OptioneConfig.objects.filter(tipo__iexact="caporeparto", legacy_user_id=legacy_user_id).first()
        if duplicate:
            return JsonResponse({"ok": False, "error": "Questo utente Ã¨ giÃ  configurato come caporeparto."}, status=400)
    o = OptioneConfig.objects.create(
        tipo=tipo,
        valore=valore,
        legacy_user_id=legacy_user_id,
        ordine=int(payload.get("ordine") or 100),
    )
    return JsonResponse({"ok": True, "id": o.id})


@legacy_admin_required
@require_POST
def api_opzione_update(request):
    payload = _helpers._json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_helpers._int_or_none(payload.get("id")))
    valore = (payload.get("valore") or "").strip()[:200]
    if not valore:
        return JsonResponse({"ok": False, "error": "valore obbligatorio."}, status=400)
    if str(o.tipo or "").strip().lower() == "caporeparto":
        normalized = normalize_caporeparto_option(
            valore,
            legacy_user_id=_helpers._int_or_none(payload.get("legacy_user_id")) or _helpers._int_or_none(getattr(o, "legacy_user_id", None)),
            promote_role=True,
        )
        if not normalized.get("ok"):
            return JsonResponse({"ok": False, "error": normalized.get("error") or "Caporeparto non valido."}, status=400)
        legacy_user_id = int(normalized["legacy_user_id"])
        duplicate = OptioneConfig.objects.filter(tipo__iexact="caporeparto", legacy_user_id=legacy_user_id).exclude(id=o.id).first()
        if duplicate:
            return JsonResponse({"ok": False, "error": "Questo utente Ã¨ giÃ  configurato come caporeparto."}, status=400)
        o.legacy_user_id = legacy_user_id
        o.valore = str(normalized["value"] or "").strip()[:200]
    else:
        o.valore = valore
        if hasattr(o, "legacy_user_id"):
            o.legacy_user_id = None
    if payload.get("ordine") is not None:
        o.ordine = int(payload.get("ordine") or 100)
    o.save()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_opzione_toggle(request):
    payload = _helpers._json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_helpers._int_or_none(payload.get("id")))
    o.is_active = bool(payload.get("is_active", True))
    o.save()
    return JsonResponse({"ok": True, "is_active": o.is_active})


@legacy_admin_required
@require_POST
def api_opzione_delete(request):
    payload = _helpers._json_payload(request)
    o = get_object_or_404(OptioneConfig, id=_helpers._int_or_none(payload.get("id")))
    o.delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_create(request):
    payload = _helpers._json_payload(request)
    label = (payload.get("label") or "").strip()[:300]
    if not label:
        return JsonResponse({"ok": False, "error": "label obbligatoria."}, status=400)
    v = AnagraficaVoce.objects.create(
        categoria=_normalize_category(payload.get("categoria"), default="Campi extra"),
        label=label,
        tipo_campo=payload.get("tipo_campo") or "testo",
        scelte=payload.get("scelte") or [],
        obbligatorio=bool(payload.get("obbligatorio", False)),
        ordine=int(payload.get("ordine") or 100),
    )
    _helpers._audit_safe(
        request,
        "anagrafica_voce_create",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "categoria": v.categoria,
            "label": v.label,
            "tipo_campo": v.tipo_campo,
            "scelte": v.scelte,
            "obbligatorio": v.obbligatorio,
            "ordine": v.ordine,
            "is_active": v.is_active,
        },
    )
    return JsonResponse({"ok": True, "id": v.id})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_update(request):
    payload = _helpers._json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_helpers._int_or_none(payload.get("id")))
    before = {
        "categoria": v.categoria,
        "label": v.label,
        "tipo_campo": v.tipo_campo,
        "scelte": v.scelte,
        "obbligatorio": v.obbligatorio,
        "ordine": v.ordine,
        "is_active": v.is_active,
    }
    if payload.get("categoria") is not None:
        v.categoria = _normalize_category(payload.get("categoria"), default=v.categoria or "Campi extra")
    if payload.get("label") is not None:
        v.label = (payload["label"] or "").strip()[:300]
    if payload.get("tipo_campo") is not None:
        v.tipo_campo = payload["tipo_campo"]
    if payload.get("scelte") is not None:
        v.scelte = payload["scelte"] or []
    if payload.get("obbligatorio") is not None:
        v.obbligatorio = bool(payload["obbligatorio"])
    if payload.get("ordine") is not None:
        v.ordine = int(payload["ordine"] or 100)
    v.save()
    _helpers._audit_safe(
        request,
        "anagrafica_voce_update",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "before": before,
                "after": {
                    "categoria": v.categoria,
                    "label": v.label,
                    "tipo_campo": v.tipo_campo,
                    "scelte": v.scelte,
                    "obbligatorio": v.obbligatorio,
                    "ordine": v.ordine,
                "is_active": v.is_active,
            },
        },
    )
    return JsonResponse({"ok": True})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_toggle(request):
    payload = _helpers._json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_helpers._int_or_none(payload.get("id")))
    before = bool(v.is_active)
    v.is_active = bool(payload.get("is_active", True))
    v.save()
    _helpers._audit_safe(
        request,
        "anagrafica_voce_toggle",
        "admin_anagrafica",
        {
            "voce_id": v.id,
            "before_is_active": before,
            "after_is_active": bool(v.is_active),
        },
    )
    return JsonResponse({"ok": True, "is_active": v.is_active})


@legacy_admin_required
@require_POST
def api_anagrafica_voce_delete(request):
    payload = _helpers._json_payload(request)
    v = get_object_or_404(AnagraficaVoce, id=_helpers._int_or_none(payload.get("id")))
    before = {
        "voce_id": v.id,
        "categoria": v.categoria,
        "label": v.label,
        "tipo_campo": v.tipo_campo,
        "scelte": v.scelte,
        "obbligatorio": v.obbligatorio,
        "ordine": v.ordine,
        "is_active": v.is_active,
    }
    if AnagraficaRisposta.objects.filter(voce=v).exists():
        return JsonResponse({"ok": False, "error": "Impossibile eliminare: esistono risposte registrate."}, status=400)
    v.delete()
    _helpers._audit_safe(request, "anagrafica_voce_delete", "admin_anagrafica", before)
    return JsonResponse({"ok": True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Audit log
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _audit_queryset_from_request(request):
    from core.models import AuditLog

    qs = AuditLog.objects.all()
    filtro_modulo = (request.GET.get("modulo") or "").strip()
    filtro_azione = (request.GET.get("azione") or "").strip()
    filtro_data = (request.GET.get("data") or "").strip()

    if filtro_modulo:
        qs = qs.filter(modulo=filtro_modulo)
    if filtro_azione:
        qs = qs.filter(azione__icontains=filtro_azione)
    if filtro_data:
        qs = qs.filter(created_at__date=filtro_data)

    return qs, filtro_modulo, filtro_azione, filtro_data


@legacy_admin_required
def audit_log_view(request):
    from core.models import AuditLog
    from django.core.paginator import Paginator

    qs, filtro_modulo, filtro_azione, filtro_data = _audit_queryset_from_request(request)
    export_format = (request.GET.get("export") or "").strip().lower()
    if export_format in {"csv", "xlsx"}:
        return export_rows_response(
            rows=qs.order_by("-created_at"),
            columns=[
                ("Data/Ora", "created_at"),
                ("Utente", lambda e: (e.utente_display or "").upper()),
                ("Legacy user ID", "legacy_user_id"),
                ("Modulo", "modulo"),
                ("Azione", "azione"),
                ("IP", "ip_address"),
                ("Dettaglio", "dettaglio"),
            ],
            filename="audit_log",
            fmt=export_format,
        )

    moduli_disponibili = AuditLog.objects.values_list("modulo", flat=True).distinct().order_by("modulo")

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "admin_portale/pages/audit_log.html", {
        "page_title": "Audit Log",
        "page_obj": page_obj,
        "filtro_modulo": filtro_modulo,
        "filtro_azione": filtro_azione,
        "filtro_data": filtro_data,
        "moduli_disponibili": moduli_disponibili,
    })


def _notifiche_display_names(legacy_ids) -> dict:
    """legacy_user_id → nome (da UtenteLegacy), fail-safe (fallback #id)."""
    names: dict = {}
    ids = [int(i) for i in legacy_ids if i]
    if not ids:
        return names
    try:
        from core.legacy_models import UtenteLegacy

        for row in UtenteLegacy.objects.filter(id__in=ids).values("id", "nome"):
            names[row["id"]] = naming.normalizza_parte(row["nome"]) or f"#{row['id']}"
    except Exception:
        pass
    return names


@legacy_admin_required
def notifiche_log_view(request):
    """Log amministrativo delle notifiche in-app (cross-utente): verifica cosa
    parte davvero e a chi. Filtri per tipo/utente/stato/giorni + conteggi per tipo."""
    from datetime import timedelta

    from django.core.paginator import Paginator

    from core.models import Notifica
    from core.notifiche_meta import notifica_meta

    days_raw = (request.GET.get("days") or "30").strip()
    try:
        days = max(1, min(365, int(days_raw)))
    except ValueError:
        days = 30
    since = timezone.now() - timedelta(days=days)

    filtro_tipo = (request.GET.get("tipo") or "").strip()
    filtro_user = (request.GET.get("legacy_user_id") or "").strip()
    filtro_stato = (request.GET.get("stato") or "").strip()  # "" | lette | non_lette

    qs = Notifica.objects.filter(created_at__gte=since)
    if filtro_tipo:
        qs = qs.filter(tipo=filtro_tipo)
    if filtro_user:
        qs = qs.filter(legacy_user_id=filtro_user)
    if filtro_stato == "lette":
        qs = qs.filter(letta=True)
    elif filtro_stato == "non_lette":
        qs = qs.filter(letta=False)
    elif filtro_stato == "archiviate":
        qs = qs.filter(archiviata=True)
    qs = qs.order_by("-created_at")

    # Conteggi per tipo nella finestra (con etichetta/icona dal registro).
    per_tipo = []
    for row in (
        Notifica.objects.filter(created_at__gte=since)
        .values("tipo")
        .annotate(total=Count("id"))
        .order_by("-total", "tipo")
    ):
        m = notifica_meta(row["tipo"])
        per_tipo.append(
            {"tipo": row["tipo"], "label": m["label"], "icona": m["icona"], "total": row["total"]}
        )

    export_format = (request.GET.get("export") or "").strip().lower()
    if export_format in {"csv", "xlsx"}:
        names = _notifiche_display_names(
            qs.values_list("legacy_user_id", flat=True).distinct()
        )
        return export_rows_response(
            rows=qs,
            columns=[
                ("Data/Ora", "created_at"),
                ("Utente", lambda n: names.get(n.legacy_user_id, f"#{n.legacy_user_id}")),
                ("Legacy user ID", "legacy_user_id"),
                ("Tipo", lambda n: notifica_meta(n.tipo)["label"]),
                ("Messaggio", "messaggio"),
                ("Letta", lambda n: "Si" if n.letta else "No"),
                ("Archiviata", lambda n: n.get_archiviata_motivo_display() if n.archiviata else ""),
                ("URL", "url_azione"),
            ],
            filename="notifiche_log",
            fmt=export_format,
        )

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    names = _notifiche_display_names([n.legacy_user_id for n in page_obj.object_list])
    for n in page_obj.object_list:
        n.utente_display = names.get(n.legacy_user_id, f"#{n.legacy_user_id}")
        n.meta = notifica_meta(n.tipo)

    return render(request, "admin_portale/pages/notifiche_log.html", {
        "page_title": "Log notifiche",
        "page_obj": page_obj,
        "per_tipo": per_tipo,
        "tipi_disponibili": [r["tipo"] for r in per_tipo],
        "filtro_tipo": filtro_tipo,
        "filtro_user": filtro_user,
        "filtro_stato": filtro_stato,
        "days": days,
        "totale": qs.count(),
        "non_lette": qs.filter(letta=False).count(),
    })


@legacy_admin_required
def notifiche_config_view(request):
    """Interruttore admin globale: accende/spegne per TUTTI ciascuna categoria di
    notifica (in-app; l'email lo eredita dove il sender consulta l'enforcement)."""
    from core import notifiche_archivio
    from core.notifiche_meta import CATEGORIE
    from core.notifiche_prefs import is_category_enabled_globally, set_category_global
    from core.security_notify import avviso_impersonazione_attivo, set_avviso_impersonazione

    if request.method == "POST":
        sezione = (request.POST.get("sezione") or "categorie").strip()
        if sezione == "archivio":
            politica = notifiche_archivio.set_politica(
                non_lette=request.POST.get("non_lette"),
                lette=request.POST.get("lette"),
                elimina=request.POST.get("elimina"),
            )
            log_action(request, "notifiche_archivio_config", "admin_portale", {
                "non_lette": politica.non_lette, "lette": politica.lette, "elimina": politica.elimina,
            })
            messages.success(request, "Regole di archiviazione salvate.")
        elif sezione == "archivia_ora":
            esito = notifiche_archivio.archivia_scadute()
            log_action(request, "notifiche_archivio_run", "admin_portale", esito)
            messages.success(
                request,
                f"Archiviazione eseguita: {esito['non_lette']} non lette e {esito['lette']} lette archiviate, "
                f"{esito['eliminate']} eliminate.",
            )
        elif sezione == "sicurezza":
            attivo = request.POST.get("avviso_impersonazione") == "1"
            set_avviso_impersonazione(attivo)
            log_action(request, "notifiche_avviso_impersonazione", "admin_portale", {"attivo": attivo})
            messages.success(
                request,
                "Avviso di impersonazione acceso." if attivo else "Avviso di impersonazione spento: resta solo l'audit.",
            )
        else:
            for cat in CATEGORIE:
                set_category_global(cat, enabled=(request.POST.get(f"cat_{cat}") == "1"))
            log_action(request, "notifiche_config", "admin_portale", {"categorie": list(CATEGORIE)})
            messages.success(request, "Interruttori notifiche aggiornati.")
        return redirect("admin_portale:notifiche_config")

    categorie = [
        {"key": cat, "label": label, "enabled": is_category_enabled_globally(cat)}
        for cat, label in CATEGORIE.items()
    ]
    return render(request, "admin_portale/pages/notifiche_config.html", {
        "page_title": "Gestione notifiche",
        "categorie": categorie,
        "politica": notifiche_archivio.get_politica(),
        "stats": notifiche_archivio.statistiche(),
        "max_giorni": notifiche_archivio.MAX_GIORNI,
        "avviso_impersonazione": avviso_impersonazione_attivo(),
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Health check admin
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@legacy_admin_required
def admin_health_check(request):
    from django.conf import settings as djsettings
    from django.db import connection, connections as all_connections
    from pathlib import Path

    checks = []

    # 1. DB Django (SQLite default)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks.append({"nome": "DB Django (SQLite)", "ok": True, "dettaglio": "Connesso"})
    except Exception as exc:
        checks.append({"nome": "DB Django (SQLite)", "ok": False, "dettaglio": str(exc)})

    # 2. DB Legacy (SQL Server) â€” alias "default" in prod, stessa conn in dev
    try:
        with all_connections["default"].cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM utenti")
            row = cur.fetchone()
        checks.append({"nome": "DB Legacy (tabella utenti)", "ok": True, "dettaglio": f"{row[0]} utenti"})
    except Exception as exc:
        checks.append({"nome": "DB Legacy (tabella utenti)", "ok": False, "dettaglio": str(exc)})

    # 3. Azure MSAL config
    msal_vars = ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]
    missing = [v for v in msal_vars if not getattr(djsettings, v, None)]
    msal_ok = not missing
    checks.append({
        "nome": "Azure MSAL Config",
        "ok": msal_ok,
        "dettaglio": "Configurato" if msal_ok else f"Variabili mancanti: {', '.join(missing)}",
    })

    # 4. File di log
    try:
        log_path = Path(djsettings.BASE_DIR) / "logs" / "app.log"
        if log_path.exists():
            size_kb = round(log_path.stat().st_size / 1024, 1)
            checks.append({"nome": "File di log", "ok": True, "dettaglio": f"{log_path} ({size_kb} KB)"})
        else:
            checks.append({"nome": "File di log", "ok": False, "dettaglio": f"Non trovato: {log_path}"})
    except Exception as exc:
        checks.append({"nome": "File di log", "ok": False, "dettaglio": str(exc)})

    # 5. Sessioni Django attive
    try:
        from django.contrib.sessions.models import Session
        from django.utils import timezone as tz
        n = Session.objects.filter(expire_date__gt=tz.now()).count()
        checks.append({"nome": "Sessioni attive", "ok": True, "dettaglio": f"{n} sessioni"})
    except Exception as exc:
        checks.append({"nome": "Sessioni attive", "ok": False, "dettaglio": str(exc)})

    # 6. Ultima notifica creata
    try:
        from core.models import Notifica
        ultima = Notifica.objects.order_by("-created_at").first()
        if ultima:
            checks.append({"nome": "Notifiche", "ok": True, "dettaglio": f"Ultima: {ultima.created_at:%d-%m-%Y %H:%M}"})
        else:
            checks.append({"nome": "Notifiche", "ok": True, "dettaglio": "Nessuna notifica presente"})
    except Exception as exc:
        checks.append({"nome": "Notifiche", "ok": False, "dettaglio": str(exc)})

    all_ok = all(c["ok"] for c in checks)
    return render(request, "admin_portale/pages/health_check.html", {
        "page_title": "Health Check",
        "checks": checks,
        "all_ok": all_ok,
    })


# ---------------------------------------------------------------------------
# GuestPortal SSO relay
# ---------------------------------------------------------------------------

def _read_guestportal_config() -> dict:
    return {
        "url": _helpers._effective_env_value("GUESTPORTAL_URL", ""),
        "field_username": _helpers._effective_env_value("GUESTPORTAL_FIELD_USERNAME", "username") or "username",
        "field_password": _helpers._effective_env_value("GUESTPORTAL_FIELD_PASSWORD", "password") or "password",
        "username_format": _helpers._effective_env_value("GUESTPORTAL_USERNAME_FORMAT", "upn") or "upn",
    }


def _build_guestportal_username(request, fmt: str) -> str:
    """
    Costruisce il valore username da passare al GuestPortal in base al formato:
    - 'upn'   â†’ alias@example.local  (usa request.legacy_user.email se disponibile)
    - 'alias' â†’ solo alias             (request.user.username)
    - 'ntlm'  â†’ DOMINIO\\alias
    """
    alias = request.user.username or ""
    legacy_user = getattr(request, "legacy_user", None)

    if fmt == "upn":
        if legacy_user and getattr(legacy_user, "email", None):
            return str(legacy_user.email)
        # Fallback: aggiungi il suffisso UPN dalle impostazioni
        upn_suffix = getattr(settings, "LDAP_UPN_SUFFIX", "@example.local")
        if "@" not in alias:
            return alias + upn_suffix
        return alias
    elif fmt == "ntlm":
        domain = getattr(settings, "LDAP_DOMAIN", "EXAMPLE")
        return f"{domain}\\{alias}"
    else:  # alias
        return alias


@legacy_admin_required
@require_GET
def guestportal_sso(request):
    """Pagina relay per accesso al GuestPortal con credenziali AD. Il browser
    POSTa direttamente all'URL esterno: la password non transita mai dal server Django."""
    cfg = _read_guestportal_config()
    if not cfg["url"]:
        messages.error(
            request,
            "URL GuestPortal non configurato. Imposta GUESTPORTAL_URL nel file .env."
        )
    username = _build_guestportal_username(request, cfg["username_format"])
    return render(request, "admin_portale/pages/guestportal_sso.html", {
        "page_title": "Accesso GuestPortal",
        "gp_url": cfg["url"],
        "gp_field_username": cfg["field_username"],
        "gp_field_password": cfg["field_password"],
        "gp_username": username,
    })


# ── AI Feedback admin actions ──────────────────────────────────────────────────


@require_POST
@legacy_admin_required
def ai_feedback_approva(request: HttpRequest, feedback_id: int):
    """Approva un feedback negativo: attiva la AiKnowledgeEntry collegata e marca il feedback come reviewed."""
    from ai_assistant.views import _can_manage_knowledge

    if not _can_manage_knowledge(request):
        return JsonResponse({"ok": False, "error": "Permessi insufficienti."}, status=403)

    feedback = get_object_or_404(AiChatFeedback, id=feedback_id)
    if feedback.knowledge_entry_id:
        entry = feedback.knowledge_entry
        entry.is_active = True
        entry.updated_by = request.user
        entry.save(update_fields=["is_active", "updated_by", "updated_at"])
        clear_knowledge_cache()
        _helpers._audit_safe(
            request,
            "ai_feedback_approva",
            "ai_assistant",
            {
                "feedback_id": feedback.id,
                "knowledge_entry_id": entry.id,
            },
        )
    feedback.is_reviewed = True
    feedback.save(update_fields=["is_reviewed"])
    messages.success(request, "Feedback approvato: FAQ AI attivata.")
    return redirect(f"{reverse('admin_portale:ai_settings')}?tab=feedback")


@require_POST
@legacy_admin_required
def ai_feedback_scarta(request: HttpRequest, feedback_id: int):
    """Scarta un feedback: lo marca come reviewed senza attivare la FAQ bozza."""
    from ai_assistant.views import _can_manage_knowledge

    if not _can_manage_knowledge(request):
        return JsonResponse({"ok": False, "error": "Permessi insufficienti."}, status=403)

    feedback = get_object_or_404(AiChatFeedback, id=feedback_id)
    feedback.is_reviewed = True
    feedback.save(update_fields=["is_reviewed"])
    _helpers._audit_safe(
        request,
        "ai_feedback_scarta",
        "ai_assistant",
        {"feedback_id": feedback.id},
    )
    messages.success(request, "Feedback scartato.")
    return redirect(f"{reverse('admin_portale:ai_settings')}?tab=feedback")


# ---------------------------------------------------------------------------
# 2FA — Configurazione policy e gestione utenti
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def twofa_config(request: HttpRequest):
    from twofa.models import TwoFactorPolicy, UserTwoFactor
    from core.legacy_models import Ruolo

    policy = TwoFactorPolicy.get()
    all_roles = list(Ruolo.objects.order_by("nome"))
    # Utenti con record 2FA
    user_2fa_qs = (
        UserTwoFactor.objects.select_related("user")
        .order_by("user__username")
    )
    return render(request, "admin_portale/pages/twofa_config.html", {
        "policy": policy,
        "all_roles": all_roles,
        "user_2fa_list": user_2fa_qs,
        "allowed_methods": policy.allowed_methods or ["totp", "email"],
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_twofa_policy_save(request: HttpRequest):
    from twofa.models import TwoFactorPolicy

    policy = TwoFactorPolicy.get()
    policy.enabled = request.POST.get("enabled") == "1"
    policy.when_required = request.POST.get("when_required", "external_only")
    if policy.when_required not in ("always", "external_only", "new_device"):
        policy.when_required = "external_only"

    # Ruoli richiesti: lista di ID interi
    raw_roles = request.POST.getlist("required_role_ids")
    try:
        policy.required_role_ids = [int(r) for r in raw_roles if str(r).isdigit()]
    except (ValueError, TypeError):
        policy.required_role_ids = []

    # Reti interne: una per riga
    raw_nets = (request.POST.get("internal_networks") or "").strip()
    nets = [n.strip() for n in raw_nets.splitlines() if n.strip()]
    import ipaddress
    valid_nets = []
    invalid_nets = []
    for n in nets:
        try:
            ipaddress.ip_network(n, strict=False)
            valid_nets.append(n)
        except ValueError:
            invalid_nets.append(n)
    policy.internal_networks = valid_nets

    # Metodi ammessi
    methods = request.POST.getlist("allowed_methods")
    policy.allowed_methods = [m for m in methods if m in ("totp", "email")] or ["totp", "email"]

    try:
        policy.session_validity_seconds = max(300, int(request.POST.get("session_validity_seconds", 28800)))
    except (ValueError, TypeError):
        policy.session_validity_seconds = 28800

    policy.updated_by = request.user
    policy.save()

    _helpers._audit_safe(request, "twofa_policy_save", "twofa", {
        "enabled": policy.enabled,
        "when_required": policy.when_required,
        "required_role_ids": policy.required_role_ids,
        "allowed_methods": policy.allowed_methods,
    })

    if invalid_nets:
        messages.warning(request, f"CIDR non validi ignorati: {', '.join(invalid_nets)}")
    messages.success(request, "Configurazione 2FA salvata.")
    return redirect(reverse("admin_portale:twofa_config"))


def _notify_twofa_changed(target_user, message: str) -> None:
    from core.security_notify import notify_security_event

    notify_security_event(target_user, "Autenticazione a due fattori modificata", message)


def _twofa_target_forbidden(request, target_user) -> JsonResponse | None:
    """SEC (audit A1): il 2FA di un account privilegiato lo gestisce solo un superuser."""
    if _helpers._acting_is_superuser(request) or not _django_user_is_privileged(target_user):
        return None
    _helpers._audit_safe(request, "twofa_user_change_denied", "twofa", {
        "target_user": target_user.username,
        "path": request.path,
    })
    return JsonResponse(
        {"ok": False, "error": "Solo un superuser puo' modificare il 2FA di un amministratore."},
        status=403,
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_twofa_user_toggle(request: HttpRequest, user_id: int):
    """Attiva/disattiva il 2FA per un singolo utente."""
    from twofa.models import UserTwoFactor

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    forbidden = _twofa_target_forbidden(request, target_user)
    if forbidden is not None:
        return forbidden
    u2f, _ = UserTwoFactor.objects.get_or_create(user=target_user)
    u2f.is_active = not u2f.is_active
    u2f.save(update_fields=["is_active"])
    _helpers._audit_safe(request, "twofa_user_toggle", "twofa", {
        "target_user": target_user.username,
        "is_active": u2f.is_active,
    })
    stato = "attivato" if u2f.is_active else "disattivato"
    _notify_twofa_changed(target_user, f"L'autenticazione a due fattori del tuo account è stata {stato} da un amministratore.")
    return JsonResponse({"ok": True, "is_active": u2f.is_active, "msg": f"2FA {stato} per {target_user.username}."})


@legacy_admin_required
@csrf_protect
@require_POST
def api_twofa_user_reset(request: HttpRequest, user_id: int):
    """Resetta la configurazione 2FA (TOTP) per un utente: forza re-setup al prossimo accesso."""
    from twofa.models import UserTwoFactor, TwoFactorChallenge

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    forbidden = _twofa_target_forbidden(request, target_user)
    if forbidden is not None:
        return forbidden
    try:
        u2f = target_user.twofa
        u2f.totp_secret_enc = ""
        u2f.totp_confirmed = False
        u2f.force_setup = True
        u2f.save(update_fields=["totp_secret_enc", "totp_confirmed", "force_setup"])
    except UserTwoFactor.DoesNotExist:
        pass
    # Invalida challenge email attivi
    TwoFactorChallenge.objects.filter(user=target_user, used=False).update(used=True)
    _helpers._audit_safe(request, "twofa_user_reset", "twofa", {"target_user": target_user.username})
    _notify_twofa_changed(
        target_user,
        "Un amministratore ha reimpostato l'autenticazione a due fattori del tuo account: "
        "al prossimo accesso dovrai configurarla di nuovo.",
    )
    return JsonResponse({"ok": True, "msg": f"2FA reimpostato per {target_user.username}. Al prossimo accesso dovrà ri-configurarlo."})


@legacy_admin_required
@csrf_protect
@require_POST
def api_twofa_user_method_set(request: HttpRequest, user_id: int):
    """Imposta il metodo 2FA per un utente (totp / email)."""
    from twofa.models import UserTwoFactor

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    forbidden = _twofa_target_forbidden(request, target_user)
    if forbidden is not None:
        return forbidden
    method = (request.POST.get("method") or "").strip()
    if method not in ("totp", "email"):
        return JsonResponse({"ok": False, "error": "Metodo non valido."}, status=400)

    u2f, _ = UserTwoFactor.objects.get_or_create(user=target_user)
    if u2f.method != method:
        u2f.method = method
        # Cambio metodo → forza ri-setup
        u2f.totp_secret_enc = ""
        u2f.totp_confirmed = False
        u2f.force_setup = (method == "totp")
        u2f.save(update_fields=["method", "totp_secret_enc", "totp_confirmed", "force_setup"])
    _helpers._audit_safe(request, "twofa_user_method_set", "twofa", {
        "target_user": target_user.username,
        "method": method,
    })
    _notify_twofa_changed(target_user, f"Il metodo di verifica a due fattori del tuo account è stato impostato su «{method}» da un amministratore.")
    return JsonResponse({"ok": True, "msg": f"Metodo 2FA aggiornato a «{method}» per {target_user.username}."})


@legacy_admin_required
@csrf_protect
@require_POST
def api_twofa_user_email_set(request: HttpRequest, user_id: int):
    """Imposta o rimuove l'email override per OTP di un utente."""
    from twofa.models import UserTwoFactor
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    forbidden = _twofa_target_forbidden(request, target_user)
    if forbidden is not None:
        return forbidden
    email = (request.POST.get("email_override") or "").strip()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"ok": False, "error": "Email non valida."}, status=400)
    u2f, _ = UserTwoFactor.objects.get_or_create(user=target_user)
    u2f.email_override = email
    u2f.save(update_fields=["email_override"])
    _helpers._audit_safe(request, "twofa_user_email_set", "twofa", {"target_user": target_user.username, "email_override": email})
    _notify_twofa_changed(
        target_user,
        "L'indirizzo a cui arrivano i codici di verifica del tuo account è stato cambiato da un amministratore.",
    )
    return JsonResponse({"ok": True, "msg": "Email OTP aggiornata."})
