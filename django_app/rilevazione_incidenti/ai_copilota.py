"""Copilota AI per la rilevazione incidenti (Fase 2 - A2): analisi RCA proposta.

Dal testo di una segnalazione di sicurezza (attivita' svolte + avvenimento) propone
in **analisi**: classificazione del tipo evento, bozza di causa radice, catena
**5-Why** e azioni correttive/preventive.

VINCOLO INVALICABILE: l'AI **propone**, il preposto/RSPP rivede e firma. Nessuna
scrittura DB, nessuna transizione: ogni output ha ``proposto=True``. Tutto
**fail-safe** (AI offline => proposta vuota, ``ai_disponibile=False``). On-prem
(Ollama): il testo non lascia la rete interna; l'audit a monte resta metadata-only.

Il ``tipo_evento`` proposto e' **validato** contro ``TipoEventoSicurezza``: un valore
fuori catalogo viene scartato (campo vuoto), mai inventato.
"""
from __future__ import annotations

import json
import logging
import re

from .models import TipoEventoSicurezza

logger = logging.getLogger(__name__)


def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("incidenti copilota AI non disponibile: %s", exc)
        return ""


def _parse_json_obj(raw: str) -> dict:
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    blob = m.group(0) if m else raw
    try:
        data = json.loads(blob)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _lista_stringhe(value, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = str(item or "").strip()[:max_len]
        if s:
            out.append(s)
        if len(out) >= max_items:
            break
    return out


def proponi_analisi_incidente(*, descrizione_attivita: str, descrizione_avvenimento: str) -> dict:
    """Proposta di analisi RCA dal testo dell'evento. Sola lettura, niente DB."""
    tipi_validi = {c for c, _ in TipoEventoSicurezza.choices}
    tipi_lines = "\n".join(f"- {c}: {label}" for c, label in TipoEventoSicurezza.choices)

    prompt = (
        "Sei un tecnico della sicurezza sul lavoro (D.Lgs. 81/08). Analizza l'evento di "
        "sicurezza e proponi l'analisi come SOLO JSON (nessun testo fuori dal JSON), con queste chiavi:\n"
        '  "tipo_evento": uno dei CODICI elencati sotto (o stringa vuota se incerto),\n'
        '  "causa_evento": breve causa radice dell\'evento (max ~200 caratteri),\n'
        '  "cinque_perche": array di 3-5 stringhe, la catena dei "perche\'" fino alla causa radice,\n'
        '  "azioni_correttive": array di 1-4 azioni correttive/preventive concrete,\n'
        '  "motivazione": una frase sul ragionamento della classificazione.\n\n'
        f"TIPI EVENTO AMMESSI:\n{tipi_lines}\n\n"
        f"ATTIVITA' SVOLTE:\n{(descrizione_attivita or '').strip()[:2000]}\n\n"
        f"AVVENIMENTO:\n{(descrizione_avvenimento or '').strip()[:2000]}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota incidenti: analisi RCA proposta, il preposto/RSPP rivede e firma.",
    )
    data = _parse_json_obj(raw)

    tipo = str(data.get("tipo_evento") or "").strip().lower()
    if tipo not in tipi_validi:
        tipo = ""
    causa = str(data.get("causa_evento") or "").strip()[:200]
    cinque = _lista_stringhe(data.get("cinque_perche"), max_items=5, max_len=300)
    azioni = _lista_stringhe(data.get("azioni_correttive"), max_items=4, max_len=300)
    motivazione = str(data.get("motivazione") or "").strip()[:500]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "tipo_evento": tipo,
        "causa_evento": causa,
        "cinque_perche": cinque,
        "azioni_correttive": azioni,
        "motivazione": motivazione,
    }
