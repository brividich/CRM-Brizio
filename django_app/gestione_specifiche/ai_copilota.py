"""F9 — Copilota AI locale per gestione_specifiche.

Usa l'AI on-premise già integrata nel portale (`ai_assistant.services
.chat_with_ollama`, Ollama). Tre capacità:
  1. pre-compilazione righe MOD.133 dal PDF della specifica (proposta);
  2. classificazione automatica del TAG di processo (proposta);
  3. ricerca semantica sull'archivio specifiche (sola lettura).

VINCOLO INVALICABILE: l'AI **propone**, l'umano valida e firma. Nessuna funzione
qui persiste righe/tag né esegue transizioni/approvazioni: ogni output ha
`proposto=True` e non tocca il DB. Tutto fail-safe (AI offline ⇒ proposta vuota).

Strato di embedding (decisione DECISIONS): embeddings locali via Ollama
(`OLLAMA_EMBED_MODEL`, coerente con `ai_assistant`), con **fallback lessicale**
deterministico (overlap di token) quando gli embeddings non sono disponibili —
così la ricerca funziona anche offline e nei test.
"""
from __future__ import annotations

import json
import logging
import math
import re

from django.conf import settings

from .models import Specifica

logger = logging.getLogger(__name__)


# --- Accesso all'AI locale (fail-safe) ---------------------------------------

def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:
        logger.debug("gs copilota AI non disponibile: %s", exc)
        return ""


def _estrai_testo_pdf(filefield) -> str:
    if not filefield:
        return ""
    try:
        import fitz  # pymupdf

        with filefield.open("rb") as fh:
            data = fh.read()
        doc = fitz.open(stream=data, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        logger.debug("gs copilota estrazione PDF fallita: %s", exc)
        return ""


# --- 1. Pre-compilazione righe MOD.133 (proposta) ----------------------------

_CAMPI_RIGA = {
    "rif_paragrafo", "argomento", "descrizione_modifiche", "descrizione_impatto",
    "rif_doc_cn", "rif_paragrafo_cn", "tag_processo",
}
_FLAG_RIGA = {"impatto_documenti", "impatto_operativo", "genera_ofi"}


def _sanitizza_riga(d: dict) -> dict:
    riga = {k: str(d.get(k, "") or "")[:300] for k in _CAMPI_RIGA}
    for f in _FLAG_RIGA:
        riga[f] = bool(d.get(f, False))
    return riga


def _parse_righe_json(raw: str) -> list[dict]:
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    blob = m.group(0) if m else raw
    try:
        data = json.loads(blob)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_sanitizza_riga(d) for d in data if isinstance(d, dict)][:50]


def proponi_righe_mod133(spec: Specifica) -> dict:
    """Proposta (NON salvata) di righe MOD.133 dal PDF della specifica."""
    testo = _estrai_testo_pdf(spec.allegato)
    prompt = (
        "Sei un assistente qualità. Dal testo della specifica tecnica proponi le "
        "righe del MOD.133 (flow-down requisiti) come SOLO JSON, lista di oggetti con "
        "chiavi: rif_paragrafo, argomento, descrizione_modifiche, descrizione_impatto, "
        "tag_processo, impatto_documenti (bool), impatto_operativo (bool). "
        "Nessun testo fuori dal JSON.\n\nTESTO:\n" + (testo[:6000] if testo else "(PDF non disponibile)")
    )
    raw = _chiama_ai(prompt, runtime_context="Pre-compilazione MOD.133: proposta, l'umano valida e firma.")
    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "righe": _parse_righe_json(raw),
    }


# --- 2. Classificazione TAG di processo (proposta) ---------------------------

def proponi_tag(testo: str) -> dict:
    prompt = (
        "Classifica con UN SOLO tag di processo (parola in snake_case, minuscolo) "
        "il seguente contenuto di una specifica/comunicazione. Rispondi col solo tag.\n\n"
        + (testo or "")[:2000]
    )
    raw = _chiama_ai(prompt, runtime_context="Classificazione TAG: proposta, l'umano valida.")
    tag = ""
    if raw:
        token = re.split(r"\s+", raw.strip())[0] if raw.strip() else ""
        tag = re.sub(r"[^a-z0-9_]+", "_", token.lower()).strip("_")[:120]
    return {"proposto": True, "tag": tag, "ai_disponibile": bool(raw)}


# --- 3. Ricerca semantica (sola lettura) -------------------------------------

def _tokenizza(testo: str) -> list[str]:
    return [t for t in re.split(r"\W+", (testo or "").lower()) if len(t) > 2]


def _embedding(testo: str):
    """Embedding locale via Ollama; None se non disponibile (→ fallback lessicale)."""
    if not getattr(settings, "OLLAMA_EMBED_ENABLED", False):
        return None
    try:
        import requests

        base = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        model = getattr(settings, "OLLAMA_EMBED_MODEL", "nomic-embed-text")
        r = requests.post(f"{base}/api/embeddings", json={"model": model, "prompt": testo}, timeout=5)
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception as exc:
        logger.debug("gs copilota embedding non disponibile: %s", exc)
        return None


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


def _overlap(query_tokens: set, testo: str) -> float:
    doc = set(_tokenizza(testo))
    if not query_tokens or not doc:
        return 0.0
    return len(query_tokens & doc) / len(query_tokens | doc)  # Jaccard


def ricerca_semantica(query: str, *, limit: int = 10) -> list[dict]:
    """Classifica l'archivio specifiche per similarità con la query (read-only)."""
    query = (query or "").strip()
    if not query:
        return []
    emb_q = _embedding(query)
    q_tokens = set(_tokenizza(query))

    risultati = []
    for s in Specifica.objects.all().only(
        "id", "codice", "titolo", "tag", "cliente", "note", "stato"
    ):
        testo = f"{s.codice} {s.titolo} {s.tag} {s.cliente} {s.note}"
        if emb_q is not None:
            e = _embedding(testo)
            score = _cosine(emb_q, e) if e else 0.0
        else:
            score = _overlap(q_tokens, testo)
        if score > 0:
            risultati.append((score, s))

    risultati.sort(key=lambda t: t[0], reverse=True)
    return [
        {"id": s.id, "codice": s.codice, "titolo": s.titolo, "tag": s.tag,
         "stato": s.stato, "score": round(score, 4)}
        for score, s in risultati[:limit]
    ]
