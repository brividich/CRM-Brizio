"""Storico delle conversazioni con l'assistente AI.

Regole (decise il 12/10/2026):

- si salvano le conversazioni dell'utente, visibili **solo al proprietario**: ogni
  lettura e cancellazione filtra per ``utente=request.user``, nessuna vista admin dei
  contenuti (agli amministratori solo conteggi aggregati);
- conservazione ``AI_CHAT_HISTORY_RETENTION_DAYS`` (default 90) giorni dall'ultimo
  messaggio, poi il job notturno le cancella;
- per una conversazione salvata lo storico passato al modello si legge dal DB (non
  dal browser): stessi limiti di prima, ultimi ``OLLAMA_CHAT_MAX_HISTORY_MESSAGES``.

Spegnibile con ``AI_CHAT_HISTORY_ENABLED=False``: la chat torna a non salvare nulla.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AiConversation, AiConversationMessage

MAX_CONTENT_CHARS = 20000
MAX_SOURCES = 30
MAX_LIST = 100


def abilitato() -> bool:
    return bool(getattr(settings, "AI_CHAT_HISTORY_ENABLED", True))


def giorni_conservazione() -> int:
    try:
        return max(1, int(getattr(settings, "AI_CHAT_HISTORY_RETENTION_DAYS", 90) or 90))
    except (TypeError, ValueError):
        return 90


def _utente(request):
    user = getattr(request, "user", None)
    return user if getattr(user, "is_authenticated", False) else None


def _titolo_da(testo: str) -> str:
    titolo = re.sub(r"\s+", " ", str(testo or "")).strip()
    return titolo if len(titolo) <= 80 else titolo[:79].rstrip() + "…"


def conversazione_di(request, conversation_id: Any) -> AiConversation | None:
    """La conversazione se appartiene all'utente corrente, altrimenti None."""
    user = _utente(request)
    if user is None:
        return None
    try:
        pk = int(conversation_id)
    except (TypeError, ValueError):
        return None
    return AiConversation.objects.filter(pk=pk, utente=user).first()


def storico_per_modello(conversazione: AiConversation) -> list[dict[str, str]]:
    """Ultimi messaggi della conversazione nel formato ``history`` della chat."""
    limite = int(getattr(settings, "OLLAMA_CHAT_MAX_HISTORY_MESSAGES", 6) or 6)
    ultimi = list(
        conversazione.messaggi.order_by("-created_at", "-id").values("ruolo", "contenuto")[:limite]
    )
    return [{"role": m["ruolo"], "content": m["contenuto"]} for m in reversed(ultimi)]


def _fonti_pulite(fonti: Iterable[Any] | None) -> list[str]:
    pulite: list[str] = []
    for fonte in list(fonti or [])[:MAX_SOURCES]:
        testo = str(fonte or "").strip()[:300]
        if testo and testo not in pulite:
            pulite.append(testo)
    return pulite


def registra_turno(
    request,
    *,
    conversation_id: Any,
    domanda: str,
    risposta: str,
    fonti: Iterable[Any] | None = None,
    modello: str = "",
    rigenera: bool = False,
) -> AiConversation | None:
    """Salva domanda e risposta; crea la conversazione se ``conversation_id`` non è dell'utente.

    Con ``rigenera`` la domanda è già salvata: si sostituisce l'ultima risposta.
    Ritorna None se lo storico è spento o l'utente non è autenticato.
    """
    if not abilitato():
        return None
    user = _utente(request)
    if user is None or not (risposta or "").strip():
        return None
    with transaction.atomic():
        conversazione = conversazione_di(request, conversation_id)
        if conversazione is None:
            conversazione = AiConversation.objects.create(utente=user, titolo=_titolo_da(domanda))
            rigenera = False
        if rigenera:
            ultima = conversazione.messaggi.order_by("-created_at", "-id").first()
            if ultima is not None and ultima.ruolo == AiConversationMessage.ROLE_ASSISTANT:
                ultima.delete()
            ultima_domanda = conversazione.messaggi.order_by("-created_at", "-id").first()
            if ultima_domanda is None or ultima_domanda.ruolo != AiConversationMessage.ROLE_USER:
                rigenera = False
        if not rigenera:
            AiConversationMessage.objects.create(
                conversazione=conversazione,
                ruolo=AiConversationMessage.ROLE_USER,
                contenuto=str(domanda or "")[:MAX_CONTENT_CHARS],
            )
        AiConversationMessage.objects.create(
            conversazione=conversazione,
            ruolo=AiConversationMessage.ROLE_ASSISTANT,
            contenuto=str(risposta)[:MAX_CONTENT_CHARS],
            fonti=_fonti_pulite(fonti),
            modello=str(modello or "")[:120],
        )
        # auto_now: l'ultimo messaggio sposta la conversazione in cima e ne rinnova la scadenza.
        conversazione.save(update_fields=["updated_at"])
    return conversazione


def elenco(request) -> list[dict[str, Any]]:
    user = _utente(request)
    if user is None:
        return []
    righe = AiConversation.objects.filter(utente=user).order_by("-updated_at", "-id")[:MAX_LIST]
    return [
        {
            "id": c.pk,
            "titolo": c.titolo or "Conversazione",
            "updated_at": timezone.localtime(c.updated_at).isoformat(),
        }
        for c in righe
    ]


def dettaglio(conversazione: AiConversation) -> dict[str, Any]:
    return {
        "id": conversazione.pk,
        "titolo": conversazione.titolo or "Conversazione",
        "messaggi": [
            {
                "role": m.ruolo,
                "content": m.contenuto,
                "sources": list(m.fonti or []),
                "model": m.modello,
                "created_at": timezone.localtime(m.created_at).isoformat(),
            }
            for m in conversazione.messaggi.order_by("created_at", "id")
        ],
    }


def elimina(request, conversation_id: Any) -> bool:
    conversazione = conversazione_di(request, conversation_id)
    if conversazione is None:
        return False
    conversazione.delete()
    return True


def elimina_tutte(request) -> int:
    user = _utente(request)
    if user is None:
        return 0
    qs = AiConversation.objects.filter(utente=user)
    numero = qs.count()
    qs.delete()
    return numero


def pulisci_scadute(*, giorni: int | None = None, adesso=None) -> int:
    """Cancella le conversazioni senza messaggi da più di ``giorni``. Ritorna quante."""
    giorni = giorni or giorni_conservazione()
    limite = (adesso or timezone.now()) - timedelta(days=giorni)
    qs = AiConversation.objects.filter(updated_at__lt=limite)
    numero = qs.count()
    if numero:
        # Prima i messaggi, a blocchi: niente cascade enorme in un solo statement.
        ids = list(qs.values_list("pk", flat=True))
        for i in range(0, len(ids), 500):
            blocco = ids[i:i + 500]
            AiConversationMessage.objects.filter(conversazione_id__in=blocco).delete()
            AiConversation.objects.filter(pk__in=blocco).delete()
    return numero


def statistiche() -> dict[str, int]:
    """Solo conteggi aggregati, per la console admin."""
    return {
        "conversazioni": AiConversation.objects.count(),
        "messaggi": AiConversationMessage.objects.count(),
        # order_by() vuoto: l'ordering di Meta finirebbe nel SELECT DISTINCT (SQL Server).
        "utenti": AiConversation.objects.order_by().values("utente").distinct().count(),
        "giorni_conservazione": giorni_conservazione(),
    }
