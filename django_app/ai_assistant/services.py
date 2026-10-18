from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import math
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

from . import glossario_rag, guide_portale

logger = logging.getLogger(__name__)


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
    # Token del titolo, precalcolati da _build_index (boost BM25): a ogni ricerca si
    # tokenizza solo la query, mai i chunk (pre-pass del glossario compreso).
    title_tokens: frozenset[str] | None = field(default=None, compare=False, repr=False)


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
    # Matrice numpy float32 (una riga per chunk, gia' normalizzata L2): il coseno
    # con la query e' un solo prodotto matrice-vettore (~ms invece di ~1,5 s in
    # Python puro su ~9.000 chunk) e occupa ~6 volte meno RAM delle tuple di float.
    embeddings: Any = field(default=None, compare=False, repr=False)
    embed_model: str = ""
    # Chiavi cache degli embeddings, allineate ai chunk: al rebuild successivo i
    # vettori dei chunk invariati si riprendono da qui senza rileggere la cache DB.
    embed_keys: tuple[str, ...] = field(default=(), compare=False, repr=False)
    # Indice invertito token -> chunk: BM25 valuta solo i chunk che contengono
    # almeno un token della domanda (nel testo o nel titolo), non tutto il corpus.
    postings: dict[str, tuple[int, ...]] | None = field(default=None, compare=False, repr=False)


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
_KNOWLEDGE_CACHE: dict[str, Any] = {
    "loaded_at": 0.0, "signature": (), "index": None, "complete": True, "rebuilding": False,
}
_KNOWLEDGE_BUILD_LOCK = threading.Lock()
# Testo PDF SGI gia' estratto, per content-hash (stesso hash = stesso testo): evita di
# rileggere ~250 documenti dalla cache DB a ogni rebuild dell'indice.
_SGI_TEXT_MEMO: dict[str, str] = {}
_SGI_TEXT_MEMO_MAX = 2000


def clear_knowledge_cache() -> None:
    _KNOWLEDGE_CACHE.update({"loaded_at": 0.0, "signature": (), "index": None, "complete": True})
    _SGI_TEXT_MEMO.clear()


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


# Stemmer italiano opt-in (OLLAMA_RAG_STEMMING_ENABLED). snowballstemmer e'
# pure-python; se la dipendenza manca o il flag e' spento la tokenizzazione resta
# invariata (fail-safe). Lo stemmer e' applicato in modo identico a chunk e query,
# quindi "timbri"/"timbro"/"timbrare" collassano sullo stesso token ("timbr").
_STEMMER_CACHE: dict[str, Any] = {"loaded": False, "stemmer": None}


def _get_italian_stemmer():
    if not _STEMMER_CACHE["loaded"]:
        try:
            import snowballstemmer

            _STEMMER_CACHE["stemmer"] = snowballstemmer.stemmer("italian")
        except Exception:
            _STEMMER_CACHE["stemmer"] = None
        _STEMMER_CACHE["loaded"] = True
    return _STEMMER_CACHE["stemmer"]


def _tokenize(value: str) -> list[str]:
    folded = _fold_accents(value.lower())
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_]{3,}", folded)
        if token not in _RAG_STOPWORDS
    ]
    # Stemming opt-in: dopo la rimozione stopword (queste sono non-stemmate), così
    # query e chunk condividono la stessa radice. Fail-safe se la dipendenza manca.
    if tokens and bool(getattr(settings, "OLLAMA_RAG_STEMMING_ENABLED", False)):
        stemmer = _get_italian_stemmer()
        if stemmer is not None:
            tokens = [stemmer.stemWord(token) for token in tokens]
    # Glossario tecnico (OLLAMA_RAG_GLOSSARIO_ENABLED): token canonici gl_<id> e pattern
    # protetti (H7, M8, Ra) che la regex sopra scarta. A flag spento non aggiunge nulla.
    extra = glossario_rag.token_aggiuntivi(value)
    if extra:
        tokens.extend(extra)
    return tokens


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
    if text.rsplit("\n", 1)[-1].lstrip().startswith("|"):
        # Coda di una pipe-table: solo righe intere, mai un frammento di riga.
        newline = tail.find("\n")
        return tail[newline + 1:] if newline != -1 else ""
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def _split_long_section(source: str, title: str, content: str, *, max_chars: int) -> list[KnowledgeChunk]:
    raw_paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    # Spezza i paragrafi piu' lunghi di max_chars: i PDF spesso estraggono il testo
    # come UN UNICO blocco senza righe vuote -> senza questo taglio si formerebbe un
    # chunk enorme che sfonda il limite di token del modello di embedding (TEI/Ollama
    # restituiscono errore -> tutto il warm fallisce). Niente piu' chunk > max_chars.
    paragraphs: list[str] = []
    for part in raw_paragraphs:
        if len(part) <= max_chars:
            paragraphs.append(part)
        else:
            paragraphs.extend(part[k:k + max_chars] for k in range(0, len(part), max_chars))
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


def _load_glossario_chunks() -> list[KnowledgeChunk]:
    """Termini del glossario tecnico come conoscenza curata (OLLAMA_RAG_GLOSSARIO_ENABLED).

    Un chunk per termine: definizione, varianti, simbolo, esempio a disegno e codice norma. Fonte
    ``glossario:<id>#<termine>``. Solo termini validati con «usa nell'assistente»
    (le bozze solo con OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE, strumento di misura in dev).
    Le note interne non entrano mai.
    """
    chunks: list[KnowledgeChunk] = []
    for voce in glossario_rag.voci_per_chunk():
        termine = _clean_text(voce.termine, limit=150)
        if not termine:
            continue
        righe = [f"{termine}" + (f" (EN: {voce.termine_en})" if voce.termine_en else "")]
        if voce.categoria:
            righe.append(f"Categoria: {voce.categoria}")
        righe.append(f"Definizione: {_clean_text(voce.definizione, limit=700)}")
        if voce.varianti:
            righe.append("Detto anche: " + ", ".join(voce.varianti[:20]))
        if voce.simbolo:
            righe.append(f"Simbolo: {voce.simbolo}")
        if voce.esempio_disegno:
            # Deviazione approvata da §B2.2: l'esempio («⌀20 H7») porta i token protetti.
            righe.append(f"Esempio a disegno: {_clean_text(voce.esempio_disegno, limit=200)}")
        if voce.norma_rif:
            righe.append(f"Norma: {voce.norma_rif}")
        content = "\n".join(righe)
        title = f"Glossario — {termine}"
        slug = re.sub(r"\s+", "-", _fold_accents(termine.lower())).strip("-")
        chunks.append(
            KnowledgeChunk(
                source=f"glossario:{voce.id}#{slug}",
                title=title,
                content=content,
                tokens=Counter(_tokenize(f"{title}\n{content}")),
            )
        )
    return chunks


def _load_guide_chunks() -> list[KnowledgeChunk]:
    """Capitoli delle guide in-app dei moduli (fonte ``guida:<slug>``).

    Ogni chunk porta nel testo modulo e link della guida, così la risposta può
    indicare dove aprirla. Il gate ACL è a valle, in ``build_knowledge_context``.
    """
    max_chars = int(getattr(settings, "OLLAMA_RAG_CHUNK_CHARS", 1600) or 1600)
    chunks: list[KnowledgeChunk] = []
    for numero, sezione in enumerate(guide_portale.sezioni()):
        title = f"Guida {sezione.modulo} — {sezione.titolo}"[:200]
        header = f"{title}\nGuida completa nel portale: {sezione.url}\n"
        budget = max(200, max_chars - len(header))
        source = f"{guide_portale.SOURCE_PREFIX}{sezione.slug}#{numero}"
        # Le parole del modulo («timbro», «firma»...) contano come titolo nel BM25:
        # «nuovo timbro» deve preferire i capitoli del Registro Timbri.
        title_tokens = frozenset(_tokenize(f"{title} {sezione.parole}"))
        for piece in _split_long_section(source, title, sezione.testo, max_chars=budget):
            content = header + piece.content
            chunks.append(
                KnowledgeChunk(
                    source=source,
                    title=title,
                    content=content,
                    tokens=Counter(_tokenize(f"{title}\n{sezione.parole}\n{content}")),
                    title_tokens=title_tokens,
                )
            )
    return chunks


def _guide_enabled() -> bool:
    return bool(getattr(settings, "OLLAMA_RAG_GUIDE_ENABLED", True))


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


# ── Corpus documentale SGI (specifiche + procedure correnti) ────────────────
# Loader gemello di `_load_curated_knowledge_chunks`: indicizza il testo dei
# documenti SGI gia' presenti nel portale rendendoli citabili in chat (handle
# stabile `spec:`/`proc:`). Solo revisioni in vigore. Tutto fail-safe: app
# assente, PDF illeggibile o Ollama offline saltano il singolo documento senza
# mai propagare un'eccezione (coerente con gli altri loader). On-premise: per le
# procedure si legge solo il file server locale; SharePoint -> fallback metadati.

# Heading di sezione numerata (es. "4.2 Registrazione timbri", "§4.2 Titolo",
# "4.2) Titolo"): chiave per il chunking sezione-aware, cosi' la citazione puo'
# riportare il paragrafo (§4.2) e non solo il documento.
_SGI_HEADING_RE = re.compile(r"^\s*(?:§\s*)?(\d{1,2}(?:\.\d{1,3}){0,4})[.)]?\s+(\S.+?)\s*$")


def _extract_pdf_text(source: Any) -> str:
    """Estrae il testo da un PDF (FieldFile, path o bytes) con pymupdf.

    Replica il pattern di ``gestione_specifiche.ai_copilota._estrai_testo_pdf``
    mantenendo ``ai_assistant`` autonomo (nessun import cross-app). Fail-safe:
    pymupdf assente, file mancante o PDF corrotto -> stringa vuota (il chunk viene
    saltato o ripiega sui metadati), mai un'eccezione propagata.
    """
    if not source:
        return ""
    try:
        import fitz  # pymupdf
    except Exception:
        return ""
    try:
        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        elif hasattr(source, "open"):  # Django FieldFile
            with source.open("rb") as fh:
                data = fh.read()
        elif isinstance(source, (str, Path)):
            data = Path(source).read_bytes()
        else:
            return ""
        if not data:
            return ""
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        logger.debug("ai_assistant: estrazione PDF SGI fallita: %s", exc)
        return ""


def _sgi_sections(text: str) -> list[tuple[str, str]]:
    """Spezza il testo del documento in sezioni numerate (etichetta, contenuto).

    Una riga e' heading se combacia con ``_SGI_HEADING_RE``, e' corta (titolo, non
    un paragrafo) e ha almeno una lettera. Senza heading riconosciuti ritorna
    un'unica sezione con etichetta vuota (il chiamante usa il titolo del documento).
    """
    sections: list[tuple[str, list[str]]] = []
    title = ""
    lines: list[str] = []
    for line in text.splitlines():
        match = _SGI_HEADING_RE.match(line)
        is_heading = bool(
            match
            and len(line.strip()) <= 90
            and any(ch.isalpha() for ch in match.group(2))
        )
        if is_heading:
            if title or lines:
                sections.append((title, lines))
            title = f"§{match.group(1)} {match.group(2).strip()}"[:160]
            lines = [line]
        else:
            lines.append(line)
    if title or lines:
        sections.append((title, lines))
    return [
        (label, "\n".join(body).strip())
        for label, body in sections
        if "\n".join(body).strip()
    ]


def _sgi_chunks_from_text(*, source: str, doc_label: str, text: str, max_chars: int) -> list[KnowledgeChunk]:
    """Costruisce i chunk citabili di un documento: sezione-aware + split lungo.

    Con ``OLLAMA_RAG_SGI_CHUNK_HEADER`` ogni chunk porta anche nel TESTO
    l'intestazione ``"<codice> Rev.<n> — <§ sezione>"`` (oggi è solo nel titolo):
    gli embeddings vedono a quale documento/sezione appartiene il frammento. Le
    tabelle in pipe-table non vengono mai spezzate a metà riga.
    """
    header_on = bool(getattr(settings, "OLLAMA_RAG_SGI_CHUNK_HEADER", False))
    chunks: list[KnowledgeChunk] = []
    for label, body in _sgi_sections(text):
        title = f"{doc_label} — {label}" if label else doc_label
        if not header_on:
            chunks.extend(_split_long_section(source, title, _sgi_split_tables(body, _sgi_table_budget(max_chars)), max_chars=max_chars))
            continue
        header = title + "\n"
        budget = max(200, max_chars - len(header))
        for piece in _split_long_section(source, title, _sgi_split_tables(body, _sgi_table_budget(budget)), max_chars=budget):
            content = header + piece.content
            chunks.append(
                KnowledgeChunk(
                    source=piece.source,
                    title=piece.title,
                    content=content,
                    tokens=Counter(_tokenize(f"{title}\n{content}")),
                )
            )
    return chunks


