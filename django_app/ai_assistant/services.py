from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache


class OllamaChatError(RuntimeError):
    """Errore funzionale nella chiamata al runtime Ollama."""


@dataclass(frozen=True)
class OllamaChatResult:
    content: str
    model: str
    done: bool
    sources: tuple[str, ...] = ()
    rag_context_chars: int = 0


@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    title: str
    content: str
    tokens: Counter[str]


@dataclass(frozen=True)
class KnowledgeContext:
    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeIndex:
    """Corpus RAG con statistiche BM25 precalcolate (IDF e lunghezza media).

    Quando il retrieval semantico e' attivo (``OLLAMA_EMBED_ENABLED``) l'indice
    porta anche gli ``embeddings`` allineati ai chunk e le loro norme L2, usati
    per la similarita' coseno e la fusione ibrida con BM25.
    """

    chunks: tuple[KnowledgeChunk, ...]
    idf: dict[str, float]
    avgdl: float
    embeddings: tuple[tuple[float, ...], ...] | None = None
    embed_norms: tuple[float, ...] = ()
    embed_model: str = ""


_RAG_ALLOWED_EXTENSIONS = {".md", ".txt", ".rst"}
# Stopword italiane (gia' accent-folded: la tokenizzazione rimuove gli accenti).
_RAG_STOPWORDS = {
    "ad", "agli", "ai", "al", "alla", "alle", "allo", "anche", "ancora",
    "che", "chi", "ci", "coi", "col", "come", "con", "cosa", "cui",
    "da", "dagli", "dai", "dal", "dalla", "dalle", "dallo", "degli", "dei",
    "del", "della", "delle", "dello", "di", "dopo", "dove", "due", "e", "ed",
    "ecco", "gia", "gli", "ha", "hai", "hanno", "ho", "il", "in", "io",
    "la", "le", "lei", "li", "lo", "loro", "lui", "ma", "mi", "ne", "negli",
    "nei", "nel", "nella", "nelle", "nello", "noi", "non", "o", "od", "per",
    "piu", "poi", "qua", "quale", "quali", "quando", "quanto", "quasi",
    "quel", "quella", "quelle", "quelli", "quello", "questa", "queste",
    "questi", "questo", "qui", "se", "sei", "senza", "si", "sia", "sono",
    "su", "sue", "sugli", "sui", "sul", "sulla", "sulle", "sullo", "suo",
    "ti", "tra", "tu", "tua", "tue", "tuo", "un", "una", "uno", "vi", "voi",
}
_KNOWLEDGE_CACHE: dict[str, Any] = {"loaded_at": 0.0, "signature": (), "index": None}


def clear_knowledge_cache() -> None:
    _KNOWLEDGE_CACHE.update({"loaded_at": 0.0, "signature": (), "index": None})


def _ollama_endpoint_hint(base_url: str, *, http_status: int | None = None) -> str:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
        host = parsed.hostname or "host"
    except ValueError:
        port = None
        host = "host"
    if port in {3000, 8080, 8081} or http_status in {404, 405}:
        return (
            "L'URL configurato sembra non essere l'API nativa di Ollama. "
            "Non usare l'indirizzo di Open WebUI: configura OLLAMA_BASE_URL con l'endpoint Ollama, "
            f"per esempio http://{host}:11434."
        )
    return "Verifica OLLAMA_BASE_URL: deve puntare all'API nativa di Ollama, non a Open WebUI."


def _timeout_message(timeout: int) -> str:
    return (
        f"Timeout dopo {timeout}s durante la risposta di Ollama. "
        "La connessione funziona, ma il modello puo' essere ancora in caricamento o troppo lento per il timeout "
        "configurato. Aumenta OLLAMA_REQUEST_TIMEOUT_SECONDS a 180-300 e riavvia Django/IIS."
    )


