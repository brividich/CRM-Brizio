"""Avviso a chi entra nel team di un kickoff.

Prima chi veniva messo come PM, capocommessa, programmatore o caporeparto
(da «Nuovo kickoff» o «Modifica kickoff») non lo sapeva finché non apriva il
modulo. Ora riceve la campanella; chi fa la modifica non avvisa sé stesso.
"""
from __future__ import annotations

import logging

from django.urls import reverse

logger = logging.getLogger(__name__)


def team_attuale(project, ruoli) -> dict[str, set[int]]:
    return {ruolo: {u.pk for u in project.team_members(ruolo)} for ruolo in ruoli}


def avvisa_nuovi_membri(project, prima: dict[str, set[int]], *, etichette: dict[str, str], actor=None) -> int:
    """Campanella ai nuovi entrati per ruolo; ritorna quante ne sono partite."""
    from .notify import notify_user

    url = reverse("tasks:project_overview", kwargs={"project_id": project.pk})
    actor_id = getattr(actor, "pk", None)
    inviati = 0
    for ruolo, vecchi in prima.items():
        for user in project.team_members(ruolo):
            if user.pk in vecchi or user.pk == actor_id:
                continue
            try:
                notify_user(
                    user,
                    f"Sei nel team del kickoff «{project.name}» come {etichette.get(ruolo, ruolo)}.",
                    url,
                )
                inviati += 1
            except Exception:
                logger.exception("Avviso team kickoff non inviato (project=%s, user=%s)", project.pk, user.pk)
    return inviati
