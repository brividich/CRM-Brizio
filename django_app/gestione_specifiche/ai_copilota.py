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

import difflib
import json
import logging
import math
import os
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


# --- 1b. F5: diff revisione precedente ↔ nuova → righe MOD.133 (proposta) -----

def _estrai_testo_specifica(spec) -> str:
    """Testo del PDF di una specifica: allegato locale cifrato oppure percorso_esterno share.

    Il PDF sulla share si legge SOLO se dentro l'allowlist (`share_link.risolvi_consentito`).
    Fail-safe: '' se non disponibile.
    """
    if spec is None:
        return ""
    testo = _estrai_testo_pdf(getattr(spec, "allegato", None))
    if testo:
        return testo
    perc = (getattr(spec, "percorso_esterno", "") or "").strip()
    if not perc:
        return ""
    try:
        import fitz  # pymupdf

        from .share_link import risolvi_consentito

        reale = risolvi_consentito(perc)
        if not reale or not os.path.isfile(reale):
            return ""
        doc = fitz.open(reale)
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("gs copilota estrazione PDF share fallita: %s", exc)
        return ""


def _paragrafi(testo: str) -> list[str]:
    """Segmenta il testo in paragrafi normalizzati (whitespace collassato)."""
    parti = re.split(r"\n\s*\n", testo or "")
    return [re.sub(r"\s+", " ", p).strip() for p in parti if p.strip()]


def cambiamenti_tra_revisioni(testo_precedente: str, testo_nuovo: str, *, max_blocchi: int = 60) -> list[dict]:
    """Diff a paragrafi tra due revisioni. Ritorna i blocchi cambiati:
    ``{'tipo': 'aggiunto'|'modificato'|'rimosso', 'testo': ...}`` (rimosso = solo contesto).

    Deterministico (``difflib``), nessun accesso a rete: e' la base "accurata" su cui l'LLM
    poi ragiona, cosi' il modello vede SOLO cio' che e' cambiato (meno rumore, meno allucinazioni).
    """
    a, b = _paragrafi(testo_precedente), _paragrafi(testo_nuovo)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("insert", "replace"):
            for p in b[j1:j2]:
                out.append({"tipo": "modificato" if tag == "replace" else "aggiunto", "testo": p[:500]})
        if tag in ("delete", "replace"):
            for p in a[i1:i2]:
                out.append({"tipo": "rimosso", "testo": p[:500]})
        if len(out) >= max_blocchi:
            break
    return out[:max_blocchi]


def proponi_righe_da_diff(spec_nuova: Specifica, spec_precedente: Specifica | None = None) -> dict:
    """Proposta (NON salvata) di righe MOD.133 dal DIFF rev. precedente ↔ nuova.

    La precedente e' ``spec_precedente`` o, di default, ``spec_nuova.revisione_precedente``.
    L'AI **propone**, l'umano firma; fail-safe (AI/PDF non disponibili ⇒ righe vuote, ma i
    ``cambiamenti`` deterministici restano utili). Nessuna scrittura su DB.
    """
    prec = spec_precedente or getattr(spec_nuova, "revisione_precedente", None)
    if prec is None:
        return {"proposto": True, "fonte": "ai_diff", "ai_disponibile": False,
                "righe": [], "cambiamenti": [],
                "nota": "Nessuna revisione precedente: usare la pre-compilazione da singolo PDF."}

    testo_prec = _estrai_testo_specifica(prec)
    testo_nuovo = _estrai_testo_specifica(spec_nuova)
    cambiamenti = cambiamenti_tra_revisioni(testo_prec, testo_nuovo)
    if not cambiamenti:
        return {"proposto": True, "fonte": "ai_diff", "ai_disponibile": False,
                "righe": [], "cambiamenti": [],
                "nota": "Nessun cambiamento testuale rilevato tra le due revisioni (o PDF non leggibili)."}

    blocchi = "\n".join(f"[{c['tipo'].upper()}] {c['testo']}" for c in cambiamenti)
    prompt = (
        "Sei un assistente qualità. Confronta la revisione PRECEDENTE e la NUOVA di una "
        "specifica tecnica: qui sotto ci sono SOLO i blocchi cambiati (AGGIUNTO/MODIFICATO/"
        "RIMOSSO). Proponi le righe del MOD.133 (flow-down dei NUOVI requisiti) come SOLO "
        "JSON, lista di oggetti con chiavi: rif_paragrafo, argomento, descrizione_modifiche, "
        "descrizione_impatto, tag_processo, impatto_documenti (bool), impatto_operativo (bool). "
        "Concentrati sui cambiamenti reali; nessun testo fuori dal JSON.\n\nCAMBIAMENTI:\n"
        + blocchi[:6000]
    )
    raw = _chiama_ai(prompt, runtime_context="Diff MOD.133 rev precedente↔nuova: proposta, l'umano valida e firma.")
    return {
        "proposto": True,
        "fonte": "ai_diff",
        "ai_disponibile": bool(raw),
        "righe": _parse_righe_json(raw),
        "cambiamenti": cambiamenti,
        "n_cambiamenti": len(cambiamenti),
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
