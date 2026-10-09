"""Timeline sicurezza del dipendente + audit formale, in un punto solo.

Ogni generazione, chiusura, annullamento o deroga lascia due tracce:

- un ``EventoSicurezzaDipendente`` (timeline per dipendente, leggibile nella
  scheda, scritto anche dai job notturni senza request);
- una riga ``core.AuditLog`` via ``log_action`` (audit formale del portale).

Il payload è **non clinico** per costruzione: chi chiama passa id, codici ed
etichette di mansione/adempimento, mai esiti, prescrizioni o referti.
L'evento è scritto nella stessa transazione del dato che descrive; l'audit
formale parte dopo il commit (``log_action`` è fire-and-forget).
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

logger = logging.getLogger(__name__)

# Chiavi che non devono mai finire nel payload (difesa in profondità).
_CHIAVI_CLINICHE = {"esito", "prescrizioni", "limitazioni", "referto", "diagnosi", "note_cliniche"}


def _attore(user) -> tuple[Any, str]:
    if user is not None and getattr(user, "is_authenticated", False):
        nome = (user.get_full_name() or user.get_username() or "").strip()
        return user, nome[:150]
    return None, "Sistema"


def registra(
    legacy_id: int,
    tipo: str,
    descrizione: str,
    *,
    user=None,
    request=None,
    data_effetto=None,
    payload: dict | None = None,
    oggetto=None,
):
    """Scrive l'evento di timeline e accoda l'audit formale dopo il commit."""
    from ..models_mansioni_rischio import EventoSicurezzaDipendente

    if request is not None and user is None:
        user = getattr(request, "user", None)
    actor, actor_display = _attore(user)
    dati = {k: v for k, v in (payload or {}).items() if k not in _CHIAVI_CLINICHE}
    evento = EventoSicurezzaDipendente.objects.create(
        legacy_anagrafica_id=int(legacy_id),
        tipo=tipo,
        descrizione=(descrizione or "")[:300],
        data_effetto=data_effetto,
        payload=dati,
        actor=actor,
        actor_display=actor_display,
        oggetto_tipo=(oggetto._meta.label_lower if oggetto is not None else "")[:60],
        oggetto_id=getattr(oggetto, "pk", None),
    )

    def _audit():
        try:
            from core.audit import log_action
            log_action(
                request, f"sicurezza_{tipo.lower()}", "anagrafica",
                {"legacy_anagrafica_id": int(legacy_id), "descrizione": evento.descrizione, **dati},
                oggetto_tipo="anagrafica.dipendente", oggetto_id=str(int(legacy_id)),
            )
        except Exception:
            logger.warning("audit evento sicurezza %s non scritto", evento.pk, exc_info=True)

    transaction.on_commit(_audit)
    return evento


def timeline(legacy_ids, *, limite: int = 100):
    """Eventi di timeline di una persona (tutti i suoi id), dal più recente."""
    from ..models_mansioni_rischio import EventoSicurezzaDipendente

    ids = [int(i) for i in legacy_ids]
    return list(
        EventoSicurezzaDipendente.objects
        .filter(legacy_anagrafica_id__in=ids)
        .select_related("actor")
        .order_by("-occorso_il", "-pk")[:limite]
    )
