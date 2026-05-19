from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.audit import log_action

from .models import AiChatFeedback, AiKnowledgeEntry
from .services import OllamaChatError, chat_with_ollama, clear_knowledge_cache
from .tools import build_runtime_context


def _json_payload(request) -> dict:
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _can_manage_knowledge(request) -> bool:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_superuser", False)) or bool(getattr(user, "is_staff", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    request.legacy_user = legacy_user
    return bool(legacy_user and is_legacy_admin(legacy_user))


def _runtime_audit_summary(runtime_audit: dict | None) -> dict:
    audit = runtime_audit or {}
    tools = audit.get("tools") if isinstance(audit.get("tools"), list) else []
    base = {
        "runtime_context_chars": audit.get("context_chars") if isinstance(audit.get("context_chars"), int) else 0,
        "runtime_context_lines": audit.get("context_lines") if isinstance(audit.get("context_lines"), int) else 0,
        "runtime_context_truncated": bool(audit.get("truncated")),
    }
    if tools:
        return {
            **base,
            "runtime_tools": [
                str(item.get("tool") or "")
                for item in tools
                if isinstance(item, dict) and str(item.get("tool") or "").strip()
            ],
            "runtime_tools_allowed": [
                item.get("allowed")
                for item in tools
                if isinstance(item, dict) and "allowed" in item
            ],
            "runtime_tools_detail": [
                {
                    "tool": str(item.get("tool") or ""),
                    "allowed": item.get("allowed"),
                    "reason": str(item.get("reason") or ""),
                    "scope": item.get("scope"),
                    "row_count": item.get("row_count"),
                    "filters": item.get("filters"),
                }
                for item in tools
                if isinstance(item, dict) and str(item.get("tool") or "").strip()
            ],
        }
    return {
        **base,
        "runtime_tools": [str(audit.get("tool") or "")] if str(audit.get("tool") or "").strip() else [],
        "runtime_tools_allowed": [audit.get("allowed")] if "allowed" in audit else [],
        "runtime_tools_detail": [
            {
                "tool": str(audit.get("tool") or ""),
                "allowed": audit.get("allowed"),
                "reason": str(audit.get("reason") or ""),
                "scope": audit.get("scope"),
                "row_count": audit.get("row_count"),
                "filters": audit.get("filters"),
            }
        ]
        if str(audit.get("tool") or "").strip()
        else [],
    }


_SUGGESTED_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (
        ("assente", "assenz", "ferie", "permesso", "malattia"),
        [
            "Chi è assente questa settimana?",
            "Quanti giorni di ferie ho ancora?",
            "Mostrami le assenze di domani.",
        ],
    ),
    (
        ("ticket", "supporto", "richiesta", "problema", "guasto"),
        [
            "Quali ticket urgenti sono aperti?",
            "Mostrami i miei ticket in attesa.",
            "Quanti ticket ho aperto questo mese?",
        ],
    ),
    (
        ("task", "progetto", "scadenza", "ritardo", "kick-off", "kickoff"),
        [
            "Quali task sono in ritardo?",
            "Mostrami le scadenze della prossima settimana.",
            "Quali progetti sono attivi?",
        ],
    ),
    (
        ("asset", "attrezzatura", "manutenzione", "scadenza", "macchina"),
        [
            "Quali asset hanno manutenzione in scadenza?",
            "Mostrami gli asset assegnati a me.",
            "Ci sono attrezzature fuori servizio?",
        ],
    ),
    (
        ("dpi", "dispositivo", "protezione", "elmetto", "guanti", "scarpe"),
        [
            "Ho DPI in scadenza?",
            "Quando è prevista la prossima consegna DPI?",
            "Quali DPI devo ancora ricevere?",
        ],
    ),
    (
        ("anomalia", "segnalazione", "incidente", "sicurezza", "rischio"),
        [
            "Ci sono anomalie aperte nel mio reparto?",
            "Mostrami le segnalazioni urgenti.",
            "Quali anomalie sono state risolte di recente?",
        ],
    ),
    (
        ("procedura", "formazione", "quiz", "corso", "lettura"),
        [
            "Ho procedure da leggere?",
            "Quali quiz di formazione devo completare?",
            "Mostrami le campagne formative attive.",
        ],
    ),
    (
        ("modulo", "funzione", "accesso", "portale", "sezione"),
        [
            "Cosa posso fare oggi?",
            "Quali moduli posso usare?",
            "Dove trovo le notizie aziendali?",
        ],
    ),
]

_FALLBACK_SUGGESTIONS = [
    "Cosa devo fare oggi?",
    "Chi è assente questa settimana?",
    "Quali ticket urgenti sono aperti?",
]


def _build_suggested_questions(user_message: str, assistant_reply: str) -> list[str]:
    combined = (user_message + " " + assistant_reply).lower()
    for keywords, questions in _SUGGESTED_RULES:
        if any(kw in combined for kw in keywords):
            return questions[:3]
    return _FALLBACK_SUGGESTIONS


@login_required
def chat_page(request):
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip()
    base_url_host = urlsplit(base_url).netloc if base_url else ""
    context = {
        "page_title": "Assistente AI",
        "ollama_enabled": bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)),
        "ollama_base_url": base_url,
        "ollama_base_url_host": base_url_host,
        "ollama_provider": str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower(),
        "ollama_model": str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip(),
        "ollama_timeout": int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60),
        "max_prompt_chars": int(getattr(settings, "OLLAMA_CHAT_MAX_PROMPT_CHARS", 4000) or 4000),
        "can_manage_knowledge": _can_manage_knowledge(request),
    }
    return render(request, "ai_assistant/chat.html", context)