def _sgi_table_budget(max_chars: int) -> int:
    """Dimensione dei pezzi di tabella: lascia spazio all'overlap, che a valle viene
    anteposto al pezzo (e l'ultimo chunk e' troncato a max_chars)."""
    overlap = int(getattr(settings, "OLLAMA_RAG_CHUNK_OVERLAP_CHARS", 0) or 0)
    return max(100, max_chars - overlap)


def _sgi_doc_label(code: str, rev: str, title: str = "") -> str:
    """Etichetta del documento nei chunk SGI: ``"<codice> Rev.<n>"``.

    Con ``OLLAMA_RAG_SGI_CHUNK_TITLE`` aggiunge il titolo del documento: ogni
    frammento sa di che documento parla anche quando il testo non lo ripete
    (misura A1 in dev: ``ai_eval --rag-sgi`` recall 27->31/32, MRR 0,623 -> 0,772).
    """
    label = f"{code} Rev.{rev}" if rev else code
    if not getattr(settings, "OLLAMA_RAG_SGI_CHUNK_TITLE", False):
        return label
    clean_title = _clean_text(title, limit=120)
    if clean_title and clean_title.lower() != (code or "").lower():
        label = f"{label} {clean_title}"
    return label

def _sgi_split_tables(body: str, max_chars: int) -> str:
    """Spezza le pipe-table più lunghe di ``max_chars`` in paragrafi per righe intere,
    ripetendo l'intestazione: lo split a caratteri a valle non taglia più una riga.

    Testo senza pipe-table (estrazione "piatta") -> ritornato identico.
    """
    if "\n|" not in "\n" + body:
        return body
    out: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        if len(para) <= max_chars:
            out.append(para)
            continue
        # Separa le righe di tabella dal testo attorno (es. heading di sezione).
        runs: list[tuple[bool, list[str]]] = []
        for ln in para.splitlines():
            is_row = ln.lstrip().startswith("|")
            if runs and runs[-1][0] == is_row:
                runs[-1][1].append(ln)
            else:
                runs.append((is_row, [ln]))
        for is_row, lines in runs:
            text = "\n".join(lines)
            if not is_row or len(lines) < 3 or len(text) <= max_chars:
                out.append(text)
                continue
            out.extend(_sgi_table_pieces(lines, max_chars))
    return "\n\n".join(out)


def _sgi_table_pieces(lines: list[str], max_chars: int) -> list[str]:
    """Pezzi di una pipe-table per righe intere, intestazione ripetuta in ognuno."""
    out: list[str] = []
    head = lines[:2]
    head_len = sum(len(h) + 1 for h in head)
    current: list[str] = []
    size = head_len
    for row in lines[2:]:
        if current and size + len(row) + 1 > max_chars:
            out.append("\n".join(head + current))
            current, size = [], head_len
        current.append(row)
        size += len(row) + 1
    if current:
        out.append("\n".join(head + current))
    return out


def _sgi_chunk_chars() -> int:
    """Dimensione chunk SGI (OLLAMA_RAG_SGI_CHUNK_CHARS, default = OLLAMA_RAG_CHUNK_CHARS)."""
    base = int(getattr(settings, "OLLAMA_RAG_CHUNK_CHARS", 900) or 900)
    return int(getattr(settings, "OLLAMA_RAG_SGI_CHUNK_CHARS", base) or base)


def _sgi_text_cache_key(file_hash: str) -> str:
    return "ai_sgi_text:" + file_hash


def _sgi_cached_text(file_hash: str) -> str | None:
    """Testo PDF estratto in cache (DatabaseCache) per content-hash. None = miss."""
    if not file_hash:
        return None
    memo = _SGI_TEXT_MEMO.get(file_hash)
    if memo is not None:
        return memo
    try:
        value = cache.get(_sgi_text_cache_key(file_hash))
    except Exception:
        return None
    if not isinstance(value, str):
        return None
    _sgi_memo_text(file_hash, value)
    return value


def _sgi_memo_text(file_hash: str, text: str) -> None:
    if len(_SGI_TEXT_MEMO) >= _SGI_TEXT_MEMO_MAX:
        _SGI_TEXT_MEMO.clear()
    _SGI_TEXT_MEMO[file_hash] = text


def _sgi_store_text(file_hash: str, text: str) -> None:
    if not file_hash:
        return
    ttl = int(getattr(settings, "OLLAMA_RAG_SGI_TEXT_CACHE_TTL", 2592000) or 2592000)
    _sgi_memo_text(file_hash, text)
    try:
        cache.set(_sgi_text_cache_key(file_hash), text, timeout=ttl)
    except Exception:
        pass


def _sgi_spec_hash_cache_key(spec) -> str:
    """Chiave cache (pk, updated_at) -> file_hash per la Specifica.

    La Specifica non persiste un hash del PDF: lo deriviamo dai byte una sola
    volta e lo cachiamo per (pk, updated_at), cosi' i rebuild a caldo dell'indice
    non rileggono il file finche' il documento non cambia.
    """
    updated = getattr(spec, "updated_at", None)
    stamp = updated.isoformat() if updated else ""
    return "ai_sgi_hash:spec:" + hashlib.sha256(f"{spec.pk}\n{stamp}".encode("utf-8")).hexdigest()


def _sgi_cached_spec_hash(spec) -> str:
    try:
        value = cache.get(_sgi_spec_hash_cache_key(spec))
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _sgi_store_spec_hash(spec, file_hash: str) -> None:
    ttl = int(getattr(settings, "OLLAMA_RAG_SGI_TEXT_CACHE_TTL", 2592000) or 2592000)
    try:
        cache.set(_sgi_spec_hash_cache_key(spec), file_hash, timeout=ttl)
    except Exception:
        pass


def _sgi_extract_specifica_text(spec) -> str:
    """Testo PDF della Specifica con doppia cache (hash per pk+updated_at, testo
    per file_hash). I byte si leggono al piu' una volta per rebuild (solo su miss).
    """
    allegato = getattr(spec, "allegato", None)
    if not allegato:
        return ""
    max_pdf_chars = int(getattr(settings, "OLLAMA_RAG_SGI_MAX_PDF_CHARS", 200000) or 200000)
    file_hash = _sgi_cached_spec_hash(spec)
    if file_hash:
        cached = _sgi_cached_text(file_hash)
        if cached is not None:
            return cached[:max_pdf_chars]
    # Miss: leggi i byte UNA volta -> hash + estrazione.
    try:
        with allegato.open("rb") as fh:
            data = fh.read()
    except Exception as exc:
        logger.debug("ai_assistant: lettura allegato Specifica fallita: %s", exc)
        return ""
    if not data:
        return ""
    file_hash = hashlib.sha256(data).hexdigest()
    _sgi_store_spec_hash(spec, file_hash)
    cached = _sgi_cached_text(file_hash)
    if cached is not None:
        return cached[:max_pdf_chars]
    text = _extract_pdf_text(data)[:max_pdf_chars]
    _sgi_store_text(file_hash, text)
    return text


def _sgi_safe_doc_path(raw_path: str, extensions: tuple[str, ...] = (".pdf",)) -> Path | None:
    """Path file server leggibile e con estensione in whitelist, altrimenti None.

    Nessuna scrittura, sola lettura per l'indicizzazione.
    """
    try:
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() in extensions:
            return path
    except OSError:
        return None
    return None


def _sgi_safe_pdf_path(raw_path: str) -> Path | None:
    """Alias storico: l'estrazione "piatta" legge solo PDF (un .docx/.xlsx ripiega
    sui metadati a monte)."""
    return _sgi_safe_doc_path(raw_path, (".pdf",))


# Strumenti di analisi (es. glossario_varianti_comuni) usano SEMPRE il testo persistito
# quando c'è: il flag SGI_ESTRAZIONE_PERSISTITA_ENABLED governa solo la lettura per il RAG.
_FORZA_TESTO_PERSISTITO: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sgi_forza_testo_persistito", default=False
)


@contextlib.contextmanager
def usa_testo_persistito():
    """Dentro il blocco i documenti SGI usano il testo persistito allineato all'hash, a
    prescindere dal flag; i PDF si estraggono solo per le revisioni senza testo."""
    token = _FORZA_TESTO_PERSISTITO.set(True)
    try:
        yield
    finally:
        _FORZA_TESTO_PERSISTITO.reset(token)


def _sgi_persisted_text(rev, file_hash: str) -> str | None:
    """Testo persistito (procedure_refresh.SgiTestoEstratto) se l'hash coincide.

    Con ``SGI_ESTRAZIONE_PERSISTITA_ENABLED`` (lettura RAG) o dentro
    ``usa_testo_persistito()``. None = usa il percorso attuale (riga assente, hash
    diverso, testo vuoto o app non disponibile). Import lazy: nessun import
    cross-app a livello di modulo.
    """
    attivo = getattr(settings, "SGI_ESTRAZIONE_PERSISTITA_ENABLED", False) or _FORZA_TESTO_PERSISTITO.get()
    if not attivo or not file_hash:
        return None
    try:
        from procedure_refresh.models import SgiTestoEstratto

        row = (
            SgiTestoEstratto.objects.filter(revision_id=rev.pk, file_hash=file_hash)
            .only("testo")
            .first()
        )
    except Exception:
        return None
    if row is None or not (row.testo or "").strip():
        return None
    return row.testo


def _sgi_extract_procedure_text(rev) -> str:
    """Testo PDF della procedura: solo file server locale (decisione F0-A).

    SharePoint e' escluso on-premise -> il chiamante ripiega sui metadati. Cache
    del testo per il ``file_hash`` gia' presente sul modello.
    """
    source_type = str(getattr(rev, "source_type", "") or "").strip().lower()
    source_path = str(getattr(rev, "source_path", "") or "").strip()
    if source_type != "fileserver" or not source_path:
        return ""
    max_pdf_chars = int(getattr(settings, "OLLAMA_RAG_SGI_MAX_PDF_CHARS", 200000) or 200000)
    file_hash = _clean_text(getattr(rev, "file_hash", ""), limit=128)
    # Prima del cache: per lo stesso hash il cache tiene il testo "piatto".
    persisted = _sgi_persisted_text(rev, file_hash)
    if persisted is not None:
        return persisted[:max_pdf_chars]
    if file_hash:
        cached = _sgi_cached_text(file_hash)
        if cached is not None:
            return cached[:max_pdf_chars]
    path = _sgi_safe_pdf_path(source_path)
    if path is None:
        return ""
    text = _extract_pdf_text(path)[:max_pdf_chars]
    if file_hash:
        _sgi_store_text(file_hash, text)
    return text


def _sgi_specifica_metadata(spec) -> str:
    """Testo di fallback (metadati) quando il PDF della Specifica non e' leggibile."""
    parts = [
        _clean_text(getattr(spec, "titolo", ""), limit=300),
        f"Cliente: {_clean_text(spec.cliente, limit=200)}" if getattr(spec, "cliente", "") else "",
        f"TAG: {_clean_text(spec.tag, limit=120)}" if getattr(spec, "tag", "") else "",
        _clean_text(getattr(spec, "note", ""), limit=600),
    ]
    return "\n".join(p for p in parts if p)


def _sgi_procedure_metadata(doc) -> str:
    """Testo di fallback (metadati) quando il PDF della procedura non e' leggibile."""
    parts = [
        _clean_text(getattr(doc, "title", ""), limit=300),
        f"Categoria: {_clean_text(doc.category, limit=100)}" if getattr(doc, "category", "") else "",
        _clean_text(getattr(doc, "description", ""), limit=600),
    ]
    return "\n".join(p for p in parts if p)


def _sgi_exclude_patterns() -> list[str]:
    """Deny-list roster operatori (OLLAMA_RAG_SGI_EXCLUDE), lower-case, deduplicata vuoti."""
    raw = getattr(settings, "OLLAMA_RAG_SGI_EXCLUDE", []) or []
    if isinstance(raw, str):
        raw = raw.split(";")
    return [str(p).strip().lower() for p in raw if str(p).strip()]


