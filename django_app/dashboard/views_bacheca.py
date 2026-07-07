from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from core.audit import log_action
from core.hub_bacheca import link_visible_to_role, visible_bacheca
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import HubLink


def _identity(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    role_id = getattr(legacy_user, "ruolo_id", None)
    return legacy_user, is_admin, role_id


@login_required
def bacheca(request):
    _, is_admin, role_id = _identity(request)
    groups = visible_bacheca(role_id, is_admin=is_admin, preview_limit=None)
    from dashboard.views_home_portale import _KIND_LABEL
    view_groups = [{
        "name": g["category"].name,
        "slug": g["category"].slug,
        "icon": g["category"].icon,
        "items": [{
            "title": l.title, "description": l.description, "kind": l.kind,
            "kind_label": _KIND_LABEL.get(l.kind, ""), "href": l.resolve_href(),
            "open_in_new_tab": bool(l.open_in_new_tab or l.kind == HubLink.KIND_URL),
        } for l in g["items"]],
    } for g in groups]

    # Gruppo virtuale «Procedure SGI»: documenti procedura consultabili (esclusi i
    # sensibili). Le voci sono già nella forma dict attesa dal template.
    try:
        from procedure_refresh.bacheca import build_procedure_group

        proc = build_procedure_group(role_id, is_admin=is_admin, preview_limit=None)
        if proc:
            view_groups.append({
                "name": proc["category"].name,
                "slug": proc["category"].slug,
                "icon": proc["category"].icon,
                "items": proc["items"],
            })
    except Exception:
        import logging

        logging.getLogger(__name__).exception("bacheca: gruppo Procedure SGI non disponibile")

    return render(request, "dashboard/pages/bacheca.html", {
        "page_title": "Documenti & Collegamenti",
        "bacheca_groups": view_groups,
    })


@login_required
def hub_link_download(request, pk: int):
    link = get_object_or_404(HubLink, pk=pk, kind=HubLink.KIND_FILE)
    _, is_admin, role_id = _identity(request)
    if not link_visible_to_role(link, role_id, is_admin) or not link.file:
        raise Http404()
    log_action(request, "download", "bacheca", {"link_id": link.pk, "title": link.title})
    filename = link.original_filename or link.file.name.rsplit("/", 1)[-1]
    return FileResponse(link.file.open("rb"), as_attachment=True, filename=filename)
