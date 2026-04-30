"""
Partial views HTMX per il lazy loading dei widget della dashboard personale.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string

from core.legacy_utils import get_legacy_user, is_legacy_admin

from .views import (
    _ALLOWED_WIDGET_IDS,
    _anomalie_access_flags,
    _get_employee_board_widget_data,
    _load_employee_board_config,
    _widget_def_map,
)


@login_required
def widget_partial(request, widget_id: str):
    """
    HTMX partial — ritorna l'innerHTML del body di un singolo widget dashboard.
    Attivato via hx-trigger="load" sulla card widget al caricamento della pagina.
    """
    if not getattr(request, "htmx", None):
        return redirect("dashboard_home")

    if widget_id not in _ALLOWED_WIDGET_IDS:
        return HttpResponse('<div class="eb-empty">Widget non disponibile</div>')

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None

    if widget_id == "anomalie_gestione" and not _anomalie_access_flags(request)["can_view_anomalie_list"]:
        return HttpResponse('<div class="eb-empty">Accesso non consentito</div>', status=403)

    board_cfg = _load_employee_board_config(legacy_user_id)
    widget_def = _widget_def_map().get(widget_id)
    if not widget_def:
        return HttpResponse('<div class="eb-empty">Widget non disponibile</div>')

    params = {
        **widget_def.get("default_params", {}),
        **board_cfg.get("widget_configs", {}).get(widget_id, {}),
    }
    data = _get_employee_board_widget_data(
        widget_id,
        request_user=request.user,
        legacy_user=legacy_user,
        legacy_user_id=legacy_user_id,
        is_admin=is_admin,
        params=params,
    )

    html = render_to_string(
        "dashboard/partials/widget_body.html",
        {
            "w": widget_def,
            "widget_data": {widget_id: data},
        },
        request=request,
    )
    return HttpResponse(html)