def _clean_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if limit > 0 and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _fold_accents(value: str) -> str:
    """Rimuove gli accenti (qualita'<->qualita, citta<->citta) via NFKD."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokenize(value: str) -> list[str]:
    folded = _fold_accents(value.lower())
    return [
        token
        for token in re.findall(r"[a-z0-9_]{3,}", folded)
        if token not in _RAG_STOPWORDS
    ]


def _repo_root() -> Path:
    return Path(getattr(settings, "BASE_DIR", Path.cwd())).resolve().parent


def _source_paths() -> list[str]:
    raw_paths = getattr(settings, "OLLAMA_RAG_SOURCE_PATHS", ["README.md", "docs/ai"])
    if isinstance(raw_paths, str):
        return [item.strip() for item in raw_paths.split(",") if item.strip()]
    return [str(item).strip() for item in raw_paths if str(item).strip()]


def _safe_source_path(raw_path: str) -> Path | None:
    repo_root = _repo_root()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(repo_root)
    except (OSError, ValueError):
        return None
    return resolved


def _iter_knowledge_files() -> list[Path]:
    files: list[Path] = []
    max_files = int(getattr(settings, "OLLAMA_RAG_MAX_FILES", 80) or 80)
    for raw_path in _source_paths():
        source_path = _safe_source_path(raw_path)
        if not source_path or not source_path.exists():
            continue
        if source_path.is_file() and source_path.suffix.lower() in _RAG_ALLOWED_EXTENSIONS:
            files.append(source_path)
        elif source_path.is_dir():
            for candidate in sorted(source_path.rglob("*")):
                if candidate.is_file() and candidate.suffix.lower() in _RAG_ALLOWED_EXTENSIONS:
                    files.append(candidate)
                if len(files) >= max_files:
                    return files[:max_files]
    return files[:max_files]


def _relative_source(path: Path) -> str:
    try:
        return path.resolve().relative_to(_repo_root()).as_posix()
    except ValueError:
        return path.name


def _overlap_tail(text: str, overlap_chars: int) -> str:
    """Ritorna gli ultimi ``overlap_chars`` di ``text`` tagliati su confine di parola."""
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return text if overlap_chars > 0 else ""
    tail = text[-overlap_chars:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def _split_long_section(source: str, title: str, content: str, *, max_chars: int) -> list[KnowledgeChunk]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    overlap_chars = int(getattr(settings, "OLLAMA_RAG_CHUNK_OVERLAP_CHARS", 0) or 0)
    chunks: list[KnowledgeChunk] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(
                KnowledgeChunk(
                    source=source,
                    title=title,
                    content=current.strip(),
                    tokens=Counter(_tokenize(f"{title}\n{current}")),
                )
            )
            # Overlap: riporta la coda del chunk precedente in testa al successivo,
            # cosi' una risposta a cavallo del confine resta recuperabile.
            tail = _overlap_tail(current.strip(), overlap_chars)
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(
            KnowledgeChunk(
                source=source,
                title=title,
                content=current.strip()[:max_chars],
                tokens=Counter(_tokenize(f"{title}\n{current}")),
            )
        )
    return chunks


def _chunk_document(path: Path, text: str) -> list[KnowledgeChunk]:
    source = _relative_source(path)
    max_chars = int(getattr(settings, "OLLAMA_RAG_CHUNK_CHARS", 1600) or 1600)
    sections: list[tuple[str, list[str]]] = []
    title = path.stem
    lines: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
        if heading:
            if lines:
                sections.append((title, lines))
            title = heading.group(1).strip()
            lines = [line]
        else:
            lines.append(line)
    if lines:
        sections.append((title, lines))

    chunks: list[KnowledgeChunk] = []
    for section_title, section_lines in sections:
        section_text = "\n".join(section_lines).strip()
        if section_text:
            chunks.extend(_split_long_section(source, section_title, section_text, max_chars=max_chars))
    return chunks


def _load_curated_knowledge_chunks() -> list[KnowledgeChunk]:
    try:
        from .models import AiKnowledgeEntry
    except Exception:
        return []

    limit = int(getattr(settings, "OLLAMA_RAG_MAX_DB_ENTRIES", 200) or 200)
    try:
        entries = list(
            AiKnowledgeEntry.objects.filter(is_active=True)
            .only("id", "question", "answer", "source_label", "updated_at")
            .order_by("-updated_at")[:limit]
        )
    except Exception:
        return []

    chunks: list[KnowledgeChunk] = []
    max_chars = int(getattr(settings, "OLLAMA_RAG_CHUNK_CHARS", 1600) or 1600)
    for entry in entries:
        question = _clean_text(entry.question, limit=500)
        answer = _clean_text(entry.answer, limit=max_chars)
        if not question or not answer:
            continue
        source = f"faq-portale/{entry.id}"
        title = _clean_text(entry.source_label or "FAQ Portale", limit=120)
        content = f"Domanda: {question}\nRisposta: {answer}"
        chunks.append(
            KnowledgeChunk(
                source=source,
                title=title,
                content=content,
                tokens=Counter(_tokenize(f"{title}\n{question}\n{answer}")),
            )
        )
    return chunks


def _curated_knowledge_signature() -> tuple[int, str]:
    try:
        from .models import AiKnowledgeEntry
    except Exception:
        return (0, "")
    try:
        latest = AiKnowledgeEntry.objects.filter(is_active=True).order_by("-updated_at").first()
        count = AiKnowledgeEntry.objects.filter(is_active=True).count()
    except Exception:
        return (0, "")
    return (count, latest.updated_at.isoformat() if latest else "")


def _build_index(chunks: list[KnowledgeChunk]) -> KnowledgeIndex:
    """Precalcola IDF (con smoothing BM25) e lunghezza media dei chunk."""
    n = len(chunks)
    if not n:
        return KnowledgeIndex(chunks=(), idf={}, avgdl=0.0)
    document_frequency: Counter[str] = Counter()
    total_length = 0
    for chunk in chunks:
        total_length += sum(chunk.tokens.values())
        document_frequency.update(chunk.tokens.keys())
    avgdl = total_length / n if n else 0.0
    idf = {
        token: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5))
        for token, freq in document_frequency.items()
    }
    return KnowledgeIndex(chunks=tuple(chunks), idf=idf, avgdl=avgdl)


# ── Retrieval semantico (embeddings via Ollama nativo) ──────────────────────
# Opt-in con OLLAMA_EMBED_ENABLED. Richiede un modello di embedding scaricato in
# Ollama (es. `ollama pull nomic-embed-text`). Tutto fail-safe: qualunque errore
# fa ripiegare il retrieval su BM25, senza mai bloccare una risposta in chat.


def _post_ollama_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ollama_embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embeddings per una lista di testi via Ollama nativo.

    Prova prima ``/api/embed`` (batch, Ollama recente), poi ripiega su
    ``/api/embeddings`` per singolo item (API legacy). Ritorna ``None`` su
    qualunque errore o disallineamento (il chiamante usa solo BM25).
    Supportato solo per il provider ``ollama`` (Open WebUI -> solo BM25).
    """
    if not texts:
        return []
    base_url, provider, _model, _timeout = _resolve_ollama_target()
    if provider != "ollama" or not base_url:
        return None
    model = str(getattr(settings, "OLLAMA_EMBED_MODEL", "") or "").strip()
    if not model:
        return None
    timeout = int(getattr(settings, "OLLAMA_EMBED_TIMEOUT_SECONDS", 30) or 30)
    keep_alive = str(getattr(settings, "OLLAMA_KEEP_ALIVE", "") or "").strip()

    batch_payload: dict[str, Any] = {"model": model, "input": texts}
    if keep_alive:
        batch_payload["keep_alive"] = keep_alive
    data = _post_ollama_json(f"{base_url}/api/embed", batch_payload, timeout)
    if isinstance(data, dict):
        vectors = data.get("embeddings")
        if isinstance(vectors, list) and len(vectors) == len(texts):
            try:
                return [[float(x) for x in vec] for vec in vectors]
            except (TypeError, ValueError):
                return None

    # Fallback API legacy /api/embeddings (un item per chiamata).
    out: list[list[float]] = []
    for text in texts:
        legacy_payload: dict[str, Any] = {"model": model, "prompt": text}
        if keep_alive:
            legacy_payload["keep_alive"] = keep_alive
        legacy = _post_ollama_json(f"{base_url}/api/embeddings", legacy_payload, timeout)
        vector = legacy.get("embedding") if isinstance(legacy, dict) else None
        if not isinstance(vector, list) or not vector:
            return None
        try:
            out.append([float(x) for x in vector])
        except (TypeError, ValueError):
            return None
    return out