def _sgi_excluded_by_keyword(code: str, title: str) -> bool:
    """True se codice/titolo del documento SGI combacia con la deny-list roster operatori.

    Impedisce che gli elenchi di persone abilitate/licenziate a una macchina (skill matrix /
    licensed operators / MOD.187) entrino nel corpus RAG: sono la fonte di allucinazioni HR
    ("X e' abilitato alla macchina Y") e scavalcherebbero il tool governato (ACL + privacy).
    """
    patterns = _sgi_exclude_patterns()
    if not patterns:
        return False
    hay = f"{code or ''} {title or ''}".lower()
    return any(p in hay for p in patterns)


def _load_sgi_specifiche_chunks() -> list[KnowledgeChunk]:
    """Chunk citabili dalle Specifiche in vigore (stato S3 `in_validita`)."""
    try:
        from gestione_specifiche import constants as C
        from gestione_specifiche.models import Specifica
    except Exception:
        return []
    limit = int(getattr(settings, "OLLAMA_RAG_SGI_MAX_SPECS", 300) or 300)
    try:
        specifiche = list(
            Specifica.objects.filter(stato=C.STATO_IN_VALIDITA)
            .only("id", "codice", "revisione", "titolo", "cliente", "tag", "note", "allegato", "updated_at")
            .order_by("-updated_at")[:limit]
        )
    except Exception:
        return []

    max_chars = _sgi_chunk_chars()
    chunks: list[KnowledgeChunk] = []
    esclusi: list[str] = []
    for spec in specifiche:
        try:
            codice = _clean_text(spec.codice, limit=100)
            if not codice:
                continue
            if _sgi_excluded_by_keyword(codice, getattr(spec, "titolo", "") or ""):
                esclusi.append(codice)
                continue
            rev = _clean_text(spec.revisione, limit=30)
            doc_label = _sgi_doc_label(codice, rev, getattr(spec, "titolo", ""))
            source = f"spec:{codice}#rev{rev}" if rev else f"spec:{codice}"
            text = _sgi_extract_specifica_text(spec) or _sgi_specifica_metadata(spec)
            chunks.extend(_sgi_chunks_from_text(source=source, doc_label=doc_label, text=text, max_chars=max_chars))
        except Exception:
            continue
    if esclusi:
        logger.info("RAG SGI: %d specifiche escluse dal corpus (deny-list roster): %s",
                    len(esclusi), ", ".join(esclusi[:20]))
    return chunks


def _load_sgi_procedure_chunks() -> list[KnowledgeChunk]:
    """Chunk citabili dalle procedure correnti (ProcedureRevision is_current, doc attivo)."""
    try:
        from procedure_refresh.models import ProcedureRevision
    except Exception:
        return []
    limit = int(getattr(settings, "OLLAMA_RAG_SGI_MAX_PROCS", 300) or 300)
    try:
        revisions = list(
            ProcedureRevision.objects.filter(is_current=True, document__is_active=True)
            .select_related("document")
            .only(
                "id", "revision_code", "file_hash", "source_type", "source_path", "updated_at",
                "document__code", "document__title", "document__category", "document__description",
            )
            .order_by("-revision_date")[:limit]
        )
    except Exception:
        return []

    max_chars = _sgi_chunk_chars()
    chunks: list[KnowledgeChunk] = []
    esclusi: list[str] = []
    for rev in revisions:
        try:
            doc = rev.document
            code = _clean_text(getattr(doc, "code", ""), limit=50)
            if not code:
                continue
            # Governance HR: flag curato per-documento OPPURE deny-list roster operatori.
            if getattr(doc, "escludi_dal_rag", False) or _sgi_excluded_by_keyword(
                code, getattr(doc, "title", "") or ""
            ):
                esclusi.append(code)
                continue
            rev_code = _clean_text(rev.revision_code, limit=50)
            doc_label = _sgi_doc_label(code, rev_code, getattr(doc, "title", ""))
            source = f"proc:{code}#rev{rev_code}" if rev_code else f"proc:{code}"
            text = _sgi_extract_procedure_text(rev) or _sgi_procedure_metadata(doc)
            chunks.extend(_sgi_chunks_from_text(source=source, doc_label=doc_label, text=text, max_chars=max_chars))
        except Exception:
            continue
    if esclusi:
        logger.info("RAG SGI: %d procedure escluse dal corpus (flag/deny-list roster): %s",
                    len(esclusi), ", ".join(esclusi[:20]))
    return chunks


def _sds_scheda_text(scheda) -> str:
    """Compone il testo citabile di una Scheda di Sicurezza dai CAMPI CURATI in DB.

    Nessun PDF ri-parsato: l'estrazione l'ha gia' fatta l'RSPP (campi curati +
    ``estratto_grezzo``). Il testo e' impaginato con heading numerati SDS (1, 2, 4,
    8, 10, ...) cosi' il chunker sezione-aware puo' citare il paragrafo. Contenuto =
    sicurezza organizzativa (CLP, DPI, primo soccorso, incompatibilita'), non personale.
    """
    prodotto = scheda.prodotto
    parts: list[str] = []

    ident = [f"Prodotto: {_clean_text(getattr(prodotto, 'nome', ''), limit=200)}"]
    if getattr(prodotto, "fornitore", ""):
        ident.append(f"Fornitore: {_clean_text(prodotto.fornitore, limit=200)}")
    if getattr(prodotto, "produttore", ""):
        ident.append(f"Produttore: {_clean_text(prodotto.produttore, limit=200)}")
    mansioni = _clean_text(prodotto.mansioni_label(), limit=500)
    if mansioni:
        ident.append(f"Mansioni di rischio: {mansioni}")
    if getattr(scheda, "versione", ""):
        ident.append(f"Versione scheda: {_clean_text(scheda.versione, limit=50)}")
    parts.append("1 Identificazione del prodotto\n" + "\n".join(ident))

    clp_bits: list[str] = []
    if getattr(scheda, "classificazione_clp", ""):
        clp_bits.append(_clean_text(scheda.classificazione_clp, limit=2000))
    frasi_h = scheda.frasi_h if isinstance(getattr(scheda, "frasi_h", None), list) else []
    frasi_p = scheda.frasi_p if isinstance(getattr(scheda, "frasi_p", None), list) else []
    pittogrammi = scheda.pittogrammi if isinstance(getattr(scheda, "pittogrammi", None), list) else []
    if frasi_h:
        clp_bits.append("Frasi H (indicazioni di pericolo): " + ", ".join(str(x) for x in frasi_h))
    if frasi_p:
        clp_bits.append("Frasi P (consigli di prudenza): " + ", ".join(str(x) for x in frasi_p))
    if pittogrammi:
        clp_bits.append("Pittogrammi: " + ", ".join(str(x) for x in pittogrammi))
    if clp_bits:
        parts.append("2 Classificazione ed etichettatura (CLP)\n" + "\n".join(clp_bits))

    if getattr(scheda, "primo_soccorso", ""):
        parts.append("4 Misure di primo soccorso\n" + _clean_text(scheda.primo_soccorso, limit=3000))
    if getattr(scheda, "dpi_testo", ""):
        parts.append(
            "8 Controllo dell'esposizione e protezione individuale (DPI)\n"
            + _clean_text(scheda.dpi_testo, limit=3000)
        )
    if getattr(scheda, "incompatibilita", ""):
        parts.append(
            "10 Stabilita' e reattivita' (incompatibilita')\n"
            + _clean_text(scheda.incompatibilita, limit=3000)
        )

    # Altre sezioni dall'estratto grezzo (mappa sezione -> testo), non gia' coperte sopra.
    estratto = scheda.estratto_grezzo if isinstance(getattr(scheda, "estratto_grezzo", None), dict) else {}
    for key, value in estratto.items():
        body = _clean_text(str(value), limit=3000)
        if not body:
            continue
        label = _clean_text(str(key), limit=90)
        head = label if re.match(r"^\s*\d", label) else f"Sezione {label}"
        parts.append(f"{head}\n{body}")

    return "\n\n".join(parts)


def _load_schede_sicurezza_chunks() -> list[KnowledgeChunk]:
    """Chunk citabili dalle Schede di Sicurezza CORRENTI (handle `sds:`).

    Fail-safe come gli altri loader (app assente / errore -> lista vuota). OPT-OUT
    con ``OLLAMA_RAG_SDS_ENABLED=False``.
    """
    if not bool(getattr(settings, "OLLAMA_RAG_SDS_ENABLED", True)):
        return []
    try:
        from schede_sicurezza.models import SchedaSicurezza
    except Exception:
        return []
    limit = int(getattr(settings, "OLLAMA_RAG_SDS_MAX", 500) or 500)
    try:
        schede = list(
            SchedaSicurezza.objects.filter(is_corrente=True)
            .select_related("prodotto")
            .prefetch_related("prodotto__mansioni")
            .order_by("-data_caricamento")[:limit]
        )
    except Exception:
        return []

    max_chars = int(getattr(settings, "OLLAMA_RAG_CHUNK_CHARS", 900) or 900)
    chunks: list[KnowledgeChunk] = []
    for scheda in schede:
        try:
            nome = _clean_text(getattr(scheda.prodotto, "nome", ""), limit=120)
            if not nome:
                continue
            versione = _clean_text(getattr(scheda, "versione", ""), limit=50)
            doc_label = f"SDS {nome} v.{versione}" if versione else f"SDS {nome}"
            source = f"sds:{nome}#v{versione}" if versione else f"sds:{nome}"
            text = _sds_scheda_text(scheda)
            if not text.strip():
                continue
            chunks.extend(_sgi_chunks_from_text(source=source, doc_label=doc_label, text=text, max_chars=max_chars))
        except Exception:
            continue
    return chunks


def _load_sgi_document_chunks() -> list[KnowledgeChunk]:
    """Aggrega il corpus SGI: specifiche + procedure correnti + schede di sicurezza correnti."""
    chunks: list[KnowledgeChunk] = []
    chunks.extend(_load_sgi_specifiche_chunks())
    chunks.extend(_load_sgi_procedure_chunks())
    chunks.extend(_load_schede_sicurezza_chunks())
    return chunks


def _sgi_documents_signature() -> tuple[int, str, int, str, int, str]:
    """Firma del corpus SGI (count + max updated per fonte: spec, proc, schede) per la cache."""
    if not bool(getattr(settings, "OLLAMA_RAG_SGI_ENABLED", True)):
        return (0, "", 0, "", 0, "")
    from django.db.models import Count, Max

    spec_count, spec_latest = 0, ""
    try:
        from gestione_specifiche import constants as C
        from gestione_specifiche.models import Specifica

        agg = Specifica.objects.filter(stato=C.STATO_IN_VALIDITA).aggregate(
            n=Count("id"), latest=Max("updated_at")
        )
        spec_count = agg["n"] or 0
        spec_latest = agg["latest"].isoformat() if agg["latest"] else ""
    except Exception:
        spec_count, spec_latest = 0, ""

    proc_count, proc_latest = 0, ""
    try:
        from procedure_refresh.models import ProcedureRevision

        agg = ProcedureRevision.objects.filter(is_current=True, document__is_active=True).aggregate(
            n=Count("id"), latest=Max("updated_at")
        )
        proc_count = agg["n"] or 0
        proc_latest = agg["latest"].isoformat() if agg["latest"] else ""
    except Exception:
        proc_count, proc_latest = 0, ""

    # Schede di sicurezza correnti: senza campo updated_at usiamo Max(data_caricamento)
    # come proxy (nuove schede/versioni invalidano la cache; le rimodifiche dei campi
    # curati restano coperte dal TTL e dal re-index schedulato).
    sds_count, sds_latest = 0, ""
    if bool(getattr(settings, "OLLAMA_RAG_SDS_ENABLED", True)):
        try:
            from schede_sicurezza.models import SchedaSicurezza

            agg = SchedaSicurezza.objects.filter(is_corrente=True).aggregate(
                n=Count("id"), latest=Max("data_caricamento")
            )
            sds_count = agg["n"] or 0
            sds_latest = agg["latest"].isoformat() if agg["latest"] else ""
        except Exception:
            sds_count, sds_latest = 0, ""

    return (spec_count, spec_latest, proc_count, proc_latest, sds_count, sds_latest)


