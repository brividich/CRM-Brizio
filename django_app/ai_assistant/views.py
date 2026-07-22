from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acl_v2 import request_has_permission_code
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.audit import log_action

from .acl_bootstrap import PERM_KNOWLEDGE_MANAGE

from .models import AiChatFeedback, AiKnowledgeEntry
from .services import (
    OllamaChatError,
    chat_with_ollama,
    clear_knowledge_cache,
    iter_ollama_stream,
    open_ollama_stream,
    sgi_rag_access,
)
from .tools import build_runtime_context


def _json_payload(request) -> dict:
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _check_rate_limit(request) -> tuple[bool, int]:
    """Throttle per-utente a finestra fissa basato sulla cache.

    Ritorna ``(allowed, retry_after_seconds)``. Fail-open: se la cache non e'
    disponibile non blocca mai la richiesta. ``OLLAMA_CHAT_RATE_LIMIT=0``
    disabilita il throttle.
    """
    limit = int(getattr(settings, "OLLAMA_CHAT_RATE_LIMIT", 20) or 0)
    window = int(getattr(settings, "OLLAMA_CHAT_RATE_WINDOW_SECONDS", 60) or 60)
    if limit <= 0 or window <= 0:
        return True, 0
    user_id = getattr(getattr(request, "user", None), "id", None) or "anon"
    now = int(time.time())
    key = f"ai_chat_rate:{user_id}:{now // window}"
    try:
        if cache.add(key, 1, timeout=window):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=window)
                count = 1
    except Exception:
        # Cache non raggiungibile: non penalizzare l'utente.
        return True, 0
    if count > limit:
        retry_after = window - (now % window)
        return False, max(1, retry_after)
    return True, 0


def _rate_limited_response(retry_after: int) -> JsonResponse:
    response = JsonResponse(
        {
            "ok": False,
            "error": "Troppe richieste all'assistente AI. Attendi qualche secondo e riprova.",
        },
        status=429,
    )
    response["Retry-After"] = str(int(retry_after))
    return response


def _can_manage_knowledge(request) -> bool:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_superuser", False)) or bool(getattr(user, "is_staff", False)):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    request.legacy_user = legacy_user
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    # ACL v2 canonico: concedibile per ruolo da /admin-portale/acl-canonico/.
    return request_has_permission_code(request, PERM_KNOWLEDGE_MANAGE)


