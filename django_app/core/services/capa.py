"""Service CAPA — Azioni Correttive/Preventive (modello `core.ActionItem`).

Single source of truth per:
- creare un'azione collegata a un evento di origine (incidente, anomalia, ...)
  e notificare il responsabile assegnato (centro notifiche C1);
- recuperare le azioni collegate a un record di origine (pannello embeddabile
  nei detail dei moduli di dominio + provider scadenzario globale C5);
- transizioni di stato del workflow (chiusura con evidenza → verifica).

I moduli di dominio chiamano `crea_action_item(...)` senza dipendere dal layer
di presentazione CAPA; il modello vive in `core` per evitare import ciclici.
"""
from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone

from core.models import ActionItem

logger = logging.getLogger(__name__)


def _legacy_user_id_for(user) -> int | None:
    """Risolve il legacy_user_id di un utente Django via Profile (per le notifiche)."""
    if user is None:
        return None
    try:
        profile = getattr(user, "profile", None)
        if profile is not None and profile.legacy_user_id:
            return int(profile.legacy_user_id)
    except Exception:
        logger.debug("CAPA: impossibile risolvere legacy_user_id per user=%s", getattr(user, "id", None))
    return None


def notifica_responsabile(action: ActionItem) -> None:
    """Notifica in-app al responsabile dell'azione (fire-and-forget)."""
    legacy_id = _legacy_user_id_for(action.responsabile)
    if not legacy_id:
        return
    from core.notifiche import invia_notifica

    scad = f" (scadenza {action.data_scadenza:%d/%m/%Y})" if action.data_scadenza else ""
    url = ""
    try:
        from django.urls import reverse
        url = reverse("capa_detail", args=[action.pk])
    except Exception:
        pass
    invia_notifica(
        legacy_user_id=legacy_id,
        tipo="generico",
        messaggio=f"Ti è stata assegnata un'azione CAPA: «{action.titolo}»{scad}.",
        url_azione=url,
    )


def crea_action_item(
    *,
    titolo: str,
    source_code: str = ActionItem.ORIGINE_MANUALE,
    source_pk: str | int = "",
    descrizione: str = "",
    tipo: str = ActionItem.TIPO_CORRETTIVA,
    responsabile=None,
    reparto: str = "",
    data_scadenza: date | None = None,
    source_label: str = "",
    source_url: str = "",
    created_by=None,
    notify: bool = True,
) -> ActionItem:
    """Crea un'azione CAPA collegata a un evento di origine e notifica il responsabile.

    `source_code`/`source_pk` seguono lo schema di automation_event_queue
    (es. ``source_code="rilevazione_incidenti"``, ``source_pk=str(incidente_id)``).
    Pensato per essere chiamato dalle view dei moduli di dominio.
    """
    action = ActionItem.objects.create(
        titolo=(titolo or "").strip()[:255] or "Azione senza titolo",
        descrizione=descrizione or "",
        tipo=tipo if tipo in dict(ActionItem.TIPO_CHOICES) else ActionItem.TIPO_CORRETTIVA,
        source_code=(source_code or ActionItem.ORIGINE_MANUALE).strip()[:64],
        source_pk=str(source_pk or "").strip()[:64],
        source_label=(source_label or "").strip()[:255],
        source_url=(source_url or "").strip()[:255],
        responsabile=responsabile,
        reparto=(reparto or "").strip()[:200],
        data_scadenza=data_scadenza,
        created_by=created_by,
    )
    if notify:
        notifica_responsabile(action)
    return action


def azioni_collegate(source_code: str, source_pk: str | int):
    """Queryset delle azioni CAPA collegate a un record di origine.

    Usato dal pannello embeddabile nei detail dei moduli e dal provider
    dello scadenzario globale.
    """
    return (
        ActionItem.objects
        .filter(source_code=(source_code or "").strip(), source_pk=str(source_pk or "").strip())
        .select_related("responsabile")
        .order_by("-created_at")
    )


def chiudi_azione(action: ActionItem, *, utente, evidenza: str) -> bool:
    """Marca l'azione come CHIUSA registrando l'evidenza. Ritorna False se manca l'evidenza.

    La chiusura è l'esecuzione del rimedio: richiede sempre un'evidenza testuale.
    Non è la verifica di efficacia (passo separato, vedi `verifica_azione`).
    """
    evidenza = (evidenza or "").strip()
    if not evidenza:
        return False
    action.evidenza_chiusura = evidenza
    action.chiusa_da = utente
    action.data_chiusura = timezone.now()
    action.stato = ActionItem.STATO_CHIUSA
    action.save(update_fields=["evidenza_chiusura", "chiusa_da", "data_chiusura", "stato", "updated_at"])
    return True


def verifica_azione(action: ActionItem, *, utente, note: str = "") -> None:
    """Verifica di efficacia: marca VERIFICATA. Passo distinto dalla chiusura (4 occhi)."""
    action.verificata_da = utente
    action.data_verifica = timezone.now()
    action.note_verifica = (note or "").strip()
    action.stato = ActionItem.STATO_VERIFICATA
    action.save(update_fields=["verificata_da", "data_verifica", "note_verifica", "stato", "updated_at"])
