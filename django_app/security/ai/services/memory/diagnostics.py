"""Diagnostics for AI memory retrieval backends."""

from django.conf import settings
from django.db import connection

from ....models import AIKnowledgeChunk, AIKnowledgeEmbedding
from .vector_backend import (
    pgvector_backend_available,
    pgvector_column_available,
    pgvector_extension_enabled,
    pgvector_package_installed,
)
from .evaluation import build_evaluation_diagnostics_summary


def get_ai_memory_diagnostics() -> dict:
    chunks_total = AIKnowledgeChunk.objects.count()
    embeddings_total = AIKnowledgeEmbedding.objects.count()
    return {
        "pgvector_package_installed": pgvector_package_installed(),
        "database_vendor": connection.vendor,
        "pgvector_extension_enabled": pgvector_extension_enabled(),
        "pgvector_column_available": pgvector_column_available(),
        "pgvector_available": pgvector_backend_available(),
        "retrieval_mode": getattr(settings, "AI_MEMORY_RETRIEVAL_MODE", "hybrid_keyword"),
        "embeddings_enabled": bool(getattr(settings, "AI_MEMORY_EMBEDDINGS_ENABLED", False)),
        "chunks_with_embeddings": embeddings_total,
        "chunks_without_embeddings": max(0, chunks_total - embeddings_total),
        "chunks_total": chunks_total,
        "quality_evaluation": build_evaluation_diagnostics_summary(),
    }


def ai_memory_diagnostic_check() -> dict:
    diagnostics = get_ai_memory_diagnostics()
    mode = str(diagnostics["retrieval_mode"])
    if mode in {"pgvector", "hybrid_pgvector"} and not diagnostics["pgvector_available"]:
        return {
            "code": "ai_memory_retrieval",
            "label": "AI Memory retrieval",
            "status": "warning",
            "message": "pgvector non disponibile; fallback keyword/JSON cosine attivo dove possibile.",
            "details": diagnostics,
            "suggested_action": "Verifica pgvector solo se la modalita di retrieval configurata lo richiede.",
        }
    return {
        "code": "ai_memory_retrieval",
        "label": "AI Memory retrieval",
        "status": "ok",
        "message": f"Modalita retrieval effettiva configurata: {mode}.",
        "details": diagnostics,
        "suggested_action": "",
    }
