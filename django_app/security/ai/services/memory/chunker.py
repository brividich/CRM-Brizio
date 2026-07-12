"""Stable text chunking for AI knowledge documents."""

import hashlib
import re
from dataclasses import dataclass


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 120


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    text_hash: str


def normalize_whitespace(text: str) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return re.sub(r"\s+", " ", text).strip()


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()


def chunk_text(text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[TextChunk]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []

    chunk_size = max(200, int(chunk_size or DEFAULT_CHUNK_SIZE))
    overlap = max(0, min(int(overlap or 0), chunk_size // 3))

    chunks: list[TextChunk] = []
    start = 0
    text_len = len(normalized)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            break_at = normalized.rfind(" ", start, end)
            if break_at > start + (chunk_size // 2):
                end = break_at

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(TextChunk(index=len(chunks), text=chunk, text_hash=hash_text(chunk)))

        if end >= text_len:
            break
        start = max(end - overlap, end if overlap == 0 else 0)

    return chunks