def _chunk_embed_text(chunk: KnowledgeChunk) -> str:
    return f"{chunk.title}\n{chunk.content}"


def _embeddings_for_chunks(chunks: list[KnowledgeChunk], model: str) -> list[list[float]] | None:
    """Embeddings allineati ai chunk, con cache per content-hash (DatabaseCache).

    Solo i chunk non in cache vengono inviati a Ollama (a batch). Ritorna
    ``None`` se l'embedding non e' disponibile -> retrieval BM25-only.
    """
    if not chunks:
        return []
    persist = bool(getattr(settings, "OLLAMA_EMBED_PERSIST", True))
    cache_keys = [
        "ai_embed:" + hashlib.sha256(f"{model}\n{_chunk_embed_text(c)}".encode("utf-8")).hexdigest()
        for c in chunks
    ]
    cached_map: dict[str, Any] = {}
    if persist:
        try:
            cached_map = cache.get_many(cache_keys) or {}
        except Exception:
            cached_map = {}

    embeddings: list[list[float] | None] = [None] * len(chunks)
    missing: list[int] = []
    for i, key in enumerate(cache_keys):
        vec = cached_map.get(key)
        if isinstance(vec, list) and vec:
            embeddings[i] = [float(x) for x in vec]
        else:
            missing.append(i)

    if missing:
        batch_size = max(1, int(getattr(settings, "OLLAMA_EMBED_BATCH", 16) or 16))
        to_store: dict[str, list[float]] = {}
        for start in range(0, len(missing), batch_size):
            group = missing[start:start + batch_size]
            vectors = _ollama_embed_texts([_chunk_embed_text(chunks[i]) for i in group])
            if vectors is None:
                return None  # embedding non disponibile: niente ramo semantico
            for offset, i in enumerate(group):
                embeddings[i] = vectors[offset]
                to_store[cache_keys[i]] = vectors[offset]
        if persist and to_store:
            ttl = int(getattr(settings, "OLLAMA_EMBED_CACHE_TTL", 2592000) or 2592000)
            try:
                cache.set_many(to_store, timeout=ttl)
            except Exception:
                pass

    if any(vec is None for vec in embeddings):
        return None
    return [vec for vec in embeddings]  # type: ignore[misc]


