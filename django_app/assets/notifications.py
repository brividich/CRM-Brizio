"""Notifiche in-app per gli interventi di manutenzione (OdL).

Il push dei reminder è collettivo (SiteConfig ``assets_reminder_emails`` → ADMINS → superuser):
il manutentore assegnato non riceveva nulla, né alla creazione né all'assegnazione né allo
scadere. Qui sta il ponte fra ``WorkOrder.assigned_to`` (utente Django) e ``core.notifiche``,
che indirizza per ``legacy_user_id``.
"""
from __future__ import annotations

from core.notifiche import invia_notifica

# Tipo già presente nel registro notifiche (core.models.Notifica.TIPI).
WORKORDER_NOTIFICA_TIPO = "asset_scadenza"


def legacy_user_id_for_user(user) -> int | None:
    """``legacy_user_id`` collegato a un utente Django, None se il profilo non esiste."""
    if user is None or not getattr(user, "pk", None):
        return None
    from core.models import Profile

    return Profile.objects.filter(user_id=user.pk).values_list("legacy_user_id", flat=True).first()


def workorder_url(workorder) -> str:
    return f"/assets/workorders/view/{workorder.pk}/"


def notify_user_about_workorder(user, workorder, message: str) -> bool:
    """Notifica in-app un singolo utente su un OdL. Ritorna True se la notifica è partita."""
    legacy_user_id = legacy_user_id_for_user(user)
    if not legacy_user_id:
        return False
    invia_notifica(legacy_user_id, WORKORDER_NOTIFICA_TIPO, message, workorder_url(workorder))
    return True


def notify_workorder_assigned(workorder, *, actor=None) -> bool:
    """Avvisa l'assegnatario che l'intervento è suo.

    Se l'assegnatario coincide con chi ha compiuto l'azione (tipico della presa in carico)
    non si notifica nulla: sarebbe rumore.
    """
    assignee = getattr(workorder, "assigned_to", None)
    if assignee is None:
        return False
    if actor is not None and getattr(actor, "pk", None) == assignee.pk:
        return False
    asset_tag = getattr(getattr(workorder, "asset", None), "asset_tag", "") or "asset"
    return notify_user_about_workorder(
        assignee,
        workorder,
        f"Ti è stato assegnato l'intervento #{workorder.pk}: {workorder.title} ({asset_tag}).",
    )


def notify_workorder_taken_over(workorder, *, previous_assignee, actor) -> bool:
    """Avvisa il precedente assegnatario che qualcun altro ha preso in carico l'intervento."""
    if previous_assignee is None or actor is None:
        return False
    if getattr(previous_assignee, "pk", None) == getattr(actor, "pk", None):
        return False
    who = actor.get_full_name() or actor.username
    return notify_user_about_workorder(
        previous_assignee,
        workorder,
        f"L'intervento #{workorder.pk} che ti era assegnato è stato preso in carico da {who}.",
    )
