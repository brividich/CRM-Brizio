"""Index text into the internal AI knowledge base."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from ....models import AIKnowledgeChunk, AIKnowledgeDocument
from .chunker import chunk_text, hash_text, normalize_whitespace


@dataclass(frozen=True)
class IndexResult:
    document: AIKnowledgeDocument
    created: bool
    updated: bool
    chunks_count: int


def _clean_metadata(metadata: Any) -> dict:
    return metadata if isinstance(metadata, dict) else {}


def _source_identity_filter(source_type: str, source_object_type: str, source_object_id: str) -> dict[str, str] | None:
    if source_object_type and source_object_id:
        return {
            "source_type": source_type,
            "source_object_type": source_object_type,
            "source_object_id": source_object_id,
        }
    return None


@transaction.atomic
def index_document(
    *,
    source_type: str,
    source_object_type: str = "",
    source_object_id: str = "",
    title: str,
    raw_text: str,
    metadata: dict | None = None,
) -> IndexResult:
    source_type = normalize_whitespace(source_type)[:80]
    source_object_type = normalize_whitespace(source_object_type)[:80]
    source_object_id = normalize_whitespace(str(source_object_id or ""))[:80]
    title = normalize_whitespace(title)[:255]
    normalized_text = normalize_whitespace(raw_text)

    if not source_type:
        raise ValueError("source_type is required")
    if not title:
        raise ValueError("title is required")
    if not normalized_text:
        raise ValueError("raw_text is required")

    content_hash = hash_text(normalized_text)
    metadata = _clean_metadata(metadata)
    created = False
    updated = False

    identity_filter = _source_identity_filter(source_type, source_object_type, source_object_id)
    document = AIKnowledgeDocument.objects.filter(**identity_filter).first() if identity_filter else None

    if document is None:
        document = AIKnowledgeDocument.objects.filter(content_hash=content_hash).first()

    if document is None:
        document = AIKnowledgeDocument.objects.create(
            source_type=source_type,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            title=title,
            content_hash=content_hash,
            raw_text=normalized_text,
            metadata=metadata,
        )
        created = True
        _replace_chunks(document, normalized_text)
    else:
        content_changed = document.content_hash != content_hash
        fields_changed = (
            document.title != title
            or document.source_type != source_type
            or document.source_object_type != source_object_type
            or document.source_object_id != source_object_id
            or document.metadata != metadata
        )
        if content_changed or fields_changed:
            document.title = title
            document.source_type = source_type
            document.source_object_type = source_object_type
            document.source_object_id = source_object_id
            document.content_hash = content_hash
            document.raw_text = normalized_text
            document.metadata = metadata
            document.save()
            updated = True
        if content_changed:
            _replace_chunks(document, normalized_text)

    return IndexResult(
        document=document,
        created=created,
        updated=updated,
        chunks_count=document.chunks.count(),
    )


def _replace_chunks(document: AIKnowledgeDocument, raw_text: str) -> None:
    AIKnowledgeChunk.objects.filter(document=document).delete()
    chunks = chunk_text(raw_text)
    AIKnowledgeChunk.objects.bulk_create(
        [
            AIKnowledgeChunk(
                document=document,
                chunk_index=chunk.index,
                text=chunk.text,
                text_hash=chunk.text_hash,
                metadata={"chunk_index": chunk.index},
            )
            for chunk in chunks
        ]
    )