def _query_embedding(prompt: str) -> list[float] | None:
    vectors = _ollama_embed_texts([prompt])
    if not vectors:
        return None
    return vectors[0]


def embeddings_enabled() -> bool:
    """True se il retrieval/routing semantico via embeddings e' utilizzabile.

    Richiede il flag attivo e il provider Ollama nativo (Open WebUI non supportato
    per gli embeddings in questo stack).
    """
    if not bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False)):
        return False
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    return provider == "ollama"


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """API pubblica per embeddare testi (usata dal routing tool). None su errore."""
    return _ollama_embed_texts(texts)


def cosine_similarity(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    return _cosine_sim(a, b, _l2_norm(a), _l2_norm(b))


def _l2_norm(vector: tuple[float, ...] | list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def _cosine_sim(a: tuple[float, ...] | list[float], b: tuple[float, ...], a_norm: float, b_norm: float) -> float:
    if not a_norm or not b_norm or len(a) != len(b):
        return 0.0
    dot = 0.0
    for x, y in zip(a, b):
        dot += x * y
    return dot / (a_norm * b_norm)


def _rrf_fuse(ranking_a: list[int], ranking_b: list[int], k: int) -> list[int]:
    """Reciprocal Rank Fusion di due ranking (liste di indici chunk ordinate)."""
    scores: dict[int, float] = {}
    for position, idx in enumerate(ranking_a):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + position + 1)
    for position, idx in enumerate(ranking_b):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


def _load_knowledge_index() -> KnowledgeIndex:
    if not bool(getattr(settings, "OLLAMA_RAG_ENABLED", True)):
        return KnowledgeIndex(chunks=(), idf={}, avgdl=0.0)

    files = _iter_knowledge_files()
    signature = (
        tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files),
        _curated_knowledge_signature(),
    )
    ttl = int(getattr(settings, "OLLAMA_RAG_CACHE_SECONDS", 300) or 0)
    now = time.monotonic()
    cached = _KNOWLEDGE_CACHE.get("index")
    if (
        ttl > 0
        and isinstance(cached, KnowledgeIndex)
        and _KNOWLEDGE_CACHE.get("signature") == signature
        and now - float(_KNOWLEDGE_CACHE.get("loaded_at") or 0) < ttl
    ):
        return cached

    max_file_chars = int(getattr(settings, "OLLAMA_RAG_MAX_FILE_CHARS", 300000) or 300000)
    chunks: list[KnowledgeChunk] = []
    for path in files:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = raw_text[:max_file_chars]
        chunks.extend(_chunk_document(path, text))
    chunks.extend(_load_curated_knowledge_chunks())

    index = _build_index(chunks)

    # Arricchimento semantico opzionale (fail-safe: se fallisce resta BM25-only).
    if chunks and bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False)):
        embed_model = str(getattr(settings, "OLLAMA_EMBED_MODEL", "") or "").strip()
        if embed_model:
            vectors = _embeddings_for_chunks(chunks, embed_model)
            if vectors:
                index = replace(
                    index,
                    embeddings=tuple(tuple(vec) for vec in vectors),
                    embed_norms=tuple(_l2_norm(vec) for vec in vectors),
                    embed_model=embed_model,
                )

    _KNOWLEDGE_CACHE.update({"loaded_at": now, "signature": signature, "index": index})
    return index