def _build_index(chunks: list[KnowledgeChunk]) -> KnowledgeIndex:
    """Precalcola IDF (con smoothing BM25) e lunghezza media dei chunk."""
    n = len(chunks)
    if not n:
        return KnowledgeIndex(chunks=(), idf={}, avgdl=0.0)
    chunks = [
        chunk if chunk.title_tokens is not None else replace(chunk, title_tokens=frozenset(_tokenize(chunk.title)))
        for chunk in chunks
    ]
    document_frequency: Counter[str] = Counter()
    postings: dict[str, list[int]] = {}
    total_length = 0
    for i, chunk in enumerate(chunks):
        total_length += sum(chunk.tokens.values())
        document_frequency.update(chunk.tokens.keys())
        for token in set(chunk.tokens) | set(chunk.title_tokens or ()):
            postings.setdefault(token, []).append(i)
    avgdl = total_length / n if n else 0.0
    idf = {
        token: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5))
        for token, freq in document_frequency.items()
    }
    return KnowledgeIndex(
        chunks=tuple(chunks),
        idf=idf,
        avgdl=avgdl,
        postings={token: tuple(ids) for token, ids in postings.items()},
    )


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


def _ollama_embed_texts(texts: list[str], *, timeout: int | None = None) -> list[list[float]] | None:
    """Embeddings per una lista di testi via Ollama nativo.

    Prova prima ``/api/embed`` (batch, Ollama recente), poi ripiega su
    ``/api/embeddings`` per singolo item (API legacy). Ritorna ``None`` su
    qualunque errore o disallineamento (il chiamante usa solo BM25).
    Supportato solo per il provider ``ollama`` (Open WebUI -> solo BM25).

    ``timeout`` (secondi) sovrascrive ``OLLAMA_EMBED_TIMEOUT_SECONDS`` per i
    chiamanti latency-sensitive (es. routing semantico) che devono degradare
    rapidamente a keyword-only se l'endpoint e' lento/giu'.
    """
    if not texts:
        return []
    base_url, provider, _model, _timeout = _resolve_ollama_target()
    if provider != "ollama" or not base_url:
        return None
    model = str(getattr(settings, "OLLAMA_EMBED_MODEL", "") or "").strip()
    if not model:
        return None
    timeout = int(timeout) if timeout else int(getattr(settings, "OLLAMA_EMBED_TIMEOUT_SECONDS", 30) or 30)
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


def _embed_cache_key(model: str, chunk: KnowledgeChunk) -> str:
    return "ai_embed:" + hashlib.sha256(f"{model}\n{_chunk_embed_text(chunk)}".encode("utf-8")).hexdigest()


def _embeddings_for_chunks(
    chunks: list[KnowledgeChunk],
    model: str,
    *,
    reuse: dict[str, Any] | None = None,
    max_compute: int | None = None,
) -> list[Any] | None:
    """Embeddings allineati ai chunk, con cache per content-hash (DatabaseCache).

    Solo i chunk non in cache vengono inviati a Ollama (a batch). Ritorna
    ``None`` se l'embedding non e' disponibile -> retrieval BM25-only.

    ``reuse``: vettori gia' in memoria (indice precedente) per chiave cache: i chunk
    invariati non rileggono la cache DB. ``max_compute``: se i vettori da calcolare
    sono di piu', ritorna ``None`` senza chiamare il backend (la richiesta di chat non
    deve aspettare minuti di embedding: li completa la ricostruzione in background).
    """
    if not chunks:
        return []
    persist = bool(getattr(settings, "OLLAMA_EMBED_PERSIST", True))
    cache_keys = [_embed_cache_key(model, c) for c in chunks]
    cached_map: dict[str, Any] = {}
    if reuse:
        cached_map.update({key: reuse[key] for key in cache_keys if key in reuse})
    to_read = [key for key in cache_keys if key not in cached_map]
    if persist and to_read:
        # get_many A BATCH: una IN(...) con migliaia di chiavi sfonda il limite di
        # parametri del backend (SQL Server ~2100, SQLite 999) -> la lettura intera
        # fallirebbe e ricalcoleremmo TUTTI gli embedding ad ogni rebuild (~140s di
        # TTFT). Batch piccolo e tollerante: un batch fallito = quei chunk risultano
        # "missing" e vengono ricalcolati, senza buttare via gli altri letti.
        get_batch = max(1, int(getattr(settings, "OLLAMA_EMBED_CACHE_GET_BATCH", 500) or 500))
        for start in range(0, len(to_read), get_batch):
            keys = to_read[start:start + get_batch]
            try:
                cached_map.update(cache.get_many(keys) or {})
            except Exception:
                continue

    embeddings: list[Any] = [None] * len(chunks)
    missing: list[int] = []
    for i, key in enumerate(cache_keys):
        vec = cached_map.get(key)
        if vec is not None and len(vec):
            embeddings[i] = vec
        else:
            missing.append(i)

    if missing and max_compute is not None and len(missing) > max_compute:
        logger.info(
            "ai_assistant: %d embeddings da calcolare (> %d): indice BM25-only finche' "
            "la ricostruzione in background non li completa.", len(missing), max_compute,
        )
        return None
    if missing:
        batch_size = max(1, int(getattr(settings, "OLLAMA_EMBED_BATCH", 16) or 16))
        ttl = int(getattr(settings, "OLLAMA_EMBED_CACHE_TTL", 2592000) or 2592000)
        retries = max(0, int(getattr(settings, "OLLAMA_EMBED_RETRY", 2) or 0))
        pause_s = max(0.0, float(getattr(settings, "OLLAMA_EMBED_BATCH_PAUSE_MS", 0) or 0) / 1000.0)
        # Cache INCREMENTALE + retry + micro-pausa tra batch. Su corpora grandi
        # (migliaia di chunk) l'ondata di richieste puo' saturare Ollama: la pausa
        # smorza il picco, il retry supera i timeout transitori, e la cache per batch
        # fa si' che una batch fallita non butti via il lavoro fatto (i run successivi
        # / il warm notturno convergono fino a coprire tutto, in prod su DatabaseCache).
        failed = False
        for start in range(0, len(missing), batch_size):
            group = missing[start:start + batch_size]
            texts = [_chunk_embed_text(chunks[i]) for i in group]
            vectors = None
            for attempt in range(retries + 1):
                vectors = _compute_embeddings(texts)
                if vectors is not None:
                    break
                if attempt < retries:
                    time.sleep(min(1.0 * (attempt + 1), 5.0))  # backoff
            if vectors is None:
                failed = True
                break
            batch_store: dict[str, list[float]] = {}
            for offset, i in enumerate(group):
                embeddings[i] = vectors[offset]
                batch_store[cache_keys[i]] = vectors[offset]
            if persist and batch_store:
                try:
                    cache.set_many(batch_store, timeout=ttl)
                except Exception:
                    pass
            if pause_s:
                time.sleep(pause_s)
        if failed:
            return None  # questo build resta BM25-only; il progresso e' in cache

    if any(vec is None for vec in embeddings):
        return None
    return [vec for vec in embeddings]  # type: ignore[misc]


def _embedding_matrix(vectors: list[Any]):
    """Matrice float32 con righe normalizzate L2 (None se le dimensioni non tornano)."""
    import numpy as np

    try:
        matrix = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if matrix.ndim != 2 or not matrix.shape[0] or not matrix.shape[1]:
        return None
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # riga nulla -> resta nulla, similarita' 0
    return matrix / norms


# Embedding della domanda condiviso nella stessa richiesta: il routing dei tool e il
# retrieval RAG embeddano spesso lo stesso testo; con lo scope attivo il backend viene
# chiamato una sola volta. Fuori dallo scope nessuna memoria (test e comandi invariati).
_QUERY_EMBED_MEMO: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "ai_query_embed_memo", default=None
)


@contextlib.contextmanager
def query_embedding_scope():
    token = _QUERY_EMBED_MEMO.set({})
    try:
        yield
    finally:
        _QUERY_EMBED_MEMO.reset(token)


def embed_query(text: str, *, timeout: int | None = None) -> list[float] | None:
    """Embedding di un singolo testo, riusato dentro ``query_embedding_scope``."""
    memo = _QUERY_EMBED_MEMO.get()
    key = (_embed_backend(), _effective_embed_model(), text)
    if memo is not None and key in memo:
        return memo[key]
    vectors = embed_texts([text], timeout=timeout)
    vector = vectors[0] if vectors else None
    if memo is not None and vector is not None:
        memo[key] = vector
    return vector


def _query_embedding(prompt: str) -> list[float] | None:
    return embed_query(prompt)


def embeddings_enabled() -> bool:
    """True se il retrieval/routing semantico via embeddings e' utilizzabile.

    Richiede il flag attivo. Con backend ``fastembed`` (in-process) o ``openai``
    (endpoint HTTP) e' indipendente dal provider chat; con backend ``ollama`` resta
    valido solo il provider Ollama nativo (Open WebUI non espone gli embeddings).
    """
    if not bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False)):
        return False
    backend = _embed_backend()
    if backend in ("fastembed", "openai"):
        return True
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    return provider == "ollama"


def embed_texts(texts: list[str], *, timeout: int | None = None) -> list[list[float]] | None:
    """API pubblica per embeddare testi (usata dal routing tool). None su errore.

    ``timeout`` (secondi) e' un override per i chiamanti latency-sensitive: il
    routing semantico passa un timeout breve cosi' un endpoint embeddings lento
    degrada subito a keyword-only invece di rallentare ogni messaggio di chat.

    I testi vengono inviati in **sotto-batch** (``OLLAMA_EMBED_BATCH``, default 16):
    alcuni backend HTTP rifiutano richieste con troppi input in un colpo (es. TEI,
    ``max_client_batch_size=32``). Senza batch il calcolo dei vettori-seme del routing
    (~55 frasi) veniva respinto in blocco -> None -> ranking semantico spento in
    silenzio (fail-safe a keyword-only). L'indicizzazione RAG batchava gia'; questo
    allinea anche il percorso ``embed_texts``.
    """
    if not texts:
        return []
    batch_size = max(1, int(getattr(settings, "OLLAMA_EMBED_BATCH", 16) or 16))
    if len(texts) <= batch_size:
        return _compute_embeddings(texts, timeout=timeout)
    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        group = list(texts[start:start + batch_size])
        vectors = _compute_embeddings(group, timeout=timeout)
        if not vectors or len(vectors) != len(group):
            return None
        out.extend(vectors)
    return out


# ── Backend embeddings configurabile (RAG_EMBED_BACKEND) ────────────────────
# Default "ollama" (com'era). "fastembed" calcola i vettori IN-PROCESS (CPU, ONNX:
# nessun server da saturare, ideale per il warm notturno). "openai" li prende da un
# endpoint HTTP OpenAI-compatibile (TEI / Infinity / vLLM / LM Studio sulla GPU).
# Tutto on-premise, nessun vector DB: il vettore non lascia la rete interna.
_FASTEMBED_CACHE: dict[str, Any] = {"name": "", "model": None}


def _embed_backend() -> str:
    return str(getattr(settings, "RAG_EMBED_BACKEND", "ollama") or "ollama").strip().lower()


def _effective_embed_model() -> str:
    """Nome modello del backend attivo (usato anche per la chiave di cache vettori)."""
    backend = _embed_backend()
    if backend == "fastembed":
        return str(getattr(settings, "RAG_EMBED_FASTEMBED_MODEL", "BAAI/bge-m3") or "").strip()
    if backend == "openai":
        return str(getattr(settings, "RAG_EMBED_OPENAI_MODEL", "") or "").strip()
    return str(getattr(settings, "OLLAMA_EMBED_MODEL", "") or "").strip()


def _get_fastembed_model(name: str):
    """Istanza fastembed cachata (il caricamento del modello e' costoso). None se la
    dipendenza manca o il modello non e' supportato (fail-safe -> BM25)."""
    if _FASTEMBED_CACHE["name"] != name or _FASTEMBED_CACHE["model"] is None:
        _FASTEMBED_CACHE["name"] = name
        try:
            from fastembed import TextEmbedding

            _FASTEMBED_CACHE["model"] = TextEmbedding(model_name=name)
        except Exception as exc:
            logger.debug("fastembed non disponibile (%s): %s", name, exc)
            _FASTEMBED_CACHE["model"] = None
    return _FASTEMBED_CACHE["model"]


def _fastembed_texts(texts: list[str]) -> list[list[float]] | None:
    if not texts:
        return []
    emb = _get_fastembed_model(_effective_embed_model() or "BAAI/bge-m3")
    if emb is None:
        return None
    try:
        return [[float(x) for x in vec] for vec in emb.embed(list(texts))]
    except Exception as exc:
        logger.debug("fastembed embed fallita: %s", exc)
        return None


