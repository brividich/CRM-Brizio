"""Copilota AI per i ticket (Ondata 3.1).

Usa l'AI on-premise gia' integrata nel portale (`ai_assistant.services
.chat_with_ollama`, Ollama). Dal testo del ticket (titolo + descrizione) propone
in **triage**: categoria, priorita', incide sicurezza, assegnatario (dal team
gestori) e una bozza di risoluzione.

VINCOLO INVALICABILE: l'AI **propone**, il gestore rivede e firma. Questo modulo
non scrive nulla nel DB e non esegue assegnazioni/transizioni: ogni output ha
`proposto=True`. Tutto **fail-safe** (AI offline => proposta vuota,
`ai_disponibile=False`).

I valori proposti sono **validati**: la categoria deve appartenere alle categorie
del tipo, la priorita' all'enum, l'assegnatario al team gestori configurato.
Valori fuori lista vengono scartati (campo vuoto), mai inventati.
"""
from __future__ import annotations

import json
import logging
import re

from .models import PrioritaTicket

logger = logging.getLogger(__name__)


# --- Accesso all'AI locale (fail-safe) ---------------------------------------

def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("tickets copilota AI non disponibile: %s", exc)
        return ""


def _parse_json_obj(raw: str) -> dict:
    """Estrae il primo oggetto JSON dal testo del modello (tollerante)."""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    blob = m.group(0) if m else raw
    try:
        data = json.loads(blob)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# --- Triage proposto (NON salvato) -------------------------------------------

def proponi_triage(*, titolo: str, descrizione: str, tipo: str,
                   categorie, gestori) -> dict:
    """Proposta di triage dal testo del ticket. Sola lettura, niente DB.

    Args:
        titolo, descrizione: testo del ticket.
        tipo: "IT" o "MAN" (usato solo nel prompt; le liste candidate sono gia'
            filtrate dal chiamante).
        categorie: iterabile di tuple ``(codice, etichetta)`` ammesse.
        gestori: lista di dict ``{"nome": ..., "email": ...}`` (team gestori).
    """
    categorie = list(categorie or [])
    gestori = list(gestori or [])

    cat_validi = {str(c) for c, _ in categorie}
    prio_validi = {c for c, _ in PrioritaTicket.choices}
    gest_per_email = {
        (g.get("email") or "").strip().lower(): g
        for g in gestori
        if isinstance(g, dict) and (g.get("email") or "").strip()
    }

    cat_lines = "\n".join(f"- {c}: {e}" for c, e in categorie) or "(nessuna categoria)"
    gest_lines = "\n".join(
        f"- {(g.get('nome') or '').strip()} <{(g.get('email') or '').strip()}>"
        for g in gestori
        if isinstance(g, dict) and (g.get("email") or "").strip()
    ) or "(nessun gestore configurato)"

    prompt = (
        "Sei un assistente di service desk. Analizza il ticket e proponi il triage "
        "come SOLO JSON (nessun testo fuori dal JSON), con queste chiavi:\n"
        '  "categoria": uno dei CODICI elencati sotto (o stringa vuota se incerto),\n'
        '  "priorita": uno tra BASSA, MEDIA, ALTA, URGENTE,\n'
        '  "incide_sicurezza": true/false (true solo se c\'e\' rischio per la sicurezza delle persone),\n'
        '  "assegnatario_email": una delle email gestori elencate (o stringa vuota),\n'
        '  "bozza_risoluzione": breve bozza operativa dei passi di risoluzione,\n'
        '  "motivazione": una frase sul perche\' di categoria/priorita.\n\n'
        f"CATEGORIE AMMESSE (tipo {tipo}):\n{cat_lines}\n\n"
        f"GESTORI ASSEGNABILI:\n{gest_lines}\n\n"
        f"TICKET\nTitolo: {(titolo or '').strip()[:300]}\n"
        f"Descrizione: {(descrizione or '').strip()[:3000]}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota ticket: proposta di triage, il gestore rivede e firma.",
    )
    data = _parse_json_obj(raw)

    categoria = str(data.get("categoria") or "").strip()
    if categoria not in cat_validi:
        categoria = ""

    priorita = str(data.get("priorita") or "").strip().upper()
    if priorita not in prio_validi:
        priorita = ""

    incide_sicurezza = bool(data.get("incide_sicurezza"))
    # Stessa regola del modello: la sicurezza forza la priorita' a URGENTE.
    if incide_sicurezza:
        priorita = PrioritaTicket.URGENTE

    email = str(data.get("assegnatario_email") or "").strip().lower()
    gestore = gest_per_email.get(email)
    assegnatario = (
        {"nome": (gestore.get("nome") or "").strip(), "email": (gestore.get("email") or "").strip()}
        if gestore
        else None
    )

    bozza = str(data.get("bozza_risoluzione") or "").strip()[:1500]
    motivazione = str(data.get("motivazione") or "").strip()[:500]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "categoria": categoria,
        "priorita": priorita,
        "incide_sicurezza": incide_sicurezza,
        "assegnatario": assegnatario,
        "bozza_risoluzione": bozza,
        "motivazione": motivazione,
    }
