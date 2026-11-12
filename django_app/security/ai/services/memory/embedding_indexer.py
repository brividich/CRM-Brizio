"""Build and maintain AI memory embeddings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
import hashlib

from django.db import transaction
from django.utils import timezone

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
    """Calcola gli embedding mancanti o cambiati.

    Gli hash esistenti si leggono prima; i vettori si chiedono al provider a gruppi (``embed_batch``)
    FUORI da ogni transazione (prima una transazione restava aperta durante ogni chiamata HTTP, un
    chunk alla volta); ogni gruppo si salva poi in un'unica transazione breve (``bulk_update``).
    ``limit`` si applica alla query, non dopo aver caricato tutti i chunk.
    """
    provider = get_embedding_provider(provider_name)
    queryset = AIKnowledgeChunk.objects.select_related("document").order_by("document_id", "chunk_index")
    if source_type:
        queryset = queryset.filter(document__source_type=source_type)
    if document_id:
        queryset = queryset.filter(document_id=document_id)

    stats = EmbeddingIndexStats(documents_seen=queryset.values("document_id").distinct().count())
    stats.chunks_seen = queryset.count()
    if limit is not None and limit > 0:
        queryset = queryset[:limit]
    chunks = list(queryset)

    if reset_embeddings and not dry_run:
        with transaction.atomic():
            for ids in _a_gruppi([chunk.id for chunk in chunks], _IN_BATCH):
                AIKnowledgeEmbedding.objects.filter(chunk_id__in=ids).delete()
            for chunk in chunks:
                chunk.embedding = []
            AIKnowledgeChunk.objects.bulk_update(chunks, ["embedding"], batch_size=_IN_BATCH)

    existing_by_chunk: dict[int, AIKnowledgeEmbedding] = {}
    for ids in _a_gruppi([chunk.id for chunk in chunks], _IN_BATCH):
        for embedding in AIKnowledgeEmbedding.objects.filter(chunk_id__in=ids):
            existing_by_chunk[embedding.chunk_id] = embedding

    pending: list[tuple[AIKnowledgeChunk, AIKnowledgeEmbedding | None, str]] = []
    for chunk in chunks:
        embedding_hash = build_embedding_hash(chunk, provider)
        existing = existing_by_chunk.get(chunk.id)
        if (
            existing
            and existing.embedding_hash == embedding_hash
            and existing.provider == provider.provider_name
            and existing.dimensions == provider.dimensions
        ):
            stats.embeddings_skipped += 1
            continue
        if dry_run:
            if existing:
                stats.embeddings_updated += 1
            else:
                stats.embeddings_created += 1
            continue
        pending.append((chunk, existing, embedding_hash))

    for group in _a_gruppi(pending, max(1, int(batch_size or 100))):
        try:
            vectors = provider.embed_batch([chunk.text for chunk, _existing, _hash in group])
            if len(vectors) != len(group):
                raise RuntimeError(f"{len(vectors)} vettori per {len(group)} testi")
        except Exception as e:
            stats.provider_errors += 1
            stats.errors += len(group)
            logger.error(
                "Embedding di %d chunk non riuscito (%s): %s", len(group), provider.provider_name, str(e)[:200],
            )
            if strict:
                raise
            continue
        try:
            _salva_gruppo(group, vectors, provider=provider, stats=stats)
        except Exception as e:
            stats.errors += len(group)
            logger.error("Salvataggio di %d embedding non riuscito: %s", len(group), str(e)[:200])
            if strict:
                raise
    return stats


_IN_BATCH = 500  # SQL Server: massimo ~2100 parametri per query


def _a_gruppi(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _salva_gruppo(
    group: list[tuple[AIKnowledgeChunk, AIKnowledgeEmbedding | None, str]],
    vectors: list[list[float]],
    *,
    provider: BaseEmbeddingProvider,
    stats: EmbeddingIndexStats,
) -> None:
    """Salva un gruppo di vettori già calcolati in una transazione breve (nessuna chiamata di rete qui)."""
    to_update: list[AIKnowledgeEmbedding] = []
    saved: list[AIKnowledgeEmbedding] = []
    created = 0
    with transaction.atomic():
        for (chunk, existing, embedding_hash), vector in zip(group, vectors, strict=True):
            metadata = {"source": "rebuild_ai_memory_index", "text_hash": chunk.text_hash}
            if existing:
                existing.provider = provider.provider_name
                existing.model_name = provider.model_name
                existing.dimensions = provider.dimensions
                existing.embedding_hash = embedding_hash
                existing.embedding = vector
                existing.metadata = metadata
                existing.updated_at = timezone.now()  # bulk_update non applica auto_now
                to_update.append(existing)
            else:
                existing = AIKnowledgeEmbedding.objects.create(
                    chunk=chunk,
                    provider=provider.provider_name,
                    model_name=provider.model_name,
                    dimensions=provider.dimensions,
                    embedding_hash=embedding_hash,
                    embedding=vector,
                    metadata=metadata,
                )
                created += 1
            saved.append(existing)
            chunk.embedding = vector
        if to_update:
            AIKnowledgeEmbedding.objects.bulk_update(
                to_update,
                ["provider", "model_name", "dimensions", "embedding_hash", "embedding", "metadata", "updated_at"],
                batch_size=_IN_BATCH,
            )
        AIKnowledgeChunk.objects.bulk_update([chunk for chunk, _e, _h in group], ["embedding"], batch_size=_IN_BATCH)
    stats.embeddings_created += created
    stats.embeddings_updated += len(to_update)

    non_salvati = [embedding for embedding in saved if not store_pgvector_embedding(embedding)]
    if non_salvati:
        logger.warning(
            "pgvector embedding storage unavailable for %d chunk (es. chunk %s). JSON fallback is active.",
            len(non_salvati),
            non_salvati[0].chunk_id,
        )