def _openai_embed_texts(texts: list[str], *, timeout: int | None = None) -> list[list[float]] | None:
    """Embeddings da endpoint OpenAI-compatibile (TEI/Infinity/vLLM/LM Studio).

    ``timeout`` sovrascrive ``OLLAMA_EMBED_TIMEOUT_SECONDS`` (vedi
    ``_ollama_embed_texts``): il routing usa un timeout breve per non bloccare
    la chat se l'endpoint embeddings e' lento/giu'.
    """
    if not texts:
        return []
    base = str(getattr(settings, "RAG_EMBED_OPENAI_BASE_URL", "") or "").strip().rstrip("/")
    model = str(getattr(settings, "RAG_EMBED_OPENAI_MODEL", "") or "").strip()
    if not base or not model:
        return None
    api_key = str(getattr(settings, "RAG_EMBED_OPENAI_API_KEY", "") or "").strip()
    timeout = int(timeout) if timeout else int(getattr(settings, "OLLAMA_EMBED_TIMEOUT_SECONDS", 30) or 30)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base}/v1/embeddings",
        data=json.dumps({"model": model, "input": list(texts)}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != len(texts):
        return None
    try:
        return [[float(x) for x in item["embedding"]] for item in items]
    except (KeyError, TypeError, ValueError):
        return None


def _compute_embeddings(texts: list[str], *, timeout: int | None = None) -> list[list[float]] | None:
    """Dispatcher: calcola gli embeddings col backend configurato (RAG_EMBED_BACKEND).

    ``timeout`` si applica ai backend di rete (openai/ollama); ``fastembed`` e'
    in-process (CPU) e lo ignora.
    """
    if not texts:
        return []
    backend = _embed_backend()
    if backend == "fastembed":
        return _fastembed_texts(texts)
    if backend == "openai":
        return _openai_embed_texts(texts, timeout=timeout)
    return _ollama_embed_texts(texts, timeout=timeout)


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


def _embed_cache_max_entries() -> int | None:
    """MAX_ENTRIES del cache ``default`` (None se non leggibile / non DatabaseCache)."""
    try:
        default_cache = (getattr(settings, "CACHES", {}) or {}).get("default", {}) or {}
        raw = (default_cache.get("OPTIONS", {}) or {}).get("MAX_ENTRIES")
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _warn_if_embed_cache_too_small(n_chunks: int) -> None:
    """Avvisa se i chunk superano MAX_ENTRIES: gli embedding verrebbero cullati e
    ricalcolati a ogni rebuild (causa reale della latenza ~95s del 2026-06-29)."""
    max_entries = _embed_cache_max_entries()
    if max_entries is not None and n_chunks > max_entries:
        logger.warning(
            "ai_assistant: RAG ha %d chunk ma il cache MAX_ENTRIES=%d -> gli embedding "
            "verranno cullati e RICALCOLATI a ogni rebuild dell'indice (latenza chat alta). "
            "Alza DJANGO_CACHE_MAX_ENTRIES sopra il numero di chunk.",
            n_chunks,
            max_entries,
        )


_RAG_STATUS_CACHE_KEY = "ai_rag:index_status"


def _record_rag_index_status(index: "KnowledgeIndex", chunks: list[KnowledgeChunk], elapsed_ms: float) -> None:
    """Salva un blob di stato dell'indice RAG (no PII) leggibile dalla pagina
    "Stato sistema" senza rieseguire il build. Fail-safe."""
    try:
        from django.utils import timezone

        total = len(chunks)
        sgi = sum(1 for c in chunks if c.source.startswith(("spec:", "proc:")))
        max_entries = _embed_cache_max_entries()
        embed_on = bool(embeddings_enabled())
        cache.set(
            _RAG_STATUS_CACHE_KEY,
            {
                "built_at": timezone.now().isoformat(timespec="seconds"),
                "elapsed_ms": int(elapsed_ms),
                "chunks_total": total,
                "chunks_sgi": sgi,
                "embed_enabled": embed_on,
                "embeddings_ready": bool(getattr(index, "embeddings", None)),
                "embed_model": getattr(index, "embed_model", "") or "",
                "cache_max_entries": max_entries,
                "oversized": bool(embed_on and max_entries is not None and total > max_entries),
            },
            timeout=7 * 24 * 3600,
        )
    except Exception:
        pass


def rag_index_status() -> dict | None:
    """Ultimo stato noto dell'indice RAG (None se mai costruito in questo deploy)."""
    try:
        value = cache.get(_RAG_STATUS_CACHE_KEY)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _load_knowledge_index() -> KnowledgeIndex:
    if not bool(getattr(settings, "OLLAMA_RAG_ENABLED", True)):
        return KnowledgeIndex(chunks=(), idf={}, avgdl=0.0)

    files = _iter_knowledge_files()
    signature = _knowledge_signature(files)
    ttl = int(getattr(settings, "OLLAMA_RAG_CACHE_SECONDS", 300) or 0)
    now = time.monotonic()
    cached = _KNOWLEDGE_CACHE.get("index")
    if ttl > 0 and isinstance(cached, KnowledgeIndex):
        if (
            _KNOWLEDGE_CACHE.get("signature") == signature
            and now - float(_KNOWLEDGE_CACHE.get("loaded_at") or 0) < ttl
            and _KNOWLEDGE_CACHE.get("complete", True)
        ):
            return cached
        # Indice scaduto o documenti cambiati: la chat risponde subito con l'indice
        # in memoria e la ricostruzione avviene in background (prima la pagava
        # l'utente: 20-30 s di attesa ogni OLLAMA_RAG_CACHE_SECONDS).
        if _background_rebuild_enabled():
            _start_background_rebuild()
            return cached

    with _KNOWLEDGE_BUILD_LOCK:
        cached = _KNOWLEDGE_CACHE.get("index")
        if (
            ttl > 0
            and isinstance(cached, KnowledgeIndex)
            and _KNOWLEDGE_CACHE.get("signature") == signature
            and _KNOWLEDGE_CACHE.get("complete", True)
        ):
            return cached  # costruito da un'altra richiesta mentre aspettavamo
        inline_max = None
        if ttl > 0 and _background_rebuild_enabled():
            inline_max = max(0, int(getattr(settings, "OLLAMA_EMBED_INLINE_MAX", 200) or 0))
        index = _build_knowledge_index(files, signature, max_compute=inline_max)
    if not _KNOWLEDGE_CACHE.get("complete", True):
        _start_background_rebuild()
    return index


def _knowledge_signature(files: list[Path]) -> tuple:
    return (
        tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files),
        _curated_knowledge_signature(),
        _sgi_documents_signature(),
        glossario_rag.firma(),
        guide_portale.firma() if _guide_enabled() else (),
    )


def _background_rebuild_enabled() -> bool:
    return bool(getattr(settings, "OLLAMA_RAG_BACKGROUND_REBUILD", True))


def _start_background_rebuild() -> bool:
    """Avvia (una sola alla volta) la ricostruzione dell'indice in un thread."""
    with _KNOWLEDGE_BUILD_LOCK:
        if _KNOWLEDGE_CACHE.get("rebuilding"):
            return False
        _KNOWLEDGE_CACHE["rebuilding"] = True
    threading.Thread(target=_background_rebuild, name="ai-rag-rebuild", daemon=True).start()
    return True


def _background_rebuild() -> None:
    from django.db import connection

    try:
        files = _iter_knowledge_files()
        signature = _knowledge_signature(files)
        with _KNOWLEDGE_BUILD_LOCK:
            _build_knowledge_index(files, signature, max_compute=None)
    except Exception:
        logger.exception("ai_assistant: ricostruzione in background dell'indice RAG fallita")
    finally:
        _KNOWLEDGE_CACHE["rebuilding"] = False
        connection.close()


def _build_knowledge_index(files: list[Path], signature: tuple, *, max_compute: int | None) -> KnowledgeIndex:
    """Costruisce l'indice e lo mette in cache di processo.

    ``max_compute`` limita gli embeddings calcolati qui (vedi ``_embeddings_for_chunks``):
    se ne mancano di piu' l'indice resta BM25-only e viene marcato incompleto.
    """
    now = time.monotonic()
    build_start = now
    previous = _KNOWLEDGE_CACHE.get("index")
    complete = True
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
    chunks.extend(_load_glossario_chunks())
    if _guide_enabled():
        chunks.extend(_load_guide_chunks())
    if bool(getattr(settings, "OLLAMA_RAG_SGI_ENABLED", True)):
        chunks.extend(_load_sgi_document_chunks())

    index = _build_index(chunks)

    # Arricchimento semantico opzionale (fail-safe: se fallisce resta BM25-only).
    # Usa il backend configurato (ollama / fastembed / openai) via embeddings_enabled().
    if chunks and embeddings_enabled():
        _warn_if_embed_cache_too_small(len(chunks))
        embed_model = _effective_embed_model()
        if embed_model:
            reuse = None
            if (
                isinstance(previous, KnowledgeIndex)
                and previous.embed_model == embed_model
                and previous.embeddings is not None
                and len(previous.embed_keys) == len(previous.embeddings)
            ):
                reuse = dict(zip(previous.embed_keys, previous.embeddings))
            vectors = _embeddings_for_chunks(chunks, embed_model, reuse=reuse, max_compute=max_compute)
            matrix = _embedding_matrix(vectors) if vectors else None
            if matrix is not None:
                index = replace(
                    index,
                    embeddings=matrix,
                    embed_model=embed_model,
                    embed_keys=tuple(_embed_cache_key(embed_model, c) for c in chunks),
                )
            elif max_compute is not None:
                complete = False  # mancano embeddings: li completa il rebuild in background

    _record_rag_index_status(index, chunks, (time.monotonic() - build_start) * 1000.0)
    _KNOWLEDGE_CACHE.update({"loaded_at": now, "signature": signature, "index": index, "complete": complete})
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
    title_tokens = chunk.title_tokens if chunk.title_tokens is not None else set(_tokenize(chunk.title))
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
    if index.postings is None:
        candidates = range(len(index.chunks))
    else:
        # Un chunk senza alcun token della domanda (testo o titolo) ha punteggio 0:
        # si valutano solo i candidati dell'indice invertito, in ordine di corpus.
        ids: set[int] = set()
        for token in query_tokens:
            ids.update(index.postings.get(token, ()))
        candidates = sorted(ids)
    scored = [
        (i, _bm25_score(query_tokens, index.chunks[i], index.idf, index.avgdl))
        for i in candidates
    ]
    return [i for i, score in sorted(scored, key=lambda kv: kv[1], reverse=True) if score > 0]


def _semantic_ranking(prompt: str, index: KnowledgeIndex) -> list[int]:
    if index.embeddings is None or not prompt.strip():
        return []
    query_vector = _query_embedding(prompt)
    if not query_vector:
        return []
    import numpy as np

    query = np.asarray(query_vector, dtype=np.float32)
    query_norm = float(np.linalg.norm(query))
    if not query_norm or query.shape[0] != index.embeddings.shape[1]:
        return []  # modello cambiato (dimensioni diverse): resta BM25
    sims = index.embeddings @ (query / query_norm)
    order = np.argsort(-sims, kind="stable")
    return [int(i) for i in order if sims[i] > 0]


def _select_chunk_indices(prompt: str, query_tokens: Counter[str], index: KnowledgeIndex) -> list[int]:
    """Indici dei chunk da usare: ibrido BM25+semantico (RRF) o BM25-only.

    Le parti per amministratori del Centro guide restano fuori se la domanda non è da
    amministratore e non nomina il loro modulo (``guide_admin_pertinenti``): il gate
    di chi può leggerle è a valle, in ``_guide_chunk_allowed``.
    """
    bm25_ranked = _bm25_ranking(query_tokens, index)
    semantic_ranked = _semantic_ranking(prompt, index)
    if semantic_ranked:
        max_chunks = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
        pool = max(max_chunks * 5, 20)
        rrf_k = int(getattr(settings, "OLLAMA_RAG_HYBRID_RRF_K", 60) or 60)
        ranked = _rrf_fuse(bm25_ranked[:pool], semantic_ranked[:pool], rrf_k)
    else:
        ranked = bm25_ranked
    return _senza_guide_admin_fuori_tema(prompt, query_tokens, index, ranked)


