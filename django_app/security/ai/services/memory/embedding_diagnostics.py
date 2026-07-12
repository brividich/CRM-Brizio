"""Backend diagnostics helpers for AI memory embeddings.

This module provides diagnostic functions for embedding providers, database state,
and configuration without exposing sensitive data or API keys. Functions are designed
to be used by management commands, tests, and diagnostic endpoints.

Security considerations:
- Never logs or returns raw chunk text
- Never logs or returns raw embedding vectors
- Never exposes API keys or secrets
- Truncates error messages to avoid leaking sensitive information
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import connection
from django.db.models import Count

from ....models import AIKnowledgeChunk, AIKnowledgeEmbedding
from .embedding_provider import get_embedding_provider
from .vector_backend import pgvector_backend_available


def get_active_embedding_provider() -> dict[str, Any]:
    """Get information about the active embedding provider configuration.

    Returns:
        dict: Provider information including name, model, dimensions, and status.
              Never includes API keys or secrets.

    Example:
        {
            "provider_name": "deterministic_hash",
            "model_name": "hash-bow-384",
            "dimensions": 384,
            "configured": True,
            "type": "deterministic"
        }
    """
    try:
        provider = get_embedding_provider()
        return {
            "provider_name": provider.provider_name,
            "model_name": provider.model_name,
            "dimensions": provider.dimensions,
            "configured": True,
            "type": "deterministic" if provider.provider_name == "deterministic_hash" else "ai_provider",
        }
    except Exception as exc:
        # Truncate error to avoid leaking sensitive information
        error_msg = str(exc)[:200] if exc else "Unknown error"
        return {
            "provider_name": "unknown",
            "model_name": "unknown",
            "dimensions": 0,
            "configured": False,
            "type": "unknown",
            "error": error_msg,
        }


def is_embedding_provider_configured() -> bool:
    """Check if an embedding provider is properly configured.

    Returns:
        bool: True if a provider can be instantiated without errors.
    """
    try:
        provider = get_embedding_provider()
        return provider is not None and provider.dimensions > 0
    except Exception:
        return False


def are_embeddings_enabled() -> bool:
    """Check if embeddings are enabled in the configuration.

    Returns:
        bool: True if AI_MEMORY_EMBEDDINGS_ENABLED is True.
    """
    return bool(getattr(settings, "AI_MEMORY_EMBEDDINGS_ENABLED", False))


def get_chunks_with_embeddings_count() -> int:
    """Get the count of chunks that have embeddings stored.

    Returns:
        int: Number of chunks with embeddings.
    """
    try:
        return AIKnowledgeEmbedding.objects.count()
    except Exception:
        return 0


def get_chunks_without_embeddings_count() -> int:
    """Get the count of chunks that do not have embeddings stored.

    Returns:
        int: Number of chunks without embeddings.
    """
    try:
        chunks_total = AIKnowledgeChunk.objects.count()
        embeddings_total = AIKnowledgeEmbedding.objects.count()
        return max(0, chunks_total - embeddings_total)
    except Exception:
        return 0


def get_embedding_provider_distribution() -> dict[str, Any]:
    """Get distribution statistics of embeddings by provider, model, and dimensions.

    Returns:
        dict: Distribution statistics including counts by provider, model, and dimensions.
              Never includes raw embeddings or chunk text.

    Example:
        {
            "total_embeddings": 150,
            "by_provider": {"deterministic_hash": 150},
            "by_model": {"hash-bow-384": 150},
            "by_dimensions": {384: 150},
            "unique_providers": 1,
            "unique_models": 1,
            "unique_dimensions": 1
        }
    """
    try:
        total = AIKnowledgeEmbedding.objects.count()

        # Count by provider
        by_provider = {}
        for row in AIKnowledgeEmbedding.objects.values("provider").annotate(count=Count("id")):
            by_provider[row["provider"]] = row["count"]

        # Count by model
        by_model = {}
        for row in AIKnowledgeEmbedding.objects.values("model_name").annotate(count=Count("id")):
            by_model[row["model_name"] or "default"] = row["count"]

        # Count by dimensions
        by_dimensions = {}
        for row in AIKnowledgeEmbedding.objects.values("dimensions").annotate(count=Count("id")):
            by_dimensions[row["dimensions"]] = row["count"]

        return {
            "total_embeddings": total,
            "by_provider": by_provider,
            "by_model": by_model,
            "by_dimensions": by_dimensions,
            "unique_providers": len(by_provider),
            "unique_models": len(by_model),
            "unique_dimensions": len(by_dimensions),
        }
    except Exception as exc:
        # Truncate error to avoid leaking sensitive information
        error_msg = str(exc)[:200] if exc else "Unknown error"
        return {
            "total_embeddings": 0,
            "by_provider": {},
            "by_model": {},
            "by_dimensions": {},
            "unique_providers": 0,
            "unique_models": 0,
            "unique_dimensions": 0,
            "error": error_msg,
        }


def is_pgvector_available() -> bool:
    """Check if pgvector backend is available for vector operations.

    Returns:
        bool: True if pgvector package, extension, and column are all available.
    """
    try:
        return pgvector_backend_available()
    except Exception:
        return False


def is_fallback_active() -> bool:
    """Check if fallback mode is active for embeddings.

    Fallback is active when:
    - pgvector is not available but retrieval mode requires it, OR
    - embeddings are disabled but retrieval mode requires them

    Returns:
        bool: True if fallback mode is active.
    """
    try:
        retrieval_mode = str(getattr(settings, "AI_MEMORY_RETRIEVAL_MODE", "hybrid_keyword"))
        embeddings_enabled = are_embeddings_enabled()
        pgvector_available = is_pgvector_available()

        # Check if retrieval mode requires pgvector but it's not available
        requires_pgvector = retrieval_mode in {"pgvector", "hybrid_pgvector"}
        pgvector_fallback = requires_pgvector and not pgvector_available

        # Check if retrieval mode requires embeddings but they're disabled
        requires_embeddings = retrieval_mode in {"pgvector", "hybrid_pgvector", "hybrid_keyword"}
        embeddings_fallback = requires_embeddings and not embeddings_enabled

        return pgvector_fallback or embeddings_fallback
    except Exception:
        return False


def get_embedding_diagnostics_summary() -> dict[str, Any]:
    """Get a comprehensive summary of embedding diagnostics.

    This is a convenience function that aggregates all diagnostic information
    into a single summary dict.

    Returns:
        dict: Comprehensive diagnostics summary.

    Example:
        {
            "provider": {...},
            "configuration": {
                "provider_configured": True,
                "embeddings_enabled": True,
                "fallback_active": False
            },
            "database": {
                "chunks_with_embeddings": 150,
                "chunks_without_embeddings": 10,
                "total_chunks": 160
            },
            "distribution": {...},
            "pgvector": {
                "available": False,
                "database_vendor": "sqlite"
            }
        }
    """
    chunks_with = get_chunks_with_embeddings_count()
    chunks_without = get_chunks_without_embeddings_count()

    return {
        "provider": get_active_embedding_provider(),
        "configuration": {
            "provider_configured": is_embedding_provider_configured(),
            "embeddings_enabled": are_embeddings_enabled(),
            "fallback_active": is_fallback_active(),
        },
        "database": {
            "chunks_with_embeddings": chunks_with,
            "chunks_without_embeddings": chunks_without,
            "total_chunks": chunks_with + chunks_without,
        },
        "distribution": get_embedding_provider_distribution(),
        "pgvector": {
            "available": is_pgvector_available(),
            "database_vendor": connection.vendor,
        },
    }
