"""Service di lettura della bacheca 'Documenti & Collegamenti'.

Funzioni pure che filtrano categorie/voci per ruolo legacy dell'utente.
Usato da: home (dashboard), pagina /bacheca/, download protetto.
"""
from __future__ import annotations

from core.models import HubLinkCategory


def link_visible_to_role(link, legacy_role_id, is_admin: bool) -> bool:
    """True se la voce è visibile all'utente con quel ruolo legacy.

    - is_visible=False ⇒ mai visibile (nemmeno all'admin, sulla bacheca pubblica).
    - is_admin ⇒ bypassa la restrizione di ruolo.
    - nessun HubLinkRoleAccess ⇒ visibile a tutti.
    - con record ⇒ visibile solo ai legacy_role_id con can_view=True.
    """
    if not link.is_visible:
        return False
    if is_admin:
        return True
    accesses = list(link.role_accesses.all())
    if not accesses:
        return True
    if legacy_role_id is None:
        return False
    return any(a.legacy_role_id == legacy_role_id and a.can_view for a in accesses)


def visible_bacheca(legacy_role_id, is_admin: bool = False, preview_limit=None) -> list[dict]:
    """Categorie visibili con le rispettive voci filtrate per ruolo.

    Ritorna: [{"category": HubLinkCategory, "items": [HubLink], "total": int, "more": int}]
    Le categorie senza voci visibili sono escluse.
    """
    categories = (
        HubLinkCategory.objects.filter(is_visible=True)
        .prefetch_related("links__role_accesses")
        .order_by("order", "name", "id")
    )
    result: list[dict] = []
    for cat in categories:
        items = [
            link for link in cat.links.all()
            if link_visible_to_role(link, legacy_role_id, is_admin)
        ]
        if not items:
            continue
        shown = items[:preview_limit] if preview_limit else items
        result.append({
            "category": cat,
            "items": shown,
            "total": len(items),
            "more": max(0, len(items) - len(shown)),
        })
    return result
