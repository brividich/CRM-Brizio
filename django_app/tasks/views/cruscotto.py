"""Cruscotto delle commesse: una riga per commessa dove chi guarda ha pieni poteri (capocommessa, PM)."""
from __future__ import annotations

from django.shortcuts import render

from ..access import ha_pieni_poteri, has_task_permission, scoped_projects_queryset, task_permissions_required
from ..services.filo import cruscotto
from ._shared import _tasks_shell_context


@task_permissions_required("tasks_view")
def cruscotto_commesse(request):
    stato = request.GET.get("stato", "aperte")
    qs = scoped_projects_queryset(request).select_related("modello")
    qs = qs.filter(chiuso_il__isnull=False) if stato == "chiuse" else qs.filter(chiuso_il__isnull=True)
    tutte = request.GET.get("tutte") == "1" and has_task_permission(request, "tasks_admin")
    progetti = [p for p in qs.order_by("-id")[:200] if tutte or ha_pieni_poteri(request, p)]
    return render(request, "tasks/cruscotto.html", {
        **_tasks_shell_context(request, active="cruscotto"),
        "page_title": "Le mie commesse",
        "righe": cruscotto(request, progetti),
        "stato": stato,
        "tutte": tutte,
        "puo_vedere_tutte": has_task_permission(request, "tasks_admin"),
    })