def _bm25_score(
    query_tokens: Counter[str],
    chunk: KnowledgeChunk,
    idf: dict[str, float],
    avgdl: float,
) -> float:
    """Okapi BM25 con boost per i token che compaiono nel titolo della sezione."""
    k1 = float(getattr(settings, "OLLAMA_RAG_BM25_K1", 1.5) or 1.5)
    b = float(getattr(settings, "OLLAMA_RAG_BM25_B", 0.75) or 0.75)
    doc_length = sum(chunk.tokens.values()) or 1
    norm = k1 * (1.0 - b + b * (doc_length / avgdl if avgdl else 1.0))
    title_tokens = set(_tokenize(chunk.title))
    score = 0.0
    for token in query_tokens:
        frequency = chunk.tokens.get(token, 0)
        if frequency:
            score += idf.get(token, 0.0) * (frequency * (k1 + 1.0)) / (frequency + norm)
        if token in title_tokens:
            score += 2.5
    return score


def _bm25_ranking(query_tokens: Counter[str], index: KnowledgeIndex) -> list[int]:
    if not query_tokens:
        return []
    scored = [
        (i, _bm25_score(query_tokens, index.chunks[i], index.idf, index.avgdl))
        for i in range(len(index.chunks))
    ]
    return [i for i, score in sorted(scored, key=lambda kv: kv[1], reverse=True) if score > 0]


def _semantic_ranking(prompt: str, index: KnowledgeIndex) -> list[int]:
    if index.embeddings is None or not prompt.strip():
        return []
    query_vector = _query_embedding(prompt)
    if not query_vector:
        return []
    query_norm = _l2_norm(query_vector)
    if not query_norm:
        return []
    sims = [
        (i, _cosine_sim(query_vector, index.embeddings[i], query_norm, index.embed_norms[i]))
        for i in range(len(index.chunks))
    ]
    return [i for i, sim in sorted(sims, key=lambda kv: kv[1], reverse=True) if sim > 0]


def _select_chunk_indices(prompt: str, query_tokens: Counter[str], index: KnowledgeIndex) -> list[int]:
    """Indici dei chunk da usare: ibrido BM25+semantico (RRF) o BM25-only."""
    bm25_ranked = _bm25_ranking(query_tokens, index)
    semantic_ranked = _semantic_ranking(prompt, index)
    if semantic_ranked:
        max_chunks = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
        pool = max(max_chunks * 5, 20)
        rrf_k = int(getattr(settings, "OLLAMA_RAG_HYBRID_RRF_K", 60) or 60)
        return _rrf_fuse(bm25_ranked[:pool], semantic_ranked[:pool], rrf_k)
    return bm25_ranked


