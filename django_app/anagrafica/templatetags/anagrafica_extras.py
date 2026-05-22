from __future__ import annotations

import logging

from django import template
from django.urls import NoReverseMatch, reverse


register = template.Library()
logger = logging.getLogger(__name__)


@register.filter(name="dictlookup")
def dictlookup(value, key):
    """Lookup ``value[key]`` con coercion safe a int/str e default ''.

    Permette nei template di scrivere ``mappa|dictlookup:obj.id`` per recuperare
    valori da un dict indicizzato per id (gli interi e le stringhe di interi
    sono considerati equivalenti).
    """
    if value is None or key is None:
        return ""
    try:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            try:
                ikey = int(key)
                if ikey in value:
                    return value[ikey]
            except (TypeError, ValueError):
                pass
            try:
                skey = str(key)
                if skey in value:
                    return value[skey]
            except Exception:
                pass
        return ""
    except Exception:
        return ""


@register.simple_tag(takes_context=True)
def subnav_anagrafica(context):
    """Carica categorie e link subnav anagrafica dal DB.

    Ritorna una struttura ``{"items": [...]}`` dove ogni item è:
    - ``{"type": "link", "label": ..., "url": ..., "active": bool, "target": ...}``
    - ``{"type": "category", "label": ..., "icona": ..., "links": [...], "active": bool}``
    """
    from anagrafica.models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica

    request = context.get("request")
    current_view = ""
    current_path = ""
    if request:
        try:
            current_view = request.resolver_match.view_name
        except Exception:
            pass
        current_path = getattr(request, "path", "")

    def _resolve_url(link):
        if link.url_type == "named":
            try:
                return reverse(link.url_value)
            except NoReverseMatch:
                return "#"
        return link.url_value

    def _is_active(link, resolved_url):
        if link.active_view_names:
            names = [n.strip() for n in link.active_view_names.split(",") if n.strip()]
            if current_view in names:
                return True
        if link.url_type == "raw" and resolved_url and resolved_url != "#":
            return current_path.startswith(resolved_url)
        return False

    def _build_link_item(link):
        resolved = _resolve_url(link)
        return {
            "type": "link",
            "label": link.etichetta,
            "icona": link.icona,
            "url": resolved,
            "active": _is_active(link, resolved),
            "target": "_blank" if link.apri_nuova_tab else "_self",
            "is_sistema": link.is_sistema,
            "id": link.pk,
        }

    try:
        categorie = list(SubnavCategoriaAnagrafica.objects.filter(is_active=True).prefetch_related("links"))
        cat_ids = {c.pk for c in categorie}
        links_qs = list(SubnavLinkAnagrafica.objects.filter(is_active=True).order_by("ordine", "etichetta"))
    except Exception:
        logger.exception("Errore caricamento subnav anagrafica")
        return {"items": []}

    cat_map = {c.pk: c for c in categorie}
    ungrouped = [l for l in links_qs if l.categoria_id is None or l.categoria_id not in cat_ids]
    grouped = {c.pk: [] for c in categorie}
    for link in links_qs:
        if link.categoria_id and link.categoria_id in grouped:
            grouped[link.categoria_id].append(link)

    items = []
    # Build ordered list: place grouped categories at their position based on min ordine of their links
    cat_ordine = {}
    for c in categorie:
        child_links = grouped.get(c.pk, [])
        if child_links:
            cat_ordine[c.pk] = min(l.ordine for l in child_links)
        else:
            cat_ordine[c.pk] = c.ordine

    # Merge ungrouped links and categories in order
    entries = []
    for link in ungrouped:
        entries.append(("link", link.ordine, link))
    for cat in categorie:
        child_links = grouped.get(cat.pk, [])
        if not child_links:
            continue
        entries.append(("cat", cat_ordine[cat.pk], (cat, child_links)))

    entries.sort(key=lambda e: e[1])

    for kind, _, obj in entries:
        if kind == "link":
            items.append(_build_link_item(obj))
        else:
            cat, child_links = obj
            built_children = [_build_link_item(l) for l in child_links]
            items.append({
                "type": "category",
                "label": cat.nome,
                "icona": cat.icona,
                "id": cat.pk,
                "active": any(c["active"] for c in built_children),
                "links": built_children,
            })

    return {"items": items}
