"""Copilota AI per le anomalie / segnalazioni (Fase 2 - A3).

Usa l'AI on-premise gia' integrata nel portale (``ai_assistant.services
.chat_with_ollama``, Ollama). Dal testo di una segnalazione (descrizione) propone
in **triage**: stato superficie, se serve aprire un RDC / segnalare al cliente,
avanzamento suggerito e una bozza riformulata della descrizione.

VINCOLO INVALICABILE: l'AI **propone**, l'operatore rivede e firma. Questo modulo
non scrive nulla nel DB e non esegue transizioni: ogni output ha ``proposto=True``.
Tutto **fail-safe** (AI offline => proposta vuota, ``ai_disponibile=False``).

I valori proposti sono **validati** contro le liste reali del modulo
(``stati_superficie`` / ``avanzamenti`` da ``_load_anomalie_lists``): valori fuori
lista vengono scartati (campo vuoto), mai inventati.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("anomalie copilota AI non disponibile: %s", exc)
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


def proponi_triage_anomalia(*, descrizione: str, stati_superficie, avanzamenti) -> dict:
    """Proposta di triage dal testo della segnalazione. Sola lettura, niente DB.

    Args:
        descrizione: testo libero della segnalazione/anomalia.
        stati_superficie: iterabile di etichette ammesse (vocabolario controllato).
        avanzamenti: iterabile di etichette di avanzamento ammesse.
    """
    stati = [str(s).strip() for s in (stati_superficie or []) if str(s).strip()]
    avanz = [str(a).strip() for a in (avanzamenti or []) if str(a).strip()]
    stati_validi = {s.casefold(): s for s in stati}
    avanz_validi = {a.casefold(): a for a in avanz}

    stati_lines = "\n".join(f"- {s}" for s in stati) or "(nessuno)"
    avanz_lines = "\n".join(f"- {a}" for a in avanz) or "(nessuno)"

    prompt = (
        "Sei un assistente qualita' di produzione. Analizza la segnalazione di anomalia e "
        "proponi il triage come SOLO JSON (nessun testo fuori dal JSON), con queste chiavi:\n"
        '  "stato_superficie": una delle ETICHETTE elencate sotto (o stringa vuota se incerto),\n'
        '  "avanzamento": una delle ETICHETTE di avanzamento elencate (o stringa vuota),\n'
        '  "serve_rdc": true/false (true SOLO se l\'anomalia richiede di aprire un RDC o '
        "segnalare al cliente: pezzo non conforme, fuori tolleranza, difetto bloccante),\n"
        '  "bozza_descrizione": riformulazione chiara e sintetica della segnalazione,\n'
        '  "motivazione": una frase sul perche\' della proposta.\n\n'
        f"STATI SUPERFICIE AMMESSI:\n{stati_lines}\n\n"
        f"AVANZAMENTI AMMESSI:\n{avanz_lines}\n\n"
        f"SEGNALAZIONE\n{(descrizione or '').strip()[:3000]}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota anomalie: proposta di triage, l'operatore rivede e firma.",
    )
    data = _parse_json_obj(raw)

    stato = stati_validi.get(str(data.get("stato_superficie") or "").strip().casefold(), "")
    avanzamento = avanz_validi.get(str(data.get("avanzamento") or "").strip().casefold(), "")
    serve_rdc = bool(data.get("serve_rdc"))
    bozza = str(data.get("bozza_descrizione") or "").strip()[:1500]
    motivazione = str(data.get("motivazione") or "").strip()[:500]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "stato_superficie": stato,
        "avanzamento": avanzamento,
        "serve_rdc": serve_rdc,
        "bozza_descrizione": bozza,
        "motivazione": motivazione,
    }
