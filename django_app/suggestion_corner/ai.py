"""Copilota AI per Suggestion Corner (sessione 9).

Riusa l'AI on-premise del portale (``ai_assistant.services.chat_with_ollama``,
Ollama) con lo stesso pattern fail-safe di ``anomalie/ai_copilota.py``:

- ``classifica_ai(seg)``  → suggerisce SMS_SI/SMS_NO (l'operatore conferma);
- ``bozza_plan_ai(seg)``  → bozza testuale del PLAN da rivedere;
- ``trova_simili(seg)``   → segnalazioni simili (dedup) via similarità token
  Jaccard sull'``opportunity`` — **non** dipende da Ollama, quindi testabile.

VINCOLO INVALICABILE: l'AI **propone**, l'operatore rivede e firma. Questo modulo
non scrive nulla nel DB e non esegue transizioni FSM. Tutto fail-safe (AI offline
=> proposta vuota, ``ai_disponibile=False``). Il valore ``stato_sms`` proposto è
validato contro ``StatoSMS`` reali: valori fuori lista vengono scartati.
"""
from __future__ import annotations

import json
import logging
import re

from .models import SuggestionCorner

logger = logging.getLogger(__name__)


def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("suggestion_corner copilota AI non disponibile: %s", exc)
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


def _contesto_segnalazione(seg) -> str:
    """Riassunto testuale della segnalazione per il prompt (no dati sensibili)."""
    reparto = getattr(seg.reparto_provenienza, "nome", "") or ""
    dest = getattr(seg.reparto_destinazione, "nome", "") or ""
    proc = seg.processo_libero or getattr(seg.processo, "nome", "") or ""
    parti = [f"Reparto provenienza: {reparto}"]
    if dest:
        parti.append(f"Reparto destinazione: {dest}")
    if proc:
        parti.append(f"Processo: {proc}")
    parti.append(f"Opportunità di miglioramento:\n{(seg.opportunity or '').strip()[:3000]}")
    return "\n".join(parti)


def classifica_ai(seg) -> dict:
    """Proposta di classificazione SMS Sì/No dal testo della segnalazione.

    Sola lettura. L'operatore SMS conferma la classificazione con l'azione FSM
    ``classifica``; questa funzione non scrive nulla. ``suggerimento`` è validato
    contro ``StatoSMS`` (SMS_SI/SMS_NO) o stringa vuota se incerto/AI offline.
    """
    prompt = (
        "Sei un assistente qualità di produzione (sistema SMS - miglioramento continuo). "
        "Valuta se la segnalazione seguente è una vera OPPORTUNITÀ DI MIGLIORAMENTO da "
        "gestire nel ciclo PDCA (SMS Sì) oppure no (SMS No: duplicato, non pertinente, "
        "reclamo generico senza azione, dato insufficiente). Rispondi con SOLO JSON "
        "(nessun testo fuori dal JSON), con queste chiavi:\n"
        '  "suggerimento": "SMS_SI" oppure "SMS_NO",\n'
        '  "motivazione": una frase sul perché.\n\n'
        f"SEGNALAZIONE\n{_contesto_segnalazione(seg)}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota Suggestion Corner: proposta di classificazione, l'operatore conferma.",
    )
    data = _parse_json_obj(raw)

    validi = {SuggestionCorner.StatoSMS.SMS_SI.value, SuggestionCorner.StatoSMS.SMS_NO.value}
    sugg = str(data.get("suggerimento") or "").strip().upper()
    if sugg not in validi:
        sugg = ""
    motivazione = str(data.get("motivazione") or "").strip()[:500]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "suggerimento": sugg,
        "motivazione": motivazione,
    }


def bozza_plan_ai(seg) -> dict:
    """Bozza testuale del PLAN (azioni di miglioramento) da rivedere.

    Sola lettura: restituisce testo suggerito che l'operatore incolla/edita nel
    campo ``plan_testo`` dell'azione ``definisci_plan``. Nessuna scrittura DB.
    """
    prompt = (
        "Sei un facilitatore del miglioramento continuo (PDCA). Dalla segnalazione "
        "seguente scrivi una BOZZA DI PLAN: 2-4 azioni concrete e verificabili per "
        "cogliere l'opportunità di miglioramento, in italiano, come elenco puntato "
        "sintetico. Rispondi con SOLO JSON (nessun testo fuori dal JSON):\n"
        '  "bozza_plan": "testo della bozza (usa a capo tra le azioni)".\n\n'
        f"SEGNALAZIONE\n{_contesto_segnalazione(seg)}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota Suggestion Corner: bozza PLAN, l'operatore rivede e firma.",
    )
    data = _parse_json_obj(raw)
    bozza = str(data.get("bozza_plan") or "").strip()[:2000]

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "bozza_plan": bozza,
    }


# --- Dedup / segnalazioni simili (senza dipendenza da Ollama) ----------------

_STOPWORDS = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in",
    "con", "su", "per", "tra", "fra", "e", "o", "ma", "che", "chi", "cui", "non",
    "del", "dei", "della", "delle", "degli", "dal", "dalla", "al", "alla", "nel",
    "nella", "sul", "sulla", "come", "più", "meno", "si", "sono", "essere", "ha",
    "hanno", "questo", "questa", "quello", "quella", "ci", "se", "anche", "ora",
}


def _tokenizza(testo: str) -> set:
    """Insieme di token significativi (minuscoli, senza stopword/parole corte)."""
    parole = re.findall(r"[a-zàèéìòóùç0-9]+", (testo or "").casefold())
    return {p for p in parole if len(p) > 2 and p not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def trova_simili(seg, *, limit: int = 5, soglia: float = 0.15):
    """Segnalazioni simili a ``seg`` (dedup), ordinate per similarità decrescente.

    Similarità Jaccard sui token dell'``opportunity``. Non usa l'AI: è
    deterministica e testabile con dati reali. Esclude la segnalazione stessa.

    Returns:
        Lista di dict ``{"pk", "opportunity", "score", "stato", "stato_label"}``.
    """
    base = _tokenizza(seg.opportunity)
    if not base:
        return []

    qs = SuggestionCorner.objects.exclude(pk=seg.pk).only(
        "pk", "opportunity", "stato",
    )
    risultati = []
    for altra in qs:
        score = _jaccard(base, _tokenizza(altra.opportunity))
        if score >= soglia:
            risultati.append({
                "pk": altra.pk,
                "opportunity": (altra.opportunity or "").strip()[:200],
                "score": round(score, 3),
                "stato": altra.stato,
                "stato_label": altra.stato_label,
            })
    risultati.sort(key=lambda r: r["score"], reverse=True)
    return risultati[:limit]
