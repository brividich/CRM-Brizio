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
