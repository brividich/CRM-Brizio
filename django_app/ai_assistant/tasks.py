"""Task periodici django-q2 per il modulo ai_assistant.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_warmup_ollama(timeout: int | None = None) -> dict:
    """Pre-carica il modello chat Ollama per azzerare il cold start.

    Wrappa ``services.warmup_ollama()``. **Fail-safe**: non solleva mai, così il
    cluster django-q non va in errore se Ollama è giù. Va schedulato a intervalli
    inferiori al ``keep_alive`` del modello (default 30m): ogni run rinnova il
    timer keep_alive, quindi il modello resta caldo in memoria e la prima
    richiesta utente non paga il caricamento (causa principale dei timeout
    «Timeout dopo Ns»). Con provider Open WebUI è un no-op (esito ``skipped``).
    """
    from ai_assistant.services import warmup_ollama

    try:
        result = warmup_ollama(timeout=timeout)
        if not result.get("ok") and not result.get("skipped"):
            logger.warning("warmup_ollama non riuscito: %s", result.get("message"))
        return result
    except Exception:
        logger.exception("run_warmup_ollama: errore inatteso")
        return {"ok": False, "skipped": False, "loaded": False, "message": "errore inatteso"}


def run_index_sgi_documents() -> dict:
    """Indicizza/scalda il corpus documentale SGI nel RAG dell'assistente.

    Wrappa ``services.index_sgi_documents()``. **Fail-safe**: non solleva mai, così
    il cluster django-q non va in errore se Ollama/embeddings sono giù. La prima
    build è la più costosa (estrazione PDF + embedding); poi è in cache per
    ``file_hash``/content-hash. Schedulalo a bassa frequenza (es. notturna) per
    evitare che sia la prima chat della giornata a pagare la ricostruzione.
    """
    from ai_assistant.services import index_sgi_documents

    try:
        result = index_sgi_documents()
        if not result.get("ok") and not result.get("skipped"):
            logger.warning("index_sgi_documents non riuscito: %s", result.get("message"))
        return result
    except Exception:
        logger.exception("run_index_sgi_documents: errore inatteso")
        return {"ok": False, "skipped": False, "message": "errore inatteso"}


_RAG_QUALITY_STATE_KEY = "monitoring:rag-quality:fingerprint"


def run_rag_quality_alert() -> dict:
    """Valuta la QUALITÀ del RAG SGI (``ai_eval --rag-sgi``) e allerta gli admin se
    l'indice è vuoto (``sgi_chunks=0``) o la recall scende sotto soglia.

    Complementare a ``monitoring.run_ai_readiness_alert`` (che verifica la *liveness*
    di Ollama/TEI): qui si misura se il RAG *risponde bene*. Riusa l'intera logica di
    ``ai_eval`` via ``call_command`` (nessuna duplicazione) e l'invio email del
    monitoring (rate-limited, solo al cambio stato). **Fail-safe**: non solleva mai.
    Schedulalo dopo il warm dell'indice (es. notte), a bassa frequenza (l'eval
    ricostruisce l'indice). Soglia: ``OLLAMA_RAG_SGI_MIN_RECALL`` (default 0.7).
    """
    import io
    import json

    from django.conf import settings
    from django.core.cache import cache
    from django.core.management import call_command

    result: dict = {"degraded": False, "emailed": False}
    summary: dict = {}
    try:
        buffer = io.StringIO()
        call_command("ai_eval", "--rag-sgi", "--json", stdout=buffer)
        summary = (json.loads(buffer.getvalue() or "{}") or {}).get("summary", {}) or {}
    except Exception as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        logger.exception("run_rag_quality_alert: ai_eval fallito")

    sgi_chunks = int(summary.get("sgi_chunks") or 0)
    cases = int(summary.get("cases") or 0)
    recall_hits = summary.get("recall_hits")
    recall_pct = (recall_hits / cases) if (isinstance(recall_hits, (int, float)) and cases) else None
    min_recall = float(getattr(settings, "OLLAMA_RAG_SGI_MIN_RECALL", 0.7) or 0.0)
    result.update({"sgi_chunks": sgi_chunks, "recall_hits": recall_hits,
                   "cases": cases, "recall_pct": recall_pct})

    problems: list[str] = []
    if "error" in result:
        problems.append(f"ai_eval --rag-sgi non eseguibile: {result['error']}")
    elif sgi_chunks == 0:
        problems.append("Indice SGI vuoto (sgi_chunks=0): nessun documento citabile dall'AI.")
    elif recall_pct is not None and recall_pct < min_recall:
        problems.append(
            f"Recall RAG-SGI {recall_pct:.0%} sotto soglia {min_recall:.0%} "
            f"({recall_hits}/{cases} golden)."
        )

    result["degraded"] = bool(problems)
    if not problems:
        cache.delete(_RAG_QUALITY_STATE_KEY)
        return result

    try:
        from monitoring.health import emit_monitoring_alert

        env_label = getattr(settings, "MONITORING_ENVIRONMENT", "") or ""
        subject = "[RAG WARN] Qualità RAG SGI degradata" + (f" — {env_label}" if env_label else "")
        body = "\n".join(
            ["Problemi rilevati dalla valutazione RAG-SGI:", ""]
            + [f"- {p}" for p in problems]
            + ["", f"sgi_chunks={sgi_chunks}, recall={recall_hits}/{cases}.",
               "Alert generato da run_rag_quality_alert (rate-limited, solo al cambio stato)."]
        )
        result["emailed"] = emit_monitoring_alert(
            subject=subject, body=body, fingerprint=";".join(problems),
            state_key=_RAG_QUALITY_STATE_KEY,
        )
    except Exception:
        logger.exception("run_rag_quality_alert: invio alert fallito")
    return result