def build_knowledge_context(prompt: str) -> KnowledgeContext:
    index = _load_knowledge_index()
    if not index.chunks:
        return KnowledgeContext(text="", sources=())

    query_tokens = Counter(_tokenize(prompt))
    selected_indices = _select_chunk_indices(prompt, query_tokens, index)
    if not selected_indices:
        return KnowledgeContext(text="", sources=())

    max_chunks = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
    max_context_chars = int(getattr(settings, "OLLAMA_RAG_MAX_CONTEXT_CHARS", 5000) or 5000)
    selected = [index.chunks[i] for i in selected_indices[:max_chunks]]

    blocks: list[str] = []
    sources: list[str] = []
    current_chars = 0
    for chunk in selected:
        header = f"[fonte: {chunk.source} > {chunk.title}]"
        block = f"{header}\n{chunk.content}".strip()
        remaining = max_context_chars - current_chars
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining].rstrip()
        blocks.append(block)
        current_chars += len(block) + 2
        label = f"{chunk.source} > {chunk.title}"
        if label not in sources:
            sources.append(label)

    return KnowledgeContext(text="\n\n".join(blocks).strip(), sources=tuple(sources))


def _clean_history(raw_history: Any, *, max_messages: int, max_chars: int) -> list[dict[str, str]]:
    if not isinstance(raw_history, list):
        return []

    cleaned: list[dict[str, str]] = []
    for item in raw_history[-max_messages:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clean_text(item.get("content"), limit=max_chars)
        if content:
            cleaned.append({"role": role, "content": content})
    return cleaned


def build_ollama_messages(
    prompt: str,
    history: Any = None,
    *,
    knowledge_context: str = "",
    runtime_context: str = "",
    user_preferences: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    max_prompt_chars = int(getattr(settings, "OLLAMA_CHAT_MAX_PROMPT_CHARS", 2000) or 2000)
    max_history_messages = int(getattr(settings, "OLLAMA_CHAT_MAX_HISTORY_MESSAGES", 6) or 6)
    max_system_chars = int(getattr(settings, "OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS", 800) or 800)
    system_prompt = _clean_text(
        getattr(settings, "OLLAMA_CHAT_SYSTEM_PROMPT", ""),
        limit=max_system_chars,
    )
    user_prompt = _clean_text(prompt, limit=max_prompt_chars)
    if not user_prompt:
        raise OllamaChatError("Scrivi un messaggio prima di inviare.")

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    preferences_prompt = _build_preferences_prompt(user_preferences)
    if preferences_prompt:
        messages.append({"role": "system", "content": preferences_prompt})
    # Il contesto live viene inserito PRIMA dei documenti RAG: ha priorità assoluta
    # e deve essere il riferimento principale per domande su dati operativi.
    if runtime_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "CONTESTO LIVE AUTORIZZATO DAL PORTALE:\n"
                    f"{runtime_context}\n\n"
                    "ISTRUZIONE: questo contesto contiene dati reali del portale filtrati con i permessi "
                    "dell'utente. Usalo come fonte principale e definitiva per rispondere. "
                    "Cita le fonti tool:* quando usi questi dati. "
                    "Se il contesto contiene una sezione RISPOSTA DIRETTA, riportala come risposta principale. "
                    "Non aggiungere nominativi o dettagli non presenti nel contesto. "
                    "Se il dato non e' qui, dillo esplicitamente senza inventare procedure, comandi o sezioni. "
                    "Per richieste predittive separa fatti osservati, ipotesi e raccomandazioni."
                ),
            }
        )
    if knowledge_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "CONTESTO PORTALE RECUPERATO DA DOCUMENTI INTERNI:\n"
                    f"{knowledge_context}\n\n"
                    "Usa questo contesto solo per domande su configurazione, architettura o funzionamento del portale, "
                    "e solo se non e' gia presente un contesto live pertinente. "
                    "Cita le fonti presenti nel contesto tra parentesi."
                ),
            }
        )
    messages.extend(
        _clean_history(
            history,
            max_messages=max_history_messages,
            max_chars=max_prompt_chars,
        )
    )
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _build_preferences_prompt(user_preferences: dict[str, Any] | None) -> str:
    if not isinstance(user_preferences, dict):
        return ""
    style = str(user_preferences.get("style") or "").strip().lower()
    style_map = {
        "operativo": "Rispondi in modo operativo: dato principale, fonte, prossimo passo solo se utile.",
        "sintetico": "Rispondi in modo sintetico: massimo 3-5 righe quando il contenuto lo consente.",
        "dettagliato": "Rispondi in modo dettagliato: includi criteri, filtri applicati e assunzioni esplicite.",
    }
    lines: list[str] = []
    if style in style_map:
        lines.append(style_map[style])
    if bool(user_preferences.get("show_limits")):
        lines.append(
            "Quando non puoi rispondere o agire, spiega in una riga il limite: permesso mancante, tool live assente, "
            "dato non presente nel contesto o azione non abilitata."
        )
    if not lines:
        return ""
    lines.append(
        "Queste preferenze non autorizzano nuovi dati, non cambiano ACL/permessi e non permettono di inventare dati assenti."
    )
    return "PREFERENZE DI RISPOSTA DELL'UTENTE:\n" + "\n".join(f"- {line}" for line in lines)