def _senza_guide_admin_fuori_tema(
    prompt: str, query_tokens: Counter[str], index: KnowledgeIndex, ranked: list[int]
) -> list[int]:
    admin = {g.slug for g in guide_portale.guide() if g.solo_admin}
    if not admin:
        return ranked
    pertinenti = guide_portale.guide_admin_pertinenti(prompt, query_tokens.keys(), _tokenize)
    escluse = admin - pertinenti
    if not escluse:
        return ranked
    return [i for i in ranked if guide_portale.slug_da_source(index.chunks[i].source) not in escluse]


# ── Modalità "panoramica documento" ─────────────────────────────────────────
# Quando l'utente cita un codice documento (es. «MT CN 06») e chiede di cosa parla
# / il contenuto, NON usiamo il top-k semantico (che pesca poche sezioni e induce
# il modello a inventare lo scopo): costruiamo scopo + INDICE COMPLETO delle sezioni
# dai titoli reali del documento. Fedele al 100%, zero confabulazione.
_DOC_OVERVIEW_INTENT_RE = re.compile(
    r"di\s+cosa\s+(parla|tratta)|di\s+che\s+(cosa\s+)?(parla|tratta)|di\s+che\s+si\s+tratta|"
    r"cosa\s+(contiene|tratta)|contenut|riassum|panoramica|\bindice\b|\bsezioni\b|argoment|"
    r"in\s+generale|tutto\s+il\s+(contenut|document)",
    re.IGNORECASE,
)


def _sgi_source_kind(source: str) -> str | None:
    """'spec'/'proc' per le fonti SGI protette da ACL di modulo, None per il resto
    (file di knowledge, FAQ curate: non protetti da ACL, sempre condivisibili)."""
    if source.startswith("spec:"):
        return "spec"
    if source.startswith("proc:"):
        return "proc"
    return None


def _sgi_chunk_allowed(chunk: KnowledgeChunk, *, allow_specifiche: bool, allow_procedure: bool) -> bool:
    """Gate ACL per-sorgente del corpus SGI (finding leakage #1).

    I chunk delle Specifiche entrano solo se l'utente potrebbe aprirle nel modulo
    (`allow_specifiche`); quelli delle Procedure solo per i manager
    (`allow_procedure`). Tutte le altre fonti (file, FAQ curate) restano ammesse.
    """
    kind = _sgi_source_kind(chunk.source)
    if kind == "spec":
        return allow_specifiche
    if kind == "proc":
        return allow_procedure
    return True


def _index_document_codes(
    index: KnowledgeIndex, *, allow_specifiche: bool = True, allow_procedure: bool = True
) -> dict[str, list[int]]:
    """Mappa codice-documento -> indici chunk, dai source 'proc:<code>#rev..'/'spec:<code>..'.

    Rispetta il gate ACL per-sorgente: i documenti la cui sorgente non è
    autorizzata non entrano nella mappa (quindi non producono panoramica)."""
    codes: dict[str, list[int]] = {}
    for i, chunk in enumerate(index.chunks):
        chunk_kind = _sgi_source_kind(chunk.source)
        if chunk_kind is None:
            continue
        if chunk_kind == "spec" and not allow_specifiche:
            continue
        if chunk_kind == "proc" and not allow_procedure:
            continue
        code = chunk.source.split(":", 1)[1].split("#", 1)[0].strip()
        if code:
            codes.setdefault(code, []).append(i)
    return codes


def _code_match_regex(code: str) -> "re.Pattern[str]":
    """Regex per trovare un codice documento nel testo utente: tollerante a
    spazi/punteggiatura tra i token e a zeri iniziali, con confini per non
    confondere 06/065 o 271/2710. Es. «MT CN 06» trova anche «mt cn 6», «MTCN06»."""
    tokens = re.findall(r"[A-Za-z]+|\d+", code)  # solo lettere e gruppi di cifre
    sep = r"[\s._\-]*"  # separatore flessibile (spazi, ., _, -)
    body = sep.join(
        (r"0*" + str(int(t)) if t.isdigit() else re.escape(t)) for t in tokens
    )
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![0-9])", re.IGNORECASE)


def _match_document_code(prompt: str, codes: dict[str, list[int]]) -> str | None:
    """Il codice documento citato nel prompt (match più specifico/lungo), o None."""
    best: str | None = None
    for code in codes:
        if _code_match_regex(code).search(prompt) and (best is None or len(code) > len(best)):
            best = code
    return best


def _doc_label_from_title(title: str) -> str:
    for sep in (" — ", " - ", "—"):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def _document_overview_context(
    prompt: str,
    index: KnowledgeIndex,
    *,
    allow_specifiche: bool = True,
    allow_procedure: bool = True,
) -> KnowledgeContext | None:
    """Costruisce scopo + indice sezioni di un documento nominato, o None se non
    applicabile (nessun intento panoramica, nessun codice citato, doc assente).

    Applica il gate ACL per-sorgente: la panoramica di un documento la cui
    sorgente non è autorizzata non viene costruita (canale di leak, finding #1)."""
    if not _DOC_OVERVIEW_INTENT_RE.search(prompt):
        return None
    codes = _index_document_codes(
        index, allow_specifiche=allow_specifiche, allow_procedure=allow_procedure
    )
    if not codes:
        return None
    code = _match_document_code(prompt, codes)
    if not code:
        return None

    chunks = [index.chunks[i] for i in codes[code]]
    doc_label = _doc_label_from_title(chunks[0].title) if chunks else code

    sections: dict[str, str] = {}
    scope_text = ""
    for ch in chunks:
        m = re.search(r"§\s*([\d.]+)\s*(.*)$", ch.title)
        if m:
            num = m.group(1).strip(".")
            heading = re.sub(r"\s+", " ", m.group(2)).strip()
            if 0 < len(heading) <= 70 and num not in sections:
                sections[num] = heading
        elif not scope_text and ch.content.strip():
            scope_text = ch.content.strip()  # chunk senza § = intro/scopo
    if not scope_text:
        for ch in chunks:
            t = ch.title.lower()
            if "scopo" in t or "campo di applicazione" in t:
                scope_text = ch.content.strip()
                break
    scope_text = scope_text[:700]

    def _sec_key(n: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in n.split("."))
        except ValueError:
            return (9999,)

    outline = "\n".join(f"- §{num} {sections[num]}" for num in sorted(sections, key=_sec_key))
    if not (scope_text or outline):
        return None

    parts = [f"PANORAMICA DEL DOCUMENTO {doc_label} (codice {code}):"]
    if scope_text:
        parts.append(f"SCOPO (estratto dal documento):\n{scope_text}")
    if outline:
        parts.append(f"INDICE COMPLETO DELLE SEZIONI (dai titoli reali del documento):\n{outline}")
    parts.append(
        f"ISTRUZIONE: questo è l'inquadramento (scopo) e l'INDICE COMPLETO delle sezioni di {doc_label}. "
        "Presenta lo scopo ed elenca le sezioni così come sopra. NON descrivere il contenuto di sezioni "
        "non elencate e NON dedurre l'argomento del documento da poche sezioni; per i dettagli di una "
        f"specifica sezione invita l'utente a chiederla. Cita il documento come «{doc_label}». "
        "Per il testo integrale rimanda al documento nel modulo Procedure del portale."
    )
    return KnowledgeContext(text="\n\n".join(parts).strip(), sources=(f"{code} > {doc_label} (panoramica)",))


def sgi_rag_access(request) -> tuple[bool, bool]:
    """Autorizzazione al retrieval SGI: ``(allow_specifiche, allow_procedure)``.

    Replica l'ACL di modulo così che la chat/report non esponga contenuto che
    l'utente non vedrebbe aprendo il modulo (finding leakage #1):

    - Specifiche: stessa decisione ACL della rotta ``/gestione-specifiche/``.
    - Procedure: solo manager (superuser / admin legacy), come ``_is_manager``
      di ``procedure_refresh`` (la libreria documenti da cui il RAG estrae il testo).

    Fail-closed: ``request`` assente → ``(False, False)``. Se la legacy-auth non
    è attiva (dev/test) il middleware ACL non applica gate → ``(True, True)``,
    coerente col comportamento del portale.
    """
    if request is None:
        return (False, False)
    try:
        from core.acl_v2 import resolve_acl_access
        from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_auth_enabled
    except Exception:
        return (False, False)

    user = getattr(request, "user", None)
    if getattr(user, "is_superuser", False):
        return (True, True)
    if not legacy_auth_enabled():
        return (True, True)

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)

    # Procedure: solo manager (come procedure_refresh._is_manager).
    allow_procedure = bool(is_legacy_admin(legacy_user))

    # Specifiche: stessa decisione ACL della rotta di modulo.
    try:
        decision = resolve_acl_access(
            path="/gestione-specifiche/",
            legacy_user=legacy_user,
            django_user=user,
            request=request,
            include_legacy_diagnostic=False,
        )
        allow_specifiche = bool(decision.get("allowed"))
    except Exception:
        allow_specifiche = False

    return (allow_specifiche, allow_procedure)


def _guide_chunk_allowed(chunk: KnowledgeChunk, allowed_guides: frozenset[str] | None) -> bool:
    """Gate ACL delle guide in-app: ammessa solo se l'utente può aprire la guida.
    Le fonti che non sono guide restano ammesse (le decide ``_sgi_chunk_allowed``)."""
    slug = guide_portale.slug_da_source(chunk.source)
    if slug is None:
        return True
    return bool(allowed_guides) and slug in allowed_guides


_GUIDE_PROMOTE_MAX = 3


def _promote_mentioned_guides(
    selected_indices: list[int], index: KnowledgeIndex, query_tokens: Counter[str]
) -> list[int]:
    """Porta in testa (al massimo 3) i capitoli della guida del modulo nominato.

    Se la domanda nomina il modulo («timbro», «audit»), i suoi capitoli più
    pertinenti precedono quelli di altri moduli che condividono parole generiche
    («nuovo», «inserire»). Il resto dell'ordine non cambia, così le fonti SGI
    sullo stesso tema restano nel contesto.
    """
    mentioned = guide_portale.guide_menzionate(query_tokens.keys(), _tokenize)
    if not mentioned:
        return selected_indices
    promoted: list[int] = []
    for i in selected_indices:
        if guide_portale.slug_da_source(index.chunks[i].source) in mentioned:
            promoted.append(i)
            if len(promoted) >= _GUIDE_PROMOTE_MAX:
                break
    if not promoted:
        return selected_indices
    promoted_set = set(promoted)
    return promoted + [i for i in selected_indices if i not in promoted_set]


def build_knowledge_context(
    prompt: str,
    *,
    allow_specifiche: bool = False,
    allow_procedure: bool = False,
    allowed_guides: frozenset[str] | None = None,
    only_guides: bool = False,
    max_chunks: int | None = None,
) -> KnowledgeContext:
    """Contesto RAG per il prompt.

    ``allowed_guides``: slug delle guide in-app che l'utente può aprire (``None`` →
    nessuna, fail-closed). ``only_guides``: solo capitoli delle guide, usato quando
    risponde un tool live e i documenti generali confonderebbero il modello.
    """
    index = _load_knowledge_index()
    if not index.chunks:
        return KnowledgeContext(text="", sources=())

    if not only_guides:
        overview = _document_overview_context(
            prompt, index, allow_specifiche=allow_specifiche, allow_procedure=allow_procedure
        )
        if overview is not None:
            return overview

    query_tokens = Counter(_tokenize(prompt))
    selected_indices = _select_chunk_indices(prompt, query_tokens, index)
    # Gate ACL per-sorgente SGI (finding #1): i chunk spec:/proc: entrano solo se
    # l'utente potrebbe vederli aprendo il modulo; i non-SGI restano sempre ammessi.
    # Il filtro è a valle dell'indice cachato (content-only, condiviso): nessuno
    # scoping per-utente della cache, e il risultato del retrieval non è cachato.
    selected_indices = [
        i
        for i in selected_indices
        if _sgi_chunk_allowed(
            index.chunks[i], allow_specifiche=allow_specifiche, allow_procedure=allow_procedure
        )
        and _guide_chunk_allowed(index.chunks[i], allowed_guides)
        and (not only_guides or guide_portale.slug_da_source(index.chunks[i].source) is not None)
    ]
    if not selected_indices:
        return KnowledgeContext(text="", sources=())
    selected_indices = _promote_mentioned_guides(selected_indices, index, query_tokens)

    if max_chunks is None:
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


_FONTE_ETICHETTE = (
    (guide_portale.SOURCE_PREFIX, "Guida"),
    ("glossario:", "Glossario"),
    ("spec:", "Specifica"),
    ("proc:", "Procedura"),
    ("sds:", "Scheda di sicurezza"),
)
_URL_GUIDA_RE = re.compile(r"Guida completa nel portale:\s*(/\S*)")


