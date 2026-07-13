"""Optional vector retrieval backends for AI memory.

The Django model stores JSON embeddings so SQLite/dev/test never require
pgvector. PostgreSQL deployments may add a pgvector column named
``vector_embedding`` to ``security_aiknowledgeembedding``; this module detects it
at runtime and uses raw cosine distance SQL only when it is available.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import math

from django.db import DatabaseError, connection

from ....models import AIKnowledgeEmbedding


@dataclass(frozen=True)
class VectorCandidate:
    embedding: AIKnowledgeEmbedding
    vector_score: float
    vector_distance: float | None
    backend: str


def pgvector_package_installed() -> bool:
    return importlib.util.find_spec("pgvector") is not None


def pgvector_extension_enabled() -> bool:
    if connection.vendor != "postgresql":
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            row = cursor.fetchone()
        return bool(row and row[0])
    except DatabaseError:
        return False


def pgvector_column_available() -> bool:
    if connection.vendor != "postgresql":
        return False
    try:
        description = connection.introspection.get_table_description(
            connection.cursor(),
            AIKnowledgeEmbedding._meta.db_table,
        )
    except DatabaseError:
        return False
    return any(column.name == "vector_embedding" for column in description)


def pgvector_backend_available() -> bool:
    return connection.vendor == "postgresql" and pgvector_extension_enabled() and pgvector_column_available()


def store_pgvector_embedding(embedding: AIKnowledgeEmbedding) -> bool:
    if not pgvector_backend_available():
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {AIKnowledgeEmbedding._meta.db_table} "
                "SET vector_embedding = %s::vector WHERE id = %s",
                [_vector_literal(embedding.embedding), embedding.id],
            )
        return True
    except DatabaseError:
        return False


def retrieve_pgvector_candidates(
    query_vector: list[float],
    *,
    dimensions: int,
    source_type: str | None = None,
    source_object_type: str | None = None,
    source_object_id: str | None = None,
    limit: int = 10,
) -> list[VectorCandidate]:
    if not pgvector_backend_available():
        return []

    params: list[object] = [_vector_literal(query_vector), dimensions]
    where = ["e.dimensions = %s", "e.vector_embedding IS NOT NULL"]
    if source_type:
        where.append("d.source_type = %s")
        params.append(source_type)
    if source_object_type:
        where.append("d.source_object_type = %s")
        params.append(source_object_type)
    if source_object_id:
        where.append("d.source_object_id = %s")
        params.append(str(source_object_id))
    params.append(max(1, int(limit or 10)))

    table_embedding = AIKnowledgeEmbedding._meta.db_table
    where_sql = " AND ".join(where)
    sql = f"""
        SELECT e.id, (e.vector_embedding <=> %s::vector) AS distance
        FROM {table_embedding} e
        JOIN security_aiknowledgechunk c ON c.id = e.chunk_id
        JOIN security_aiknowledgedocument d ON d.id = c.document_id
        WHERE {where_sql}
        ORDER BY distance ASC
        LIMIT %s
    """

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except DatabaseError:
        return []

    distances = {row[0]: float(row[1]) for row in rows}
    embeddings = AIKnowledgeEmbedding.objects.select_related("chunk", "chunk__document").filter(id__in=distances)
    candidates = []
    for embedding in embeddings:
        distance = distances[embedding.id]
        candidates.append(
            VectorCandidate(
                embedding=embedding,
                vector_score=max(0.0, min(1.0, 1.0 - distance)),
                vector_distance=distance,
                backend="pgvector",
            )
        )
    candidates.sort(key=lambda item: (-item.vector_score, item.embedding.chunk.document_id, item.embedding.chunk.chunk_index))
    return candidates


def retrieve_python_vector_candidates(
    query_vector: list[float],
    *,
    dimensions: int,
    source_type: str | None = None,
    source_object_type: str | None = None,
    source_object_id: str | None = None,
    limit: int = 10,
) -> list[VectorCandidate]:
    queryset = AIKnowledgeEmbedding.objects.select_related("chunk", "chunk__document").filter(dimensions=dimensions)
    if source_type:
        queryset = queryset.filter(chunk__document__source_type=source_type)
    if source_object_type:
        queryset = queryset.filter(chunk__document__source_object_type=source_object_type)
    if source_object_id:
        queryset = queryset.filter(chunk__document__source_object_id=str(source_object_id))

    candidates = []
    for embedding in queryset[:1000]:
        vector_score = cosine_similarity(query_vector, embedding.embedding)
        if vector_score <= 0:
            continue
        candidates.append(
            VectorCandidate(
                embedding=embedding,
                vector_score=vector_score,
                vector_distance=1.0 - vector_score,
                backend="json_cosine",
            )
        )
    candidates.sort(key=lambda item: (-item.vector_score, item.embedding.chunk.document_id, item.embedding.chunk.chunk_index))
    return candidates[: max(1, int(limit or 10))]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