@require_POST
@login_required
def api_chat(request):
    if not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        return JsonResponse(
            {"ok": False, "error": "Assistente AI disabilitato in configurazione."},
            status=503,
        )

    payload = _json_payload(request)
    message = str(payload.get("message") or "").strip()
    history = payload.get("history")
    if not message:
        return JsonResponse({"ok": False, "error": "Scrivi un messaggio prima di inviare."}, status=400)

    started = time.monotonic()
    runtime_context = build_runtime_context(request, message, history=history)
    try:
        result = chat_with_ollama(message, history=history, runtime_context=runtime_context.text)
    except OllamaChatError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        runtime_audit = _runtime_audit_summary(runtime_context.audit)
        log_action(
            request,
            "ai_chat_error",
            "ai_assistant",
            {
                "model": str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip(),
                "provider": str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower(),
                "base_url_host": urlsplit(str(getattr(settings, "OLLAMA_BASE_URL", "") or "")).netloc,
                "prompt_chars": len(message),
                "elapsed_ms": elapsed_ms,
                "error_type": exc.__class__.__name__,
                **runtime_audit,
            },
        )
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    runtime_audit = _runtime_audit_summary(runtime_context.audit)
    log_action(
        request,
        "ai_chat",
        "ai_assistant",
            {
                "model": result.model,
                "prompt_chars": len(message),
                "response_chars": len(result.content),
                "rag_sources_count": len(result.sources),
                "runtime_sources_count": len(runtime_context.sources),
                "rag_context_chars": result.rag_context_chars,
                "elapsed_ms": elapsed_ms,
                **runtime_audit,
            },
        )
    sources = list(result.sources)
    for source in runtime_context.sources:
        if source not in sources:
            sources.append(source)

    suggested_questions = _build_suggested_questions(message, result.content)

    return JsonResponse(
        {
            "ok": True,
            "message": result.content,
            "model": result.model,
            "elapsed_ms": elapsed_ms,
            "sources": sources,
            "suggested_questions": suggested_questions,
        }
    )


@require_POST
@login_required
def api_save_knowledge(request):
    if not _can_manage_knowledge(request):
        return JsonResponse(
            {"ok": False, "error": "Permessi insufficienti per salvare conoscenza AI."},
            status=403,
        )

    payload = _json_payload(request)
    question = str(payload.get("question") or "").replace("\x00", "").strip()
    answer = str(payload.get("answer") or "").replace("\x00", "").strip()
    source_label = str(payload.get("source_label") or "FAQ Portale").replace("\x00", "").strip()[:120]
    if not question or not answer:
        return JsonResponse({"ok": False, "error": "Domanda e risposta sono obbligatorie."}, status=400)
    if len(question) > 500:
        question = question[:500].rstrip()
    if len(answer) > 6000:
        answer = answer[:6000].rstrip()

    entry = AiKnowledgeEntry.objects.create(
        question=question,
        answer=answer,
        source_label=source_label or "FAQ Portale",
        is_active=True,
        created_by=request.user,
        updated_by=request.user,
    )
    clear_knowledge_cache()
    log_action(
        request,
        "ai_knowledge_save",
        "ai_assistant",
        {
            "entry_id": entry.id,
            "question_chars": len(question),
            "answer_chars": len(answer),
            "source_label": entry.source_label,
        },
    )
    return JsonResponse({"ok": True, "entry_id": entry.id, "message": "Conoscenza salvata nella FAQ AI."})


@require_POST
@login_required
def api_feedback(request):
    """Salva il feedback thumbs up/down su una risposta AI.

    Payload JSON: {"prompt": "...", "response": "...", "rating": "up"|"down", "correction": "..."}
    Se rating == "down" e correction non vuoto, crea anche una AiKnowledgeEntry bozza (is_active=False).
    """
    payload = _json_payload(request)
    prompt = str(payload.get("prompt") or "").replace("\x00", "").strip()
    response_text = str(payload.get("response") or "").replace("\x00", "").strip()
    rating = str(payload.get("rating") or "").strip().lower()
    correction = str(payload.get("correction") or "").replace("\x00", "").strip()

    if not prompt or not response_text:
        return JsonResponse({"ok": False, "error": "Prompt e risposta sono obbligatori."}, status=400)
    if rating not in {"up", "down"}:
        return JsonResponse({"ok": False, "error": "Rating non valido. Usa 'up' o 'down'."}, status=400)

    # Tronca ai limiti definiti nel modello
    prompt = prompt[:500]
    response_text = response_text[:2000]
    correction = correction[:6000]

    knowledge_entry = None
    if rating == "down" and correction:
        knowledge_entry = AiKnowledgeEntry.objects.create(
            question=prompt,
            answer=correction,
            source_label="Feedback chat",
            is_active=False,  # bozza — richiede approvazione admin
            created_by=request.user,
            updated_by=request.user,
        )

    feedback = AiChatFeedback.objects.create(
        user=request.user if request.user.is_authenticated else None,
        prompt=prompt,
        response=response_text,
        rating=rating,
        correction=correction,
        source_label="Feedback chat",
        is_reviewed=False,
        knowledge_entry=knowledge_entry,
    )

    log_action(
        request,
        "ai_feedback",
        "ai_assistant",
        {
            "feedback_id": feedback.id,
            "rating": rating,
            "has_correction": bool(correction),
            "knowledge_entry_id": knowledge_entry.id if knowledge_entry else None,
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "message": "Grazie per il feedback.",
            "feedback_id": feedback.id,
        }
    )