def _etichetta_fonte(source: str) -> str:
    for prefisso, etichetta in _FONTE_ETICHETTE:
        if source.startswith(prefisso):
            return etichetta
    return "Documento"


def _estratto(content: str, query_tokens: Counter[str], *, limite: int = 180) -> str:
    """La riga più pertinente del chunk (più token della domanda), accorciata."""
    migliore, punteggio = "", -1
    for riga in content.splitlines():
        riga = riga.strip(" -#*\t")
        if len(riga) < 12 or riga.startswith("Guida completa nel portale:"):
            continue
        p = sum(1 for t in _tokenize(riga) if t in query_tokens)
        if p > punteggio:
            migliore, punteggio = riga, p
    return migliore if len(migliore) <= limite else migliore[: limite - 1].rstrip() + "…"


def cerca_documenti(
    prompt: str,
    *,
    allow_specifiche: bool = False,
    allow_procedure: bool = False,
    allowed_guides: frozenset[str] | None = None,
    limit: int = 5,
) -> tuple[str, list[dict[str, str]]]:
    """Ricerca veloce nei documenti dell'assistente, per la barra «Cerca o vai a…».

    Solo BM25 sull'indice già in memoria: niente LLM, niente embedding, niente
    costruzione sincrona dell'indice (a freddo la prepara in background e risponde
    ``in_preparazione``). Stessi filtri ACL di ``build_knowledge_context``.

    Ritorna ``(stato, risultati)``: stato ``pronto`` / ``in_preparazione`` / ``spento``;
    ogni risultato ha ``label``, ``tipo`` (Guida, Procedura…), ``preview`` e ``url``
    (la guida, se il capitolo ne ha una; altrimenti vuoto).
    """
    if not bool(getattr(settings, "OLLAMA_RAG_ENABLED", True)):
        return "spento", []
    index = _KNOWLEDGE_CACHE.get("index")
    if not isinstance(index, KnowledgeIndex) or not index.chunks:
        prewarm_async()
        return "in_preparazione", []
    query_tokens = Counter(_tokenize(prompt))
    if not query_tokens:
        return "pronto", []
    ranked = _senza_guide_admin_fuori_tema(prompt, query_tokens, index, _bm25_ranking(query_tokens, index))
    risultati: list[dict[str, str]] = []
    visti: set[tuple[str, str]] = set()
    for i in ranked:
        chunk = index.chunks[i]
        if not (
            _sgi_chunk_allowed(chunk, allow_specifiche=allow_specifiche, allow_procedure=allow_procedure)
            and _guide_chunk_allowed(chunk, allowed_guides)
        ):
            continue
        chiave = (chunk.source.split("#", 1)[0], chunk.title)
        if chiave in visti:
            continue
        visti.add(chiave)
        url = _URL_GUIDA_RE.search(chunk.content or "")
        risultati.append({
            "label": chunk.title,
            "tipo": _etichetta_fonte(chunk.source),
            "preview": _estratto(chunk.content or "", query_tokens),
            "url": url.group(1) if url and url.group(1).startswith("/") and not url.group(1).startswith("//") else "",
        })
        if len(risultati) >= limit:
            break
    return "pronto", risultati


# Domande su COME si fa una cosa nel portale: anche quando risponde un tool live
# (es. il catalogo moduli) la guida del modulo resta la fonte giusta per i passi.
_HOWTO_INTENT_RE = re.compile(
    r"\b(come|dove|in che modo|procedura|passi|passaggi|istruzioni|indicazioni|guida|"
    r"inserir\w*|aggiung\w*|crea\w*|registr\w*|modific\w*|caric\w*|archivi\w*|esport\w*|"
    r"stamp\w*|scaric\w*|approv\w*|chiud\w*|apr[io]\w*)\b",
    re.IGNORECASE,
)

# Tool live che descrivono la navigazione, non dati operativi: non tolgono il RAG.
_NAVIGATIONAL_RUNTIME_SOURCES = ("tool:portale:moduli", "tool:portale:permessi")


# Riferimenti al turno precedente: «inserirlo», «aprirla», «questo», «lo stesso».
_ANAPHORA_RE = re.compile(
    r"\b\w{3,}(?:rlo|rla|rli|rle|rne)\b|\b(questo|questa|quello|quella|stesso|stessa)\b",
    re.IGNORECASE,
)
_FOLLOWUP_MAX_TOKENS = 8


def _retrieval_query(prompt: str, history: Any) -> str:
    """Domanda per il retrieval: aggiunge l'ultima domanda utente se questa la continua.

    «ok dammi le indicazioni su come inserirlo nel modulo» da sola non dice quale
    modulo: se rimanda al turno precedente (pronome) o è corta e non nomina alcun
    modulo, il retrieval usa anche la domanda precedente. Il prompt al modello
    resta quello originale.
    """
    if not isinstance(history, list):
        return prompt
    previous = ""
    for item in reversed(history):
        if isinstance(item, dict) and str(item.get("role") or "").lower() == "user":
            previous = _clean_text(item.get("content"), limit=500)
            if previous:
                break
    if not previous or previous.strip() == (prompt or "").strip():
        return prompt
    tokens = _tokenize(prompt or "")
    names_module = bool(guide_portale.guide_menzionate(tokens, _tokenize))
    short_without_module = len(set(tokens)) < _FOLLOWUP_MAX_TOKENS and not names_module
    if _ANAPHORA_RE.search(prompt or "") or short_without_module:
        return f"{prompt}\n{previous}"
    return prompt


@dataclass(frozen=True)
class ChatKnowledge:
    knowledge_text: str = ""
    guide_text: str = ""
    sources: tuple[str, ...] = ()

    @property
    def chars(self) -> int:
        return len(self.knowledge_text) + len(self.guide_text)


def _knowledge_for_chat(
    prompt: str,
    *,
    runtime_context: str,
    runtime_sources: tuple[str, ...] | list[str] | None,
    allow_specifiche: bool,
    allow_procedure: bool,
    allowed_guides: frozenset[str] | None,
    history: Any = None,
) -> ChatKnowledge:
    """Sceglie quale conoscenza documentale affiancare alla domanda.

    - Nessun contesto live, o solo tool di navigazione: RAG completo (guide comprese).
    - Contesto live con dati operativi: niente RAG generale (i modelli piccoli
      confondono le due fonti), ma se la domanda chiede *come* fare qualcosa si
      aggiungono al massimo due capitoli delle guide in-app autorizzate.
    """
    has_runtime = bool((runtime_context or "").strip())
    sources = tuple(runtime_sources or ())
    navigational_only = has_runtime and bool(sources) and all(
        source.startswith(_NAVIGATIONAL_RUNTIME_SOURCES) for source in sources
    )
    query = _retrieval_query(prompt, history)
    if not has_runtime or navigational_only:
        knowledge = build_knowledge_context(
            query,
            allow_specifiche=allow_specifiche,
            allow_procedure=allow_procedure,
            allowed_guides=allowed_guides,
        )
        return ChatKnowledge(knowledge_text=knowledge.text, sources=knowledge.sources)
    if not allowed_guides or not _HOWTO_INTENT_RE.search(prompt or ""):
        return ChatKnowledge()
    guide = build_knowledge_context(
        query,
        allowed_guides=allowed_guides,
        only_guides=True,
        max_chunks=int(getattr(settings, "OLLAMA_RAG_GUIDE_MAX_CHUNKS_WITH_LIVE", 2) or 2),
    )
    return ChatKnowledge(guide_text=guide.text, sources=guide.sources)


# Regole di grounding sempre attive, separate dal system prompt (che può essere
# sovrascritto da .env e viene troncato a OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS).
_GROUNDING_RULES = (
    "REGOLE DI AFFIDABILITA' (sempre valide): "
    "1) Non sciogliere sigle (ruoli, uffici, moduli: MSM, CAR, RSPP, HR...) e non attribuire nomi o "
    "funzioni a una sigla se il contesto non li riporta: usa la sigla così com'è. "
    "2) Non dire che l'utente non ha accesso, permessi o abilitazioni se il contesto non lo dice "
    "esplicitamente; se non lo sai, indica il percorso e aggiungi che i pulsanti compaiono solo "
    "a chi ha il permesso. "
    "3) Se il CONTESTO LIVE contiene dati o conteggi, quelli sono dati reali a cui hai accesso: "
    "non rispondere mai che non puoi vedere i dati. Se il conteggio è zero, dillo come risultato. "
    "4) Per spiegare COME si fa una cosa nel portale preferisci le fonti 'guida:' (guide d'uso dei "
    "moduli): riporta i nomi esatti di pagine e pulsanti e indica il link della guida completa. "
    "5) Non ripetere la stessa spiegazione due volte nella stessa risposta."
)


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
    guide_context: str = "",
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
    # Le regole di affidabilità stanno nello stesso messaggio del system prompt: restano
    # attive anche quando il prompt è sovrascritto da .env o troncato.
    system_content = f"{system_prompt}\n\n{_GROUNDING_RULES}" if system_prompt else _GROUNDING_RULES
    messages.append({"role": "system", "content": system_content})
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
    if guide_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "GUIDA D'USO DEL MODULO (dalle guide in-app del portale):\n"
                    f"{guide_context}\n\n"
                    "ISTRUZIONE: usa questa guida SOLO per spiegare come si fa l'operazione nel portale "
                    "(pagine, pulsanti, passi). I dati dell'utente vengono esclusivamente dal contesto live. "
                    "Indica il link della guida completa."
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
                    "Cita le fonti presenti nel contesto tra parentesi. "
                    "REGOLA DI CITAZIONE DOCUMENTI SGI: se una fonte inizia con 'spec:' o 'proc:' "
                    "(specifiche tecniche e procedure del Sistema di Gestione), la risposta DEVE riportare "
                    "codice documento, revisione e sezione come compaiono nel titolo della fonte "
                    "(es. «MT CN 06 Rev.7 §4.2»), senza mostrare l'handle tecnico 'spec:'/'proc:'. "
                    "Se il contesto SGI non basta a rispondere, dichiaralo con "
                    "«Non disponibile nei documenti indicizzati» invece di inventare codici, revisioni o sezioni."
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


# ── Limite di chiamate AI contemporanee (per processo) ─────────────────────────
# Il portale gira con un solo processo waitress e pochi thread: ogni chiamata al
# modello tiene occupato un thread fino a OLLAMA_REQUEST_TIMEOUT_SECONDS. Senza
# limite, poche chat lente bloccano l'intero portale. Oltre il limite si risponde
# subito "assistente occupato" invece di accodare thread.
_AI_SLOTS_LOCK = threading.Lock()
_AI_SLOTS: threading.BoundedSemaphore | None = None
_AI_SLOT_WAIT_SECONDS = 5


def _ai_slots() -> threading.BoundedSemaphore:
    global _AI_SLOTS
    with _AI_SLOTS_LOCK:
        if _AI_SLOTS is None:
            limit = max(1, int(getattr(settings, "OLLAMA_MAX_CONCURRENT_REQUESTS", 3) or 3))
            _AI_SLOTS = threading.BoundedSemaphore(limit)
        return _AI_SLOTS


def _acquire_ai_slot() -> threading.BoundedSemaphore:
    slots = _ai_slots()
    if not slots.acquire(timeout=_AI_SLOT_WAIT_SECONDS):
        raise OllamaChatError(
            "L'assistente AI è occupato con altre richieste: riprova fra qualche secondo."
        )
    return slots


class _SlotReleasingResponse:
    """Stream HTTP che libera lo slot AI alla chiusura (una sola volta)."""

    def __init__(self, response: Any, slots: threading.BoundedSemaphore):
        self._response = response
        self._slots = slots
        self._released = False

    def __iter__(self):
        return iter(self._response)

    def __getattr__(self, name):
        return getattr(self._response, name)

    def close(self):
        try:
            self._response.close()
        finally:
            if not self._released:
                self._released = True
                self._slots.release()

    def __del__(self):
        if not self._released:
            self._released = True
            try:
                self._slots.release()
            except ValueError:
                pass


