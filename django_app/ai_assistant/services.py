from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings


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


_RAG_ALLOWED_EXTENSIONS = {".md", ".txt", ".rst"}
_RAG_STOPWORDS = {
    "anche",
    "come",
    "con",
    "del",
    "della",
    "delle",
    "degli",
    "dei",
    "gli",
    "per",
    "che",
    "non",
    "una",
    "uno",
    "sul",
    "sulla",
    "sono",
    "nel",
    "nelle",
    "dagli",
    "dal",
    "alla",
    "alle",
    "dove",
    "cosa",
}
_KNOWLEDGE_CACHE: dict[str, Any] = {"loaded_at": 0.0, "signature": (), "chunks": []}


def clear_knowledge_cache() -> None:
    _KNOWLEDGE_CACHE.update({"loaded_at": 0.0, "signature": (), "chunks": []})


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


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9_À-ÿ]{3,}", value.lower())
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


def _split_long_section(source: str, title: str, content: str, *, max_chars: int) -> list[KnowledgeChunk]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
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
            current = paragraph
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


def _load_knowledge_chunks() -> list[KnowledgeChunk]:
    if not bool(getattr(settings, "OLLAMA_RAG_ENABLED", True)):
        return []

    files = _iter_knowledge_files()
    signature = (
        tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files),
        _curated_knowledge_signature(),
    )
    ttl = int(getattr(settings, "OLLAMA_RAG_CACHE_SECONDS", 300) or 0)
    now = time.monotonic()
    if (
        ttl > 0
        and _KNOWLEDGE_CACHE.get("signature") == signature
        and now - float(_KNOWLEDGE_CACHE.get("loaded_at") or 0) < ttl
    ):
        return list(_KNOWLEDGE_CACHE.get("chunks") or [])

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

    _KNOWLEDGE_CACHE.update({"loaded_at": now, "signature": signature, "chunks": chunks})
    return chunks


def _score_chunk(query_tokens: Counter[str], chunk: KnowledgeChunk) -> float:
    score = 0.0
    title_tokens = set(_tokenize(chunk.title))
    for token, weight in query_tokens.items():
        occurrences = min(chunk.tokens.get(token, 0), 4)
        if occurrences:
            score += occurrences * (1.0 + min(weight, 3) * 0.2)
        if token in title_tokens:
            score += 2.5
    return score


def build_knowledge_context(prompt: str) -> KnowledgeContext:
    query_tokens = Counter(_tokenize(prompt))
    if not query_tokens:
        return KnowledgeContext(text="", sources=())

    scored_chunks = [
        (score, chunk)
        for chunk in _load_knowledge_chunks()
        if (score := _score_chunk(query_tokens, chunk)) > 0
    ]
    if not scored_chunks:
        return KnowledgeContext(text="", sources=())

    scored_chunks.sort(key=lambda item: item[0], reverse=True)
    max_chunks = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
    max_context_chars = int(getattr(settings, "OLLAMA_RAG_MAX_CONTEXT_CHARS", 5000) or 5000)
    selected = [chunk for _score, chunk in scored_chunks[:max_chunks]]

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


def chat_with_ollama(
    prompt: str,
    history: Any = None,
    *,
    runtime_context: str = "",
    user_preferences: dict[str, Any] | None = None,
) -> OllamaChatResult:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    timeout = int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60)
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
    temperature = getattr(settings, "OLLAMA_CHAT_TEMPERATURE", None)
    if temperature is not None:
        try:
            temp_value = float(temperature)
            if provider == "openwebui":
                payload["temperature"] = temp_value
            else:
                payload["options"] = {"temperature": temp_value}
        except (TypeError, ValueError):
            pass

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
