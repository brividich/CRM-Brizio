"""FAQ suggerite dai feedback negativi (fase 4: l'assistente impara dalle risposte sbagliate).

Il modello non si riaddestra: impara dalle FAQ approvate, che il RAG usa subito.

Regole (decise il 12/10/2026):

- la fonte sono **solo** i 👎 che gli utenti inviano di propria scelta
  (``AiChatFeedback``): né l'audit né lo storico chat alimentano le FAQ;
- le domande simili si raggruppano, così una risposta copre tutte le varianti;
- l'AI scrive una **bozza spenta** (``AiKnowledgeEntry.is_active=False``) a partire
  da guide in-app, knowledge base e FAQ già approvate. **Mai** da Procedure e
  Specifiche: una FAQ approvata è visibile a tutti, quei documenti no. Le correzioni
  degli utenti entrano nel prompt come indicazione, non come fatto verificato;
- la bozza diventa conoscenza solo quando un amministratore la approva (un clic,
  con la possibilità di correggere domanda e risposta prima).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

from .models import AiChatFeedback, AiKnowledgeEntry

logger = logging.getLogger(__name__)

SOURCE_LABEL_BOZZA = "Bozza AI da feedback"
NON_DISPONIBILE = "NON_DISPONIBILE"
SOGLIA_SIMILARITA = 0.5
MAX_FEEDBACK = 300
MAX_GRUPPI = 20


@dataclass
class Gruppo:
    domanda: str
    feedback_ids: list[int] = field(default_factory=list)
    domande: list[str] = field(default_factory=list)
    correzioni: list[str] = field(default_factory=list)
    bozza: AiKnowledgeEntry | None = None

    @property
    def numero(self) -> int:
        return len(self.feedback_ids)

    @property
    def ids_csv(self) -> str:
        return ",".join(str(i) for i in self.feedback_ids)


def _token(testo: str) -> frozenset[str]:
    from .services import _tokenize

    return frozenset(_tokenize(testo or ""))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def gruppi_da_rivedere() -> list[Gruppo]:
    """👎 non ancora rivisti, raggruppati per domanda simile (i più numerosi prima)."""
    feedbacks = list(
        AiChatFeedback.objects.filter(rating="down", is_reviewed=False)
        .select_related("knowledge_entry")
        .order_by("-created_at")[:MAX_FEEDBACK]
    )
    gruppi: list[tuple[frozenset[str], Gruppo]] = []
    for fb in feedbacks:
        token = _token(fb.prompt)
        destinazione = None
        for token_gruppo, gruppo in gruppi:
            if _jaccard(token, token_gruppo) >= SOGLIA_SIMILARITA:
                destinazione = gruppo
                break
        if destinazione is None:
            destinazione = Gruppo(domanda=fb.prompt)
            gruppi.append((token, destinazione))
        destinazione.feedback_ids.append(fb.id)
        if fb.prompt not in destinazione.domande:
            destinazione.domande.append(fb.prompt)
        if fb.correction and fb.correction not in destinazione.correzioni:
            destinazione.correzioni.append(fb.correction)
        entry = fb.knowledge_entry
        if entry is not None and not entry.is_active and entry.source_label == SOURCE_LABEL_BOZZA:
            destinazione.bozza = entry
    ordinati = sorted((g for _, g in gruppi), key=lambda g: -g.numero)
    return ordinati[:MAX_GRUPPI]


def _feedback_del_gruppo(ids: list[int]) -> list[AiChatFeedback]:
    return list(
        AiChatFeedback.objects.filter(pk__in=ids, rating="down", is_reviewed=False).select_related("knowledge_entry")
    )


def parse_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for parte in str(raw or "").split(","):
        parte = parte.strip()
        if parte.isdigit():
            ids.append(int(parte))
    return ids[:MAX_FEEDBACK]


def _contesto_bozza(domanda: str, correzioni: list[str], allowed_guides) -> tuple[str, tuple[str, ...]]:
    from .services import build_knowledge_context

    # allow_specifiche/allow_procedure=False: la FAQ approvata è condivisa con tutti.
    knowledge = build_knowledge_context(
        domanda, allow_specifiche=False, allow_procedure=False, allowed_guides=allowed_guides,
    )
    parti = [
        "CONTESTO PER LA BOZZA DI FAQ (guide del portale, knowledge base, FAQ approvate):",
        knowledge.text or "(nessun documento pertinente trovato)",
    ]
    if correzioni:
        parti.append("RISPOSTE PROPOSTE DAGLI UTENTI (da verificare, non sono fatti accertati):")
        parti.extend(f"- {c[:600]}" for c in correzioni[:5])
    parti.append(
        "ISTRUZIONE: scrivi la risposta di una FAQ del portale alla domanda dell'utente, in italiano, "
        "al massimo 8 righe, con i nomi esatti di pagine e pulsanti. Usa SOLO il contesto sopra; "
        "una risposta proposta dagli utenti puoi usarla solo se il contesto la conferma. "
        "Chiudi con una riga «Fonti:» con le guide o i documenti usati. "
        f"Se il contesto non basta per rispondere, scrivi soltanto {NON_DISPONIBILE}."
    )
    return "\n\n".join(parti), knowledge.sources


def genera_bozza(request, ids: list[int]) -> tuple[AiKnowledgeEntry | None, str]:
    """Genera la bozza per il gruppo. Ritorna (bozza o None, messaggio per l'admin)."""
    from .guide_portale import guide_consentite
    from .services import OllamaChatError, chat_with_ollama

    feedbacks = _feedback_del_gruppo(ids)
    if not feedbacks:
        return None, "Nessun feedback da rivedere in questo gruppo."
    domanda = feedbacks[0].prompt
    correzioni = [fb.correction for fb in feedbacks if fb.correction]
    contesto, fonti = _contesto_bozza(domanda, correzioni, guide_consentite(request))
    try:
        risultato = chat_with_ollama(
            domanda,
            runtime_context=contesto,
            runtime_sources=("tool:faq:bozza",),
            user_preferences={"style": "sintetico", "show_limits": False},
            timeout=int(getattr(settings, "OLLAMA_REPORT_TIMEOUT_SECONDS", 120) or 120),
        )
    except OllamaChatError as exc:
        return None, f"L'assistente non è raggiungibile: {exc}"
    testo = (risultato.content or "").strip()
    if not testo or NON_DISPONIBILE in testo:
        return None, (
            "Le guide e la knowledge base non contengono la risposta: scrivi la FAQ a mano "
            "dalla scheda FAQ, oppure aggiorna prima la guida del modulo."
        )
    with transaction.atomic():
        bozza = AiKnowledgeEntry.objects.create(
            question=domanda[:500],
            answer=testo[:6000],
            source_label=SOURCE_LABEL_BOZZA,
            is_active=False,
            created_by=request.user,
            updated_by=request.user,
        )
        vecchie = {fb.knowledge_entry_id for fb in feedbacks if fb.knowledge_entry_id}
        AiChatFeedback.objects.filter(pk__in=[fb.pk for fb in feedbacks]).update(knowledge_entry=bozza)
        _elimina_bozze_orfane(vecchie)
    logger.info("ai_assistant: bozza FAQ %s da %s feedback (fonti: %s)", bozza.pk, len(feedbacks), len(fonti))
    return bozza, "Bozza pronta: controllala e approvala."


def _elimina_bozze_orfane(entry_ids) -> None:
    """Toglie le bozze spente che nessun feedback usa più (mai le FAQ attive)."""
    for entry in AiKnowledgeEntry.objects.filter(pk__in=list(entry_ids), is_active=False):
        if not entry.feedback_entries.exists():
            entry.delete()


def approva(request, ids: list[int], domanda: str, risposta: str) -> AiKnowledgeEntry | None:
    """Attiva la FAQ del gruppo (con eventuali correzioni dell'admin) e chiude i feedback."""
    from .services import clear_knowledge_cache

    domanda = (domanda or "").strip()[:500]
    risposta = (risposta or "").strip()[:6000]
    feedbacks = _feedback_del_gruppo(ids)
    if not feedbacks or not domanda or not risposta:
        return None
    with transaction.atomic():
        entry = next((fb.knowledge_entry for fb in feedbacks if fb.knowledge_entry_id), None)
        vecchie = {fb.knowledge_entry_id for fb in feedbacks if fb.knowledge_entry_id}
        if entry is None or entry.is_active:
            entry = AiKnowledgeEntry(created_by=request.user)
        entry.question = domanda
        entry.answer = risposta
        entry.source_label = "FAQ Portale"
        entry.is_active = True
        entry.updated_by = request.user
        entry.save()
        AiChatFeedback.objects.filter(pk__in=[fb.pk for fb in feedbacks]).update(
            knowledge_entry=entry, is_reviewed=True,
        )
        _elimina_bozze_orfane(vecchie - {entry.pk})
    clear_knowledge_cache()
    return entry


def scarta(ids: list[int]) -> int:
    """Chiude i feedback del gruppo senza FAQ; toglie le bozze rimaste orfane."""
    feedbacks = _feedback_del_gruppo(ids)
    vecchie = {fb.knowledge_entry_id for fb in feedbacks if fb.knowledge_entry_id}
    with transaction.atomic():
        AiChatFeedback.objects.filter(pk__in=[fb.pk for fb in feedbacks]).update(
            is_reviewed=True, knowledge_entry=None,
        )
        _elimina_bozze_orfane(vecchie)
    return len(feedbacks)
