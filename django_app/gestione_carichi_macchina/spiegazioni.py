"""Strato LLM di SPIEGAZIONE (Fase 5) — riusa il gateway AI già integrato (`ai_assistant`).

L'LLM NON calcola e NON predice: riceve i numeri già calcolati (predizioni deterministiche) e
li spiega in linguaggio naturale, con istruzione di citare SOLO quei numeri. Tutto fail-safe:
se l'AI è disabilitata o non risponde, si ritorna None e il chiamante mostra i dati grezzi.
"""
from __future__ import annotations


def llm_disponibile() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "OLLAMA_CHAT_ENABLED", False))


def spiega(prompt: str, contesto: str, *, timeout: int = 30) -> str | None:
    """Chiede al gateway LLM una spiegazione. Ritorna il testo o None (fail-safe)."""
    if not llm_disponibile():
        return None
    try:  # import locale: dipendenza in sola lettura dal gateway AI del portale
        from ai_assistant.services import chat_with_ollama
    except Exception:
        return None
    try:
        res = chat_with_ollama(prompt, runtime_context=contesto, timeout=timeout)
        return (getattr(res, "content", "") or "").strip() or None
    except Exception:
        # rete giù, modello assente, timeout, config mancante: mai propagare
        return None


def contesto_suggerimento_macchina(famiglia_nome: str, ranked: list[dict]) -> tuple[str, str]:
    """Prepara (prompt, contesto) per spiegare il suggerimento macchina."""
    righe = [
        f"- {r.get('codice') or r['macchina_id']}: {round(r['prob'] * 100)}% "
        f"({r['occorrenze']} lavori storici)"
        for r in ranked
    ]
    contesto = (
        f"Famiglia pezzo: {famiglia_nome}\n"
        f"Macchine storicamente usate per questa famiglia (dato calcolato dal sistema):\n"
        + "\n".join(righe)
    )
    prompt = (
        f"In 1-2 frasi, consiglia su quale macchina conviene lavorare la famiglia "
        f"'{famiglia_nome}', basandoti ESCLUSIVAMENTE sui dati forniti e citando le percentuali. "
        f"Non inventare numeri o macchine non elencati."
    )
    return prompt, contesto
