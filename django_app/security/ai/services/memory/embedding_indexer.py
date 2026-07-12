"""Build and maintain AI memory embeddings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
import hashlib

from django.db import transaction

from ....models import AIKnowledgeChunk, AIKnowledgeEmbedding
from .embedding_provider import BaseEmbeddingProvider, get_embedding_provider
from .vector_backend import store_pgvector_embedding


logger = logging.getLogger(__name__)


@dataclass
class EmbeddingIndexStats:
    documents_seen: int = 0
    chunks_seen: int = 0
    embeddings_created: int = 0
    embeddings_updated: int = 0
    embeddings_skipped: int = 0
    provider_errors: int = 0
    rate_limit_hits: int = 0
    errors: int = 0

    def as_dict(self) -> dict:
        return {
            "documents_seen": self.documents_seen,
            "chunks_seen": self.chunks_seen,
            "embeddings_created": self.embeddings_created,
            "embeddings_updated": self.embeddings_updated,
            "embeddings_skipped": self.embeddings_skipped,
            "provider_errors": self.provider_errors,
            "rate_limit_hits": self.rate_limit_hits,
            "errors": self.errors,
        }


def build_embedding_hash(chunk: AIKnowledgeChunk, provider: BaseEmbeddingProvider) -> str:
    payload = f"{provider.provider_name}:{provider.model_name}:{provider.dimensions}:{chunk.text_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rebuild_embeddings(
    *,
    provider_name: str = "deterministic_hash",
    dry_run: bool = False,
    source_type: str | None = None,
    document_id: int | None = None,
    reset_embeddings: bool = False,
    batch_size: int = 100,
    limit: int | None = None,
    strict: bool = False,
) -> EmbeddingIndexStats:
    provider = get_embedding_provider(provider_name)
    queryset = AIKnowledgeChunk.objects.select_related("document").order_by("document_id", "chunk_index")
    if source_type:
        queryset = queryset.filter(document__source_type=source_type)
    if document_id:
        queryset = queryset.filter(document_id=document_id)

    stats = EmbeddingIndexStats(documents_seen=queryset.values("document_id").distinct().count())
    chunks = list(queryset)
    stats.chunks_seen = len(chunks)

    # Apply limit if specified
    if limit is not None and limit > 0:
        chunks = chunks[:limit]

    if reset_embeddings and not dry_run:
        AIKnowledgeEmbedding.objects.filter(chunk__in=chunks).delete()
        for chunk in chunks:
            chunk.embedding = []
        AIKnowledgeChunk.objects.bulk_update(chunks, ["embedding"])

    for chunk in chunks:
        try:
            _index_chunk_embedding(chunk, provider=provider, dry_run=dry_run, stats=stats)
        except Exception as e:
            stats.errors += 1
            error_message = str(e)[:200]
            logger.error(f"Error indexing chunk {chunk.id}: {error_message}")
            if strict:
                raise
    return stats


@transaction.atomic
def _index_chunk_embedding(
    chunk: AIKnowledgeChunk,
    *,
    provider: BaseEmbeddingProvider,
    dry_run: bool,
    stats: EmbeddingIndexStats,
) -> None:
    embedding_hash = build_embedding_hash(chunk, provider)
    existing = AIKnowledgeEmbedding.objects.filter(chunk=chunk).first()
    if (
        existing
        and existing.embedding_hash == embedding_hash
        and existing.provider == provider.provider_name
        and existing.dimensions == provider.dimensions
    ):
        stats.embeddings_skipped += 1
        return

    if dry_run:
        if existing:
            stats.embeddings_updated += 1
        else:
            stats.embeddings_created += 1
        return

    vector = provider.embed_text(chunk.text)
    if existing:
        existing.provider = provider.provider_name
        existing.model_name = provider.model_name
        existing.dimensions = provider.dimensions
        existing.embedding_hash = embedding_hash
        existing.embedding = vector
        existing.metadata = {"source": "rebuild_ai_memory_index", "text_hash": chunk.text_hash}
        existing.save()
        stats.embeddings_updated += 1
    else:
        existing = AIKnowledgeEmbedding.objects.create(
            chunk=chunk,
            provider=provider.provider_name,
            model_name=provider.model_name,
            dimensions=provider.dimensions,
            embedding_hash=embedding_hash,
            embedding=vector,
            metadata={"source": "rebuild_ai_memory_index", "text_hash": chunk.text_hash},
        )
        stats.embeddings_created += 1

    chunk.embedding = vector
    chunk.save(update_fields=["embedding"])
    pgvector_stored = store_pgvector_embedding(existing)
    if not pgvector_stored:
        logger.warning(
            "pgvector embedding storage unavailable for chunk %s (document %s). "
            "JSON fallback is active.",
            chunk.id,
            chunk.document_id,
        )