def _apply_ollama_tuning(payload: dict[str, Any], provider: str) -> None:
    """Applica temperatura e opzioni runtime al payload chat.

    Open WebUI (OpenAI-compatibile): solo temperatura a livello top.
    Ollama nativo: ``options`` (temperature, num_ctx, num_predict) + ``keep_alive``
    top-level per tenere il modello caldo in memoria e ridurre la latenza al
    primo token dopo un periodo di inattivita'.
    """
    temperature = getattr(settings, "OLLAMA_CHAT_TEMPERATURE", None)
    temp_value: float | None = None
    if temperature is not None:
        try:
            temp_value = float(temperature)
        except (TypeError, ValueError):
            temp_value = None

    if provider == "openwebui":
        if temp_value is not None:
            payload["temperature"] = temp_value
        return

    options: dict[str, Any] = {}
    if temp_value is not None:
        options["temperature"] = temp_value
    num_ctx = int(getattr(settings, "OLLAMA_NUM_CTX", 0) or 0)
    if num_ctx > 0:
        options["num_ctx"] = num_ctx
    num_predict = int(getattr(settings, "OLLAMA_NUM_PREDICT", 0) or 0)
    if num_predict > 0:
        options["num_predict"] = num_predict
    if options:
        payload["options"] = options
    keep_alive = str(getattr(settings, "OLLAMA_KEEP_ALIVE", "") or "").strip()
    if keep_alive:
        payload["keep_alive"] = keep_alive


