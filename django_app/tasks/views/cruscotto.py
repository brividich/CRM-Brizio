"""Cruscotto delle commesse: una riga per commessa dove chi guarda ha pieni poteri (capocommessa)."""
from __future__ import annotations

from urllib.parse import urlencode

from django.db.models import Q
from django.shortcuts import render

from ..access import ha_pieni_poteri, has_task_permission, scoped_projects_queryset, task_permissions_required
from ..services.filo import cruscotto
from ._shared import _tasks_shell_context


def _problema(r) -> bool:
    """Riga «Con problemi»: tappe in ritardo, consegna a rischio, ritardo sul piano o spostamenti da decidere."""
    tappe = r.get("tappe") or {}
    consegna = r.get("consegna") or {}
    return bool(
        r.get("ritardo") or consegna.get("a_rischio") or r.get("spostamenti")
        or (tappe.get("ha_piano") and (tappe.get("ritardo_piano") or 0) > 0)
    )


@task_permissions_required("tasks_view")
def cruscotto_commesse(request):
    stato = "chiuse" if request.GET.get("stato") == "chiuse" else "aperte"
    q = (request.GET.get("q") or "").strip()
    solo_problemi = request.GET.get("problemi") == "1"
    tutte = request.GET.get("tutte") == "1" and has_task_permission(request, "tasks_admin")

    base = scoped_projects_queryset(request).select_related("modello")
    if q:
        base = base.filter(
            Q(name__icontains=q) | Q(part_number__icontains=q) | Q(client_name__icontains=q)
            | Q(descrizione_pezzo__icontains=q)
        )

    def mie(qs):
        return [p for p in qs.order_by("-id")[:200] if tutte or ha_pieni_poteri(request, p)]

    aperte = mie(base.filter(chiuso_il__isnull=True))
    chiuse = mie(base.filter(chiuso_il__isnull=False))
    righe = cruscotto(request, chiuse if stato == "chiuse" else aperte)
    for r in righe:
        r["problema"] = _problema(r)
    n_problemi = sum(1 for r in righe if r["problema"])
    if solo_problemi:
        righe = [r for r in righe if r["problema"]]

    # Link dei filtri rapidi: tengono ricerca e «tutte».
    keep = urlencode({k: v for k, v in (("q", q), ("tutte", "1" if tutte else "")) if v})
    return render(request, "tasks/cruscotto.html", {
        **_tasks_shell_context(request, active="cruscotto"),
        "page_title": "Le mie commesse",
        "righe": righe,
        "stato": stato,
        "tutte": tutte,
        "q": q,
        "solo_problemi": solo_problemi,
        "n_aperte": len(aperte),
        "n_chiuse": len(chiuse),
        "n_problemi": n_problemi,
        "keep": keep,
        "puo_vedere_tutte": has_task_permission(request, "tasks_admin"),
    })