def _runtime_audit_summary(runtime_audit: dict | None) -> dict:
    audit = runtime_audit or {}
    tools = audit.get("tools") if isinstance(audit.get("tools"), list) else []
    routing = audit.get("routing") if isinstance(audit.get("routing"), dict) else {}
    base = {
        "runtime_context_chars": audit.get("context_chars") if isinstance(audit.get("context_chars"), int) else 0,
        "runtime_context_lines": audit.get("context_lines") if isinstance(audit.get("context_lines"), int) else 0,
        "runtime_context_truncated": bool(audit.get("truncated")),
        "runtime_routing_enabled": bool(routing.get("enabled")),
        "runtime_routing_active": routing.get("active") if isinstance(routing.get("active"), list) else [],
        "runtime_routing_scores": routing.get("scores") if isinstance(routing.get("scores"), dict) else {},
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


def _clean_chat_preferences(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, object] = {}
    style = str(raw.get("style") or "").replace("\x00", "").strip().lower()
    if style in {"operativo", "sintetico", "dettagliato"}:
        cleaned["style"] = style
    cleaned["show_limits"] = bool(raw.get("show_limits"))
    return cleaned


_SUGGESTED_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (
        ("ferie residue", "ratei", "rol resid", "permessi resid", "ex fest"),
        [
            "Quali sono i primi 5 dipendenti per ferie residue?",
            "Quante ore ferie residue ha un dipendente?",
            "Mostra i ROL residui piu' alti.",
        ],
    ),
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

    allowed, retry_after = _check_rate_limit(request)
    if not allowed:
        return _rate_limited_response(retry_after)

    payload = _json_payload(request)
    message = str(payload.get("message") or "").strip()
    history = payload.get("history")
    preferences = _clean_chat_preferences(payload.get("preferences"))
    if not message:
        return JsonResponse({"ok": False, "error": "Scrivi un messaggio prima di inviare."}, status=400)

    started = time.monotonic()
    runtime_context = build_runtime_context(request, message, history=history)
    allow_specifiche, allow_procedure = sgi_rag_access(request)
    try:
        result = chat_with_ollama(
            message,
            history=history,
            runtime_context=runtime_context.text,
            user_preferences=preferences,
            allow_specifiche=allow_specifiche,
            allow_procedure=allow_procedure,
        )
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
                "ai_preferences": sorted(preferences.keys()),
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


def _ndjson(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


@require_POST
@login_required
def api_chat_stream(request):
    """Variante streaming di ``api_chat``: emette NDJSON con eventi incrementali.

    Eventi (uno per riga):
      {"type": "delta", "text": "..."}              token incrementale
      {"type": "done",  "model", "elapsed_ms", ...} chiusura con metadati
      {"type": "error", "error": "..."}             errore prima di ogni token

    Il setup (ACL/contesto live, validazione, apertura connessione) avviene in
    modo sincrono: errori di setup tornano come JSON con status HTTP corretto,
    cosi' il frontend puo' ripiegare sull'endpoint non-streaming.
    """
    if not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        return JsonResponse(
            {"ok": False, "error": "Assistente AI disabilitato in configurazione."},
            status=503,
        )

    allowed, retry_after = _check_rate_limit(request)
    if not allowed:
        return _rate_limited_response(retry_after)

    payload = _json_payload(request)
    message = str(payload.get("message") or "").strip()
    history = payload.get("history")
    preferences = _clean_chat_preferences(payload.get("preferences"))
    if not message:
        return JsonResponse({"ok": False, "error": "Scrivi un messaggio prima di inviare."}, status=400)

    started = time.monotonic()
    runtime_context = build_runtime_context(request, message, history=history)
    runtime_audit = _runtime_audit_summary(runtime_context.audit)
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    allow_specifiche, allow_procedure = sgi_rag_access(request)

    try:
        stream, meta = open_ollama_stream(
            message,
            history=history,
            runtime_context=runtime_context.text,
            user_preferences=preferences,
            allow_specifiche=allow_specifiche,
            allow_procedure=allow_procedure,
        )
    except OllamaChatError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        log_action(
            request,
            "ai_chat_error",
            "ai_assistant",
            {
                "model": model,
                "provider": str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower(),
                "base_url_host": urlsplit(str(getattr(settings, "OLLAMA_BASE_URL", "") or "")).netloc,
                "prompt_chars": len(message),
                "elapsed_ms": elapsed_ms,
                "error_type": exc.__class__.__name__,
                "streamed": True,
                **runtime_audit,
            },
        )
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    sources = list(meta.get("sources") or ())
    for source in runtime_context.sources:
        if source not in sources:
            sources.append(source)

    def event_stream():
        chunks: list[str] = []
        stream_error = ""
        error_type = ""
        try:
            for piece in iter_ollama_stream(stream, meta.get("provider", "ollama")):
                chunks.append(piece)
                yield _ndjson({"type": "delta", "text": piece})
        except OllamaChatError as exc:
            # Messaggio funzionale pensato per l'utente/admin (no internals).
            stream_error = str(exc) or "Errore durante lo streaming della risposta."
            error_type = "OllamaChatError"
        except Exception as exc:  # noqa: BLE001 — non esporre dettagli interni al client
            stream_error = "Errore durante lo streaming della risposta."
            error_type = exc.__class__.__name__

        full_text = "".join(chunks).strip()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if stream_error and not full_text:
            log_action(
                request,
                "ai_chat_error",
                "ai_assistant",
                {
                    "model": meta.get("model") or model,
                    "prompt_chars": len(message),
                    "elapsed_ms": elapsed_ms,
                    "error_type": error_type or "StreamError",
                    "streamed": True,
                    **runtime_audit,
                },
            )
            yield _ndjson({"type": "error", "error": stream_error})
            return

        log_action(
            request,
            "ai_chat",
            "ai_assistant",
            {
                "model": meta.get("model") or model,
                "prompt_chars": len(message),
                "response_chars": len(full_text),
                "rag_sources_count": len(meta.get("sources") or ()),
                "runtime_sources_count": len(runtime_context.sources),
                "rag_context_chars": meta.get("rag_context_chars") or 0,
                "ai_preferences": sorted(preferences.keys()),
                "elapsed_ms": elapsed_ms,
                "streamed": True,
                "stream_partial_error": bool(stream_error),
                **runtime_audit,
            },
        )

        done_event = {
            "type": "done",
            "model": meta.get("model") or model,
            "elapsed_ms": elapsed_ms,
            "sources": sources,
            "suggested_questions": _build_suggested_questions(message, full_text),
        }
        if stream_error:
            done_event["partial_error"] = stream_error
        yield _ndjson(done_event)

    response = StreamingHttpResponse(event_stream(), content_type="application/x-ndjson; charset=utf-8")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response


_DAILY_BRIEF_QUERY = (
    "cosa devo fare oggi? riepilogo personale delle mie attivita', scadenze e "
    "cose da gestire di oggi nei moduli a cui ho accesso"
)
_DAILY_BRIEF_PROMPT = (
    "Prepara il mio brief operativo personale di oggi basandoti ESCLUSIVAMENTE sul "
    "contesto live. Elenca in massimo 6 punti, dal piu' importante, le cose che devo "
    "gestire o sapere oggi (scadenze imminenti, attivita' o task in ritardo, ticket "
    "urgenti, procedure o notizie da leggere/confermare, DPI o ferie rilevanti). "
    "Una riga per punto, tono diretto e operativo, in italiano. Non inventare voci "
    "non presenti nel contesto. Se non c'e' nulla di rilevante, dillo in una riga."
)


def _seconds_until_end_of_day() -> int:
    now = timezone.localtime()
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return max(60, int((end - now).total_seconds()))


@login_required
def api_daily_brief(request):
    """Brief operativo personale del giorno, generato dall'AI sui dati live ACL-filtrati.

    On-demand con cache per-utente/per-giorno (si genera alla prima apertura,
    poi servito dalla cache). ``?refresh=1`` forza la rigenerazione (con throttle).
    Fail-safe: se il modello non risponde, mostra comunque gli item grezzi.
    """
    if not bool(getattr(settings, "OLLAMA_DAILY_BRIEF_ENABLED", True)) or not bool(
        getattr(settings, "OLLAMA_CHAT_ENABLED", True)
    ):
        return JsonResponse({"ok": False, "error": "Brief AI non disponibile."}, status=503)

    user_id = getattr(request.user, "id", None) or "anon"
    today = timezone.localdate().isoformat()
    cache_key = f"ai_daily_brief:{user_id}:{today}"
    force = request.GET.get("refresh") == "1"

    if not force:
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if isinstance(cached, dict) and cached.get("message"):
            return JsonResponse({"ok": True, "cached": True, **cached})
    else:
        allowed, retry_after = _check_rate_limit(request)
        if not allowed:
            return _rate_limited_response(retry_after)

    started = time.monotonic()
    runtime_context = build_runtime_context(request, _DAILY_BRIEF_QUERY)
    has_context = bool(runtime_context.text.strip())

    model = ""
    if not has_context:
        message = "Per oggi non risultano attivita' o scadenze rilevanti da gestire nei tuoi moduli."
    else:
        try:
            result = chat_with_ollama(
                _DAILY_BRIEF_PROMPT,
                runtime_context=runtime_context.text,
                user_preferences={"style": "sintetico", "show_limits": True},
                # Timeout dedicato piu' corto: il brief non e' critico e non deve
                # tenere occupato un worker per l'intero OLLAMA_REQUEST_TIMEOUT_SECONDS.
                timeout=int(getattr(settings, "OLLAMA_DAILY_BRIEF_TIMEOUT_SECONDS", 45) or 45),
            )
            message = result.content
            model = result.model
        except OllamaChatError:
            # Fail-safe: niente AI ma mostriamo comunque le fonti/segnali grezzi.
            message = (
                "Servizio AI non disponibile al momento. Apri «Mie attivita'» nel "
                "portale per il riepilogo completo delle cose da gestire."
            )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    data = {
        "message": message,
        "model": model,
        "generated_at": timezone.localtime().strftime("%H:%M"),
        "sources": list(runtime_context.sources),
    }
    try:
        cache.set(cache_key, data, timeout=_seconds_until_end_of_day())
    except Exception:
        pass

    log_action(
        request,
        "ai_daily_brief",
        "ai_assistant",
        {
            "model": model,
            "response_chars": len(message),
            "elapsed_ms": elapsed_ms,
            "forced": force,
            "had_context": has_context,
            **_runtime_audit_summary(runtime_context.audit),
        },
    )
    return JsonResponse({"ok": True, "cached": False, **data})


@require_POST
@login_required
def api_genera_report(request):
    """Genera un report PDF su un argomento, ancorato al contesto live ACL-gated.

    Read-only: i dati vengono dai tool live (ACL dell'utente) e dal RAG; l'AI scrive
    solo la prosa, cita le fonti e non inventa. PDF marcato come bozza (umano firma).
    Audit solo-metadati. Fail-safe: AI giu' -> 502, niente PDF.
    """
    if not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        return JsonResponse({"ok": False, "error": "Assistente AI disabilitato in configurazione."}, status=503)

    allowed, retry_after = _check_rate_limit(request)
    if not allowed:
        return _rate_limited_response(retry_after)

    payload = _json_payload(request)
    topic = str(payload.get("topic") or "").replace("\x00", "").strip()
    if not topic:
        return JsonResponse({"ok": False, "error": "Indica l'argomento del report."}, status=400)

    started = time.monotonic()
    from .ai_report import genera_report, render_report_pdf

    report = genera_report(request, topic)
    if not report["ai_disponibile"] and not report["markdown"]:
        return JsonResponse(
            {"ok": False, "error": "Servizio AI non disponibile per generare il report. Riprova piu' tardi."},
            status=502,
        )

    autore = (request.user.get_full_name() or request.user.get_username() or "").strip()
    try:
        pdf_bytes = render_report_pdf(report, autore=autore)
    except Exception:  # noqa: BLE001 — reportlab assente/errore di rendering
        return JsonResponse({"ok": False, "error": "Generazione del PDF non disponibile."}, status=503)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    log_action(
        request,
        "ai_report",
        "ai_assistant",
        {
            "model": report.get("model"),
            "topic_chars": len(topic),
            "report_chars": len(report.get("markdown") or ""),
            "sources_count": len(report.get("fonti") or []),
            "had_context": report.get("has_context"),
            "format": "pdf",
            "elapsed_ms": elapsed_ms,
            **_runtime_audit_summary(report.get("runtime_audit")),
        },
    )

    filename = f"report-ai-{timezone.localdate().strftime('%Y%m%d')}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Length"] = str(len(pdf_bytes))
    return response


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
