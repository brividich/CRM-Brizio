"""Hybrid retrieval for the internal AI knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from ....models import AIKnowledgeChunk, AIKnowledgeEmbedding
from ..redaction import redact_text
from .embedding_provider import get_embedding_provider
from .query_normalizer import NormalizedQuery, normalize_query
from .vector_backend import (
    pgvector_backend_available,
    pgvector_package_installed,
    retrieve_pgvector_candidates,
    retrieve_python_vector_candidates,
)


RETRIEVAL_MODES = {"hybrid_keyword", "pgvector", "hybrid_pgvector"}


@dataclass(frozen=True)
class RetrievalResult:
    chunk: AIKnowledgeChunk
    score: float
    metadata: dict
    keyword_score: float = 0.0
    vector_score: float = 0.0
    vector_distance: float | None = None
    score_components: dict = field(default_factory=dict)
    retrieval_mode: str = "hybrid_keyword"
    reason: str = ""
    snippet: str = ""


@dataclass(frozen=True)
class RetrievalDiagnostics:
    results: list[RetrievalResult]
    retrieval_mode: str
    retrieval_backend: str
    requested_mode: str
    pgvector_available: bool
    pgvector_package_installed: bool
    embeddings_used: bool
    insufficient_evidence_flags: list[str]
    min_score: float


def tokenize_query(query: str) -> list[str]:
    return normalize_query(query).tokens


def retrieve_chunks(
    query: str,
    *,
    source_type: str | None = None,
    source_object_type: str | None = None,
    source_object_id: str | int | None = None,
    context_type: str | None = None,
    context_object_id: str | int | None = None,
    limit: int = 5,
    min_score: float | None = None,
) -> list[RetrievalResult]:
    return retrieve_chunks_with_diagnostics(
        query,
        source_type=source_type,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        context_type=context_type,
        context_object_id=context_object_id,
        limit=limit,
        min_score=min_score,
    ).results


def retrieve_chunks_with_diagnostics(
    query: str,
    *,
    source_type: str | None = None,
    source_object_type: str | None = None,
    source_object_id: str | int | None = None,
    context_type: str | None = None,
    context_object_id: str | int | None = None,
    limit: int = 5,
    min_score: float | None = None,
) -> RetrievalDiagnostics:
    normalized = normalize_query(query)
    requested_mode = _requested_mode()
    min_score = float(getattr(settings, "AI_MEMORY_MIN_SCORE", 0.18) if min_score is None else min_score)
    limit = max(1, min(int(limit or 5), 20))
    keyword_top_k = max(limit, int(getattr(settings, "AI_MEMORY_KEYWORD_TOP_K", 10)))
    vector_top_k = max(limit, int(getattr(settings, "AI_MEMORY_VECTOR_TOP_K", 10)))

    if not normalized.tokens:
        return RetrievalDiagnostics(
            results=[],
            retrieval_mode=requested_mode,
            retrieval_backend="none",
            requested_mode=requested_mode,
            pgvector_available=pgvector_backend_available(),
            pgvector_package_installed=pgvector_package_installed(),
            embeddings_used=False,
            insufficient_evidence_flags=["no_results"],
            min_score=min_score,
        )

    keyword_results: list[RetrievalResult] = []
    vector_results: list[RetrievalResult] = []
    flags: list[str] = []
    backend = "keyword"

    if requested_mode in {"hybrid_keyword", "hybrid_pgvector"}:
        keyword_results = _keyword_retrieve(
            normalized,
            source_type=source_type,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            context_type=context_type,
            context_object_id=context_object_id,
            limit=keyword_top_k,
        )

    embeddings_enabled = bool(getattr(settings, "AI_MEMORY_EMBEDDINGS_ENABLED", False))
    if requested_mode in {"pgvector", "hybrid_pgvector"}:
        if embeddings_enabled:
            vector_results, backend, vector_flags = _vector_retrieve(
                normalized,
                source_type=source_type,
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                context_type=context_type,
                context_object_id=context_object_id,
                limit=vector_top_k,
            )
            flags.extend(vector_flags)
        else:
            flags.append("missing_embeddings")
            backend = "keyword_fallback"

    if requested_mode == "pgvector" and not vector_results:
        keyword_results = _keyword_retrieve(
            normalized,
            source_type=source_type,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            context_type=context_type,
            context_object_id=context_object_id,
            limit=keyword_top_k,
        )
        backend = "keyword_fallback"

    fused = _fuse_results(keyword_results, vector_results, requested_mode=requested_mode)
    below_threshold = [result for result in fused if result.score < min_score]
    results = [result for result in fused if result.score >= min_score][:limit]

    if not fused:
        flags.append("no_results")
    elif not results and below_threshold:
        flags.append("below_min_score")
    if len(results) >= 2 and abs(results[0].score - results[1].score) < 0.03:
        flags.append("ambiguous_results")

    effective_mode = requested_mode
    if requested_mode in {"pgvector", "hybrid_pgvector"} and backend == "keyword_fallback":
        effective_mode = f"{requested_mode}_fallback_keyword"
    return RetrievalDiagnostics(
        results=results,
        retrieval_mode=effective_mode,
        retrieval_backend=backend,
        requested_mode=requested_mode,
        pgvector_available=pgvector_backend_available(),
        pgvector_package_installed=pgvector_package_installed(),
        embeddings_used=bool(vector_results),
        insufficient_evidence_flags=_unique(flags),
        min_score=min_score,
    )


def _requested_mode() -> str:
    mode = str(getattr(settings, "AI_MEMORY_RETRIEVAL_MODE", "hybrid_keyword") or "hybrid_keyword").strip().lower()
    return mode if mode in RETRIEVAL_MODES else "hybrid_keyword"


def _keyword_retrieve(
    normalized: NormalizedQuery,
    *,
    source_type: str | None,
    source_object_type: str | None,
    source_object_id: str | int | None,
    context_type: str | None,
    context_object_id: str | int | None,
    limit: int,
) -> list[RetrievalResult]:
    queryset = AIKnowledgeChunk.objects.select_related("document").all()
    if source_type:
        queryset = queryset.filter(document__source_type=source_type)
    if source_object_type:
        queryset = queryset.filter(document__source_object_type=source_object_type)
    if source_object_id:
        queryset = queryset.filter(document__source_object_id=str(source_object_id))

    q = Q()
    for term in normalized.tokens[:12]:
        q |= Q(text__icontains=term) | Q(document__title__icontains=term)
    if q:
        queryset = queryset.filter(q)

    results = []
    for chunk in queryset[:700]:
        score, components, reason, snippet = _score_keyword_chunk(
            chunk,
            normalized,
            source_type=source_type,
            context_type=context_type,
            context_object_id=context_object_id,
        )
        if score <= 0:
            continue
        results.append(_result_from_chunk(chunk, score, score, 0.0, None, components, "keyword", reason, snippet))

    results.sort(key=lambda item: (-item.score, item.chunk.document_id, item.chunk.chunk_index))
    return results[: max(1, int(limit or 10))]


def _vector_retrieve(
    normalized: NormalizedQuery,
    *,
    source_type: str | None,
    source_object_type: str | None,
    source_object_id: str | int | None,
    context_type: str | None,
    context_object_id: str | int | None,
    limit: int,
) -> tuple[list[RetrievalResult], str, list[str]]:
    flags: list[str] = []
    provider = get_embedding_provider("deterministic_hash")
    query_vector = provider.embed_text(normalized.original)
    queryset = AIKnowledgeEmbedding.objects.filter(dimensions=provider.dimensions)
    if source_type:
        queryset = queryset.filter(chunk__document__source_type=source_type)
    if source_object_type:
        queryset = queryset.filter(chunk__document__source_object_type=source_object_type)
    if source_object_id:
        queryset = queryset.filter(chunk__document__source_object_id=str(source_object_id))
    if not queryset.exists():
        flags.append("missing_embeddings")
        return [], "keyword_fallback", flags

    backend = "pgvector" if pgvector_backend_available() else "json_cosine"
    if backend != "pgvector":
        flags.append("pgvector_unavailable")
        candidates = retrieve_python_vector_candidates(
            query_vector,
            dimensions=provider.dimensions,
            source_type=source_type,
            source_object_type=source_object_type,
            source_object_id=str(source_object_id) if source_object_id else None,
            limit=limit,
        )
    else:
        candidates = retrieve_pgvector_candidates(
            query_vector,
            dimensions=provider.dimensions,
            source_type=source_type,
            source_object_type=source_object_type,
            source_object_id=str(source_object_id) if source_object_id else None,
            limit=limit,
        )

    results = []
    for candidate in candidates:
        chunk = candidate.embedding.chunk
        context_boost = _context_affinity_boost(chunk, context_type, context_object_id)
        components = {
            "vector_score": round(candidate.vector_score, 4),
            "context_affinity_boost": round(context_boost, 4),
        }
        score = max(0.0, min(1.0, candidate.vector_score + context_boost))
        results.append(
            _result_from_chunk(
                chunk,
                score,
                0.0,
                candidate.vector_score,
                candidate.vector_distance,
                components,
                candidate.backend,
                "Embedding similarity matched indexed knowledge.",
                _safe_snippet(chunk.text, normalized.tokens),
            )
        )
    return results, backend, flags


def _score_keyword_chunk(
    chunk: AIKnowledgeChunk,
    normalized: NormalizedQuery,
    *,
    source_type: str | None,
    context_type: str | None,
    context_object_id: str | int | None,
) -> tuple[float, dict, str, str]:
    document = chunk.document
    text_lower = chunk.text.lower()
    title_lower = document.title.lower()
    metadata_text = _metadata_text(document.metadata, chunk.metadata)
    haystack = f"{title_lower} {text_lower} {metadata_text}"

    token_hits = [token for token in normalized.tokens if token in haystack]
    important_hits = [token for token in normalized.important_tokens if token in haystack]
    phrase_hits = [phrase for phrase in normalized.phrases if phrase and phrase in haystack]
    title_hits = [token for token in normalized.tokens if token in title_lower]
    metadata_hits = [token for token in normalized.tokens if token in metadata_text]

    token_overlap = len(token_hits) / max(1, len(normalized.tokens))
    important_overlap = len(important_hits) / max(1, len(normalized.important_tokens) or 1)
    phrase_score = 1.0 if normalized.normalized and normalized.normalized in haystack else min(1.0, len(phrase_hits) * 0.4)
    title_boost = min(0.16, len(title_hits) * 0.04)
    metadata_boost = min(0.12, len(metadata_hits) * 0.03)
    source_type_boost = 0.06 if source_type and document.source_type == source_type else 0.0
    context_boost = _context_affinity_boost(chunk, context_type, context_object_id)
    recency_boost = _recency_boost(document.updated_at)

    score = (
        token_overlap * 0.42
        + important_overlap * 0.18
        + phrase_score * 0.22
        + title_boost
        + metadata_boost
        + source_type_boost
        + context_boost
        + recency_boost
    )
    score = max(0.0, min(1.0, score))
    components = {
        "exact_phrase": round(phrase_score, 4),
        "token_overlap": round(token_overlap, 4),
        "important_token_overlap": round(important_overlap, 4),
        "title_boost": round(title_boost, 4),
        "metadata_boost": round(metadata_boost, 4),
        "source_type_boost": round(source_type_boost, 4),
        "context_affinity_boost": round(context_boost, 4),
        "recency_boost": round(recency_boost, 4),
        "keyword_score": round(score, 4),
    }
    reason = _keyword_reason(phrase_score, token_hits, title_hits, metadata_hits, context_boost)
    return score, components, reason, _safe_snippet(chunk.text, normalized.tokens)


def _fuse_results(
    keyword_results: list[RetrievalResult],
    vector_results: list[RetrievalResult],
    *,
    requested_mode: str,
) -> list[RetrievalResult]:
    by_chunk: dict[int, RetrievalResult] = {}
    for result in keyword_results + vector_results:
        existing = by_chunk.get(result.chunk.id)
        if existing is None:
            by_chunk[result.chunk.id] = result
            continue
        by_chunk[result.chunk.id] = _merge_result(existing, result, requested_mode=requested_mode)

    fused = list(by_chunk.values())
    if requested_mode in {"hybrid_pgvector", "pgvector"}:
        fused = [
            _apply_hybrid_score(result, requested_mode=requested_mode)
            for result in fused
        ]
    fused.sort(key=lambda item: (-item.score, item.chunk.document_id, item.chunk.chunk_index))
    return fused


def _merge_result(left: RetrievalResult, right: RetrievalResult, *, requested_mode: str) -> RetrievalResult:
    keyword_score = max(left.keyword_score, right.keyword_score)
    vector_score = max(left.vector_score, right.vector_score)
    score_components = {**left.score_components, **right.score_components}
    vector_distance = left.vector_distance if left.vector_distance is not None else right.vector_distance
    reason = left.reason if left.keyword_score >= right.keyword_score else right.reason
    snippet = left.snippet or right.snippet
    return _result_from_chunk(
        left.chunk,
        max(left.score, right.score),
        keyword_score,
        vector_score,
        vector_distance,
        score_components,
        requested_mode,
        reason,
        snippet,
    )


def _apply_hybrid_score(result: RetrievalResult, *, requested_mode: str) -> RetrievalResult:
    keyword_weight = float(getattr(settings, "AI_MEMORY_KEYWORD_WEIGHT", 0.40))
    vector_weight = float(getattr(settings, "AI_MEMORY_VECTOR_WEIGHT", 0.60))
    weight_total = max(0.01, keyword_weight + vector_weight)
    keyword_weight = keyword_weight / weight_total
    vector_weight = vector_weight / weight_total
    boost = (
        float(result.score_components.get("title_boost", 0.0))
        + float(result.score_components.get("metadata_boost", 0.0))
        + float(result.score_components.get("context_affinity_boost", 0.0))
        + float(result.score_components.get("recency_boost", 0.0))
    )
    final_score = max(0.0, min(1.0, keyword_weight * result.keyword_score + vector_weight * result.vector_score + boost))
    components = {
        **result.score_components,
        "keyword_weight": round(keyword_weight, 4),
        "vector_weight": round(vector_weight, 4),
        "final_score": round(final_score, 4),
    }
    return _result_from_chunk(
        result.chunk,
        final_score,
        result.keyword_score,
        result.vector_score,
        result.vector_distance,
        components,
        requested_mode,
        result.reason,
        result.snippet,
    )


def _result_from_chunk(
    chunk: AIKnowledgeChunk,
    score: float,
    keyword_score: float,
    vector_score: float,
    vector_distance: float | None,
    score_components: dict,
    retrieval_mode: str,
    reason: str,
    snippet: str,
) -> RetrievalResult:
    document = chunk.document
    return RetrievalResult(
        chunk=chunk,
        score=round(score, 4),
        keyword_score=round(keyword_score, 4),
        vector_score=round(vector_score, 4),
        vector_distance=round(vector_distance, 4) if vector_distance is not None else None,
        score_components=score_components,
        retrieval_mode=retrieval_mode,
        reason=reason,
        snippet=snippet,
        metadata={
            "document_id": chunk.document_id,
            "document_title": document.title,
            "source_type": document.source_type,
            "source_object_type": document.source_object_type,
            "source_object_id": document.source_object_id,
            "chunk_index": chunk.chunk_index,
        },
    )


def _metadata_text(*metadata_items: dict) -> str:
    parts = []
    for metadata in metadata_items:
        if isinstance(metadata, dict) and metadata:
            parts.append(json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str).lower())
    return " ".join(parts)


def _context_affinity_boost(chunk: AIKnowledgeChunk, context_type: str | None, context_object_id: str | int | None) -> float:
    if not context_type or not context_object_id:
        return 0.0
    document = chunk.document
    if document.source_object_type == context_type and str(document.source_object_id) == str(context_object_id):
        return 0.18
    if document.source_object_type == context_type:
        return 0.05
    return 0.0


def _recency_boost(updated_at) -> float:
    if not updated_at:
        return 0.0
    age_days = max(0, (timezone.now() - updated_at).days)
    if age_days <= 7:
        return 0.04
    if age_days <= 30:
        return 0.02
    return 0.0


def _keyword_reason(phrase_score: float, token_hits: list[str], title_hits: list[str], metadata_hits: list[str], context_boost: float) -> str:
    reasons = []
    if phrase_score >= 1.0:
        reasons.append("exact phrase")
    if title_hits:
        reasons.append("title match")
    if metadata_hits:
        reasons.append("metadata match")
    if context_boost:
        reasons.append("same context object")
    if token_hits and not reasons:
        reasons.append("token overlap")
    return "Matched by " + ", ".join(reasons[:4]) + "." if reasons else "Matched indexed knowledge."


def _safe_snippet(text: str, tokens: list[str]) -> str:
    redacted = redact_text(str(text or ""))
    lowered = redacted.lower()
    start = 0
    for token in tokens:
        index = lowered.find(token.lower())
        if index >= 0:
            start = max(0, index - 70)
            break
    snippet = redacted[start : start + 220]
    if start > 0:
        snippet = "..." + snippet
    if start + 220 < len(redacted):
        snippet = snippet + "..."
    return snippet


def _unique(flags: list[str]) -> list[str]:
    unique_flags = []
    for flag in flags:
        if flag and flag not in unique_flags:
            unique_flags.append(flag)
    return unique_flags
