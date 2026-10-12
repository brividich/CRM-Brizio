"""Notifiche in-app del modulo KICK-OFF."""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from core.notifiche import invia_notifica

from ..models import (
    Project,
    Task,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _task_notify_users_queryset(task: Task):
    user_ids: set[int] = {task.created_by_id}
    if task.assigned_to_id:
        user_ids.add(task.assigned_to_id)
    user_ids.update(task.subscribers.values_list("id", flat=True))
    user_ids.discard(None)
    return User.objects.filter(id__in=user_ids).order_by("first_name", "last_name", "username")


def _project_notify_users_queryset(project: Project):
    task_rows = project.tasks.values_list("created_by_id", "assigned_to_id")
    user_ids: set[int] = {project.created_by_id}
    for created_by_id, assigned_to_id in task_rows:
        if created_by_id:
            user_ids.add(created_by_id)
        if assigned_to_id:
            user_ids.add(assigned_to_id)
    user_ids.update(project.tasks.values_list("subscribers__id", flat=True))
    user_ids.discard(None)
    return User.objects.filter(id__in=user_ids).order_by("first_name", "last_name", "username")


def _legacy_user_id_for_user(user) -> int | None:
    profile = getattr(user, "profile", None)
    if profile and getattr(profile, "legacy_user_id", None):
        try:
            return int(profile.legacy_user_id)
        except Exception:
            return None
    return None


def notify_user(user, message: str, url: str = "", *, tipo: str = "task") -> None:
    """Notifica in-app a un utente portale, se ha un id legacy collegato.

    Unico punto di uscita del modulo: passa da ``core.notifiche.invia_notifica``,
    che rispetta gli interruttori notifiche (globale admin + preferenza utente).
    Prima le notifiche delle attivita' scrivevano ``Notifica`` direttamente e
    ignoravano le preferenze.
    """
    legacy_user_id = _legacy_user_id_for_user(user)
    if not legacy_user_id:
        return
    invia_notifica(legacy_user_id, tipo, str(message or "")[:500], str(url or "")[:255])