def chat_with_ollama(
    prompt: str,
    history: Any = None,
    *,
    runtime_context: str = "",
    user_preferences: dict[str, Any] | None = None,
    timeout: int | None = None,
    allow_specifiche: bool = False,
    allow_procedure: bool = False,
    allowed_guides: frozenset[str] | None = None,
    runtime_sources: tuple[str, ...] | list[str] | None = None,
) -> OllamaChatResult:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "OLLAMA_API_PROVIDER", "ollama") or "ollama").strip().lower()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "").strip()
    timeout = int(timeout) if timeout else int(getattr(settings, "OLLAMA_REQUEST_TIMEOUT_SECONDS", 60) or 60)
    if not base_url:
        raise OllamaChatError("OLLAMA_BASE_URL non configurato.")
    if not model:
        raise OllamaChatError("OLLAMA_CHAT_MODEL non configurato.")

    # Con un contesto live di dati operativi il RAG generale resta fuori dal payload
    # (i modelli small confondono le due fonti): passano solo le guide d'uso, e solo
    # per le domande «come si fa». Vedi _knowledge_for_chat.
    knowledge = _knowledge_for_chat(
        prompt,
        runtime_context=runtime_context,
        runtime_sources=runtime_sources,
        allow_specifiche=allow_specifiche,
        allow_procedure=allow_procedure,
        allowed_guides=allowed_guides,
        history=history,
    )
    payload = {
        "model": model,
        "messages": build_ollama_messages(
            prompt,
            history,
            knowledge_context=knowledge.knowledge_text,
            runtime_context=runtime_context,
            guide_context=knowledge.guide_text,
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

    slots = _acquire_ai_slot()
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
    finally:
        slots.release()

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
        sources=knowledge.sources,
        rag_context_chars=knowledge.chars,
    )


def index_sgi_documents() -> dict[str, Any]:
    """Forza la build dell'indice RAG e il warm degli embeddings del corpus SGI.

    La prima build e' la piu' costosa (estrazione PDF + embedding dei chunk SGI);
    le successive riusano la cache per ``file_hash``/content-hash. Se gli embeddings
    sono attivi (``OLLAMA_EMBED_ENABLED``) i vettori vengono precalcolati e cachati
    qui, cosi' la prima chat non paga il costo.

    Non solleva eccezioni: cattura tutto e riporta l'esito in un dict
    (``ok``/``chunks_*``/``embeddings_ready``/``elapsed_ms``/``message``), cosi' e'
    usabile in un cluster django-q senza farlo fallire.
    """
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "sgi_enabled": bool(getattr(settings, "OLLAMA_RAG_SGI_ENABLED", True)),
        "embeddings_enabled": embeddings_enabled(),
        "chunks_total": 0,
        "chunks_sgi": 0,
        "chunks_spec": 0,
        "chunks_proc": 0,
        "embeddings_ready": False,
        "embed_model": "",
        "elapsed_ms": None,
        "message": "",
    }
    if not bool(getattr(settings, "OLLAMA_RAG_ENABLED", True)):
        result.update(skipped=True, message="RAG disabilitato (OLLAMA_RAG_ENABLED=False): indicizzazione saltata.")
        return result
    try:
        # Build completa e sincrona (embeddings mancanti calcolati qui, senza il tetto
        # della chat): il comando/task deve finire con l'indice pronto.
        files = _iter_knowledge_files()
        with _KNOWLEDGE_BUILD_LOCK:
            index = _build_knowledge_index(files, _knowledge_signature(files), max_compute=None)
        total = len(index.chunks)
        spec = sum(1 for c in index.chunks if c.source.startswith("spec:"))
        proc = sum(1 for c in index.chunks if c.source.startswith("proc:"))
        result.update(
            ok=True,
            chunks_total=total,
            chunks_sgi=spec + proc,
            chunks_spec=spec,
            chunks_proc=proc,
            embeddings_ready=index.embeddings is not None,
            embed_model=index.embed_model,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        result["message"] = f"Indicizzazione SGI fallita: {exc}"
        logger.exception("index_sgi_documents: errore durante la build dell'indice")
        return result

    if not result["sgi_enabled"]:
        result["message"] = (
            f"Indice ricostruito: {total} chunk totali. Corpus SGI disattivato "
            "(OLLAMA_RAG_SGI_ENABLED=False)."
        )
    elif not result["embeddings_enabled"]:
        result["message"] = (
            f"Indice ricostruito: {total} chunk ({spec + proc} SGI: {spec} specifiche, {proc} procedure). "
            "Embeddings spenti: retrieval BM25-only (attiva OLLAMA_EMBED_ENABLED per l'ibrido)."
        )
    elif not result["embeddings_ready"]:
        result["message"] = (
            f"Indice ricostruito: {total} chunk ({spec + proc} SGI), ma gli embeddings non sono "
            "disponibili (Ollama offline o modello assente): retrieval BM25-only."
        )
    else:
        result["message"] = (
            f"Indice + embeddings pronti in {result['elapsed_ms']} ms: {total} chunk "
            f"({spec + proc} SGI: {spec} specifiche, {proc} procedure), modello {result['embed_model']}."
        )
    return result


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
    allow_specifiche: bool = False,
    allow_procedure: bool = False,
    allowed_guides: frozenset[str] | None = None,
    runtime_sources: tuple[str, ...] | list[str] | None = None,
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

    knowledge = _knowledge_for_chat(
        prompt,
        runtime_context=runtime_context,
        runtime_sources=runtime_sources,
        allow_specifiche=allow_specifiche,
        allow_procedure=allow_procedure,
        allowed_guides=allowed_guides,
        history=history,
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_ollama_messages(
            prompt,
            history,
            knowledge_context=knowledge.knowledge_text,
            runtime_context=runtime_context,
            guide_context=knowledge.guide_text,
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

    slots = _acquire_ai_slot()
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        slots.release()
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        hint = _ollama_endpoint_hint(base_url, http_status=exc.code)
        if provider == "openwebui" and exc.code in {401, 403}:
            hint = "Rigenera la API key in Open WebUI e salvala nella console Gestione AI."
        raise OllamaChatError(f"Ollama ha risposto con HTTP {exc.code}: {detail[:300]} {hint}") from exc
    except urllib.error.URLError as exc:
        slots.release()
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise OllamaChatError(_timeout_message(timeout)) from exc
        raise OllamaChatError(f"Ollama non raggiungibile: {exc.reason}") from exc
    except TimeoutError as exc:
        slots.release()
        raise OllamaChatError(_timeout_message(timeout)) from exc
    except OSError as exc:
        slots.release()
        raise OllamaChatError(f"Errore di rete verso Ollama: {exc}") from exc
    # Lo slot resta occupato per tutta la durata dello stream: lo libera la close()
    # chiamata da iter_ollama_stream (o il garbage collector se lo stream e' abbandonato).
    response = _SlotReleasingResponse(response, slots)

    meta = {
        "model": model,
        "provider": provider,
        "sources": knowledge.sources,
        "rag_context_chars": knowledge.chars,
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


def warmup_ollama(*, timeout: int | None = None) -> dict[str, Any]:
    """Pre-carica il modello chat in Ollama per azzerare il cold start.

    Invia una richiesta di solo "load" all'API nativa di Ollama
    (``/api/generate`` con prompt vuoto e ``stream`` disattivato): Ollama carica
    il modello in memoria rispettando ``OLLAMA_KEEP_ALIVE`` e ritorna subito con
    ``done_reason="load"`` SENZA generare token. Va richiamata da un job
    schedulato a intervalli inferiori al keep_alive (es. ogni 25 min se
    ``keep_alive=30m``) cosi' la prima richiesta utente non paga il caricamento.

    Supportata solo per il provider nativo ``ollama`` (keep_alive/preload sono
    primitive Ollama; Open WebUI non le espone): con ``openwebui`` ritorna
    ``skipped``.

    Non solleva eccezioni: cattura tutto e lo riporta nel dict di esito
    (``ok``/``skipped``/``loaded``/``elapsed_ms``/``message``), cosi' e' usabile
    in un cluster django-q senza farlo fallire.
    """
    base_url, provider, model, configured_timeout = _resolve_ollama_target()
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "provider": provider,
        "model": model,
        "loaded": False,
        "elapsed_ms": None,
        "message": "",
    }
    if not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        result.update(skipped=True, message="Assistente AI disabilitato (OLLAMA_CHAT_ENABLED=False): warmup saltato.")
        return result
    if not base_url:
        result.update(skipped=True, message="OLLAMA_BASE_URL non configurato: warmup saltato.")
        return result
    if not model:
        result.update(skipped=True, message="OLLAMA_CHAT_MODEL non configurato: warmup saltato.")
        return result
    if provider == "openwebui":
        result.update(
            skipped=True,
            message=(
                "Warmup non supportato con provider Open WebUI: keep_alive/preload sono primitive "
                "dell'API nativa di Ollama. Configura OLLAMA_API_PROVIDER=ollama per usare il warmup."
            ),
        )
        return result

    # Il warmup DEVE assorbire il caricamento del modello, percio' usa un timeout
    # generoso e indipendente da quello (piu' stretto) delle richieste utente.
    effective_timeout = int(timeout) if timeout else max(int(configured_timeout), 300)
    keep_alive = str(getattr(settings, "OLLAMA_KEEP_ALIVE", "") or "").strip()
    payload: dict[str, Any] = {"model": model, "prompt": "", "stream": False}
    # Precarica con LO STESSO num_ctx delle richieste di chat: se il warmup scaldasse
    # a un contesto diverso (default Ollama, es. 4096), la prima chat con num_ctx
    # maggiore forzerebbe un RICARICAMENTO del modello -> warmup sprecato e latenza
    # di cold-load a ogni ciclo (flip-flop 4096<->OLLAMA_NUM_CTX).
    num_ctx = int(getattr(settings, "OLLAMA_NUM_CTX", 0) or 0)
    if num_ctx > 0:
        payload["options"] = {"num_ctx": num_ctx}
    if keep_alive:
        payload["keep_alive"] = keep_alive

    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=effective_timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        hint = _ollama_endpoint_hint(base_url, http_status=exc.code)
        result["message"] = f"Warmup fallito: Ollama ha risposto HTTP {exc.code}: {detail[:200]} {hint}"
        return result
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
            result["message"] = (
                f"Warmup: timeout dopo {effective_timeout}s mentre il modello '{model}' si caricava. "
                "Su questo hardware il caricamento e' troppo lento: valuta un modello piu' piccolo/quantizzato "
                "oppure aumenta il timeout con --timeout."
            )
        else:
            result["message"] = f"Warmup fallito: Ollama non raggiungibile: {reason}"
        return result
    except OSError as exc:
        result["message"] = f"Warmup fallito: errore di rete verso Ollama: {exc}"
        return result

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    done_reason = str(data.get("done_reason") or "").strip() if isinstance(data, dict) else ""
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    result["ok"] = True
    result["loaded"] = True
    detail = f" (done_reason={done_reason})" if done_reason else ""
    keep_note = f", keep_alive={keep_alive}" if keep_alive else ""
    result["message"] = f"Modello '{model}' pre-caricato in {result['elapsed_ms']} ms{detail}{keep_note}."
    return result


# ── Preriscaldamento all'apertura della chat ───────────────────────────────────
# L'indice RAG vive nella memoria del processo web: il warm notturno e il warmup del
# modello girano nel cluster django-q (altro processo) e non lo scaldano. All'apertura
# della pagina si prepara tutto in un thread, mentre l'utente scrive la domanda.
_PREWARM_LOCK = threading.Lock()
_PREWARM_STATE: dict[str, bool] = {"running": False}
_PREWARM_OLLAMA_KEY = "ai_assistant:prewarm_ollama"


def prewarm_async() -> bool:
    """Avvia il preriscaldamento (uno alla volta). False se spento o gia' in corso."""
    if not bool(getattr(settings, "AI_PREWARM_ON_PAGE_OPEN", True)):
        return False
    if not bool(getattr(settings, "OLLAMA_CHAT_ENABLED", True)):
        return False
    with _PREWARM_LOCK:
        if _PREWARM_STATE["running"]:
            return False
        _PREWARM_STATE["running"] = True
    threading.Thread(target=_prewarm, name="ai-prewarm", daemon=True).start()
    return True


def _prewarm() -> None:
    from django.db import connection

    try:
        _load_knowledge_index()
        from . import tools

        tools._domain_seed_vectors()
        # Il modello chat: al piu' un warmup ogni 10 minuti per processo/cache.
        if cache.add(_PREWARM_OLLAMA_KEY, 1, timeout=600):
            warmup_ollama(timeout=180)
    except Exception:
        logger.exception("ai_assistant: preriscaldamento assistente fallito")
    finally:
        _PREWARM_STATE["running"] = False
        connection.close()