def chat_with_ollama(
    prompt: str,
    history: Any = None,
    *,
    runtime_context: str = "",
    user_preferences: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> OllamaChatResult:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    timeout = int(timeout) if timeout else int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60)
    if not base_url:
        raise OllamaChatError("OLLAMA_BASE_URL non configurato.")
    if not model:
        raise OllamaChatError("OLLAMA_CHAT_MODEL non configurato.")

    knowledge = build_knowledge_context(prompt)
    has_runtime_context = bool(runtime_context.strip())
    # Se c'è un contesto live (dati operativi reali), non iniettare il RAG nel payload:
    # i modelli small ignorano l'istruzione "ignora i documenti se c'è contesto live"
    # e confondono le due fonti. Anche le fonti RAG restano nascoste nella UI quando risponde un tool live.
    rag_for_llm = "" if has_runtime_context else knowledge.text
    payload = {
        "model": model,
        "messages": build_ollama_messages(
            prompt,
            history,
            knowledge_context=rag_for_llm,
            runtime_context=runtime_context,
            user_preferences=user_preferences,
        ),
        "stream": False,
    }
    _apply_ollama_tuning(payload, provider)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if provider == "openwebui":
        api_key = str(getattr(settings, "OPENWEBUI_API_KEY", "") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        endpoint = f"{base_url}/api/chat/completions"
    else:
        endpoint = f"{base_url}/api/chat"

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        hint = _ollama_endpoint_hint(base_url, http_status=exc.code)
        if provider == "openwebui" and exc.code in {401, 403}:
            hint = "Rigenera la API key in Open WebUI e salvala nella console Gestione AI."
        raise OllamaChatError(f"Ollama ha risposto con HTTP {exc.code}: {detail[:300]} {hint}") from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise OllamaChatError(_timeout_message(timeout)) from exc
        raise OllamaChatError(f"Ollama non raggiungibile: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OllamaChatError(_timeout_message(timeout)) from exc
    except OSError as exc:
        raise OllamaChatError(f"Errore di rete verso Ollama: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaChatError("Ollama ha restituito JSON non valido.") from exc

    content = ""
    if isinstance(data, dict) and provider == "openwebui":
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = str(message.get("content") or "").strip()
    else:
        message = data.get("message") if isinstance(data, dict) else None
        if isinstance(message, dict):
            content = str(message.get("content") or "").strip()
        if not content and isinstance(data, dict):
            content = str(data.get("response") or "").strip()
    if not content:
        raise OllamaChatError("Ollama non ha restituito contenuto.")

    return OllamaChatResult(
        content=content,
        model=str(data.get("model") or model) if isinstance(data, dict) else model,
        done=bool(data.get("done", True)) if isinstance(data, dict) else True,
        sources=() if has_runtime_context else knowledge.sources,
        rag_context_chars=0 if has_runtime_context else len(knowledge.text),
    )


def _resolve_ollama_target() -> tuple[str, str, str, int]:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    timeout = int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60)
    return base_url, provider, model, timeout


def open_ollama_stream(
    prompt: str,
    history: Any = None,
    *,
    runtime_context: str = "",
    user_preferences: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Apre una richiesta streaming verso Ollama/Open WebUI.

    Esegue tutta la fase di setup in modo sincrono (validazione config, RAG,
    apertura connessione): eventuali errori vengono sollevati come
    ``OllamaChatError`` PRIMA che inizi lo streaming, cosi' la view puo' ancora
    restituire uno status HTTP corretto. Ritorna ``(response, meta)`` dove
    ``response`` e' lo stream HTTP aperto e ``meta`` contiene model/provider/fonti.
    """
    base_url, provider, model, timeout = _resolve_ollama_target()
    if not base_url:
        raise OllamaChatError("OLLAMA_BASE_URL non configurato.")
    if not model:
        raise OllamaChatError("OLLAMA_CHAT_MODEL non configurato.")

    knowledge = build_knowledge_context(prompt)
    has_runtime_context = bool(runtime_context.strip())
    rag_for_llm = "" if has_runtime_context else knowledge.text
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_ollama_messages(
            prompt,
            history,
            knowledge_context=rag_for_llm,
            runtime_context=runtime_context,
            user_preferences=user_preferences,
        ),
        "stream": True,
    }
    _apply_ollama_tuning(payload, provider)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if provider == "openwebui":
        api_key = str(getattr(settings, "OPENWEBUI_API_KEY", "") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        endpoint = f"{base_url}/api/chat/completions"
    else:
        endpoint = f"{base_url}/api/chat"

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        hint = _ollama_endpoint_hint(base_url, http_status=exc.code)
        if provider == "openwebui" and exc.code in {401, 403}:
            hint = "Rigenera la API key in Open WebUI e salvala nella console Gestione AI."
        raise OllamaChatError(f"Ollama ha risposto con HTTP {exc.code}: {detail[:300]} {hint}") from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise OllamaChatError(_timeout_message(timeout)) from exc
        raise OllamaChatError(f"Ollama non raggiungibile: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OllamaChatError(_timeout_message(timeout)) from exc
    except OSError as exc:
        raise OllamaChatError(f"Errore di rete verso Ollama: {exc}") from exc

    meta = {
        "model": model,
        "provider": provider,
        "sources": () if has_runtime_context else knowledge.sources,
        "rag_context_chars": 0 if has_runtime_context else len(knowledge.text),
    }
    return response, meta


def iter_ollama_stream(response: Any, provider: str = "ollama"):
    """Itera lo stream HTTP di Ollama/Open WebUI restituendo i delta di testo.

    Tollerante alle righe vuote e ai frammenti JSON non parsabili. Chiude sempre
    la connessione al termine (anche su eccezione del consumatore).
    """
    provider = str(provider or "ollama").strip().lower()
    try:
        for raw_line in response:
            try:
                line = raw_line.decode("utf-8", errors="replace").strip()
            except AttributeError:
                line = str(raw_line).strip()
            if not line:
                continue
            if provider == "openwebui":
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line:
                    continue
                if line == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices") if isinstance(data, dict) else None
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    delta = choices[0].get("delta")
                    piece = str(delta.get("content") or "") if isinstance(delta, dict) else ""
                    if piece:
                        yield piece
                    if choices[0].get("finish_reason"):
                        break
            else:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                message = data.get("message")
                if isinstance(message, dict):
                    piece = str(message.get("content") or "")
                    if piece:
                        yield piece
                if data.get("done"):
                    break
    finally:
        try:
            response.close()
        except Exception:
            pass
