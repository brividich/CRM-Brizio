"""Storico campi dell'asset (PROMPT 06 - C): timeline "cosa e' cambiato" e vista alla data.

Frammento caricato dalle schede Monitoraggio e Tecnica e rete del dettaglio asset.
La route sta sotto ``/assets/view/<id>/`` con binding ACL v2 del dettaglio (0125):
chi vede la scheda vede il suo storico.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Asset
from .services import storico_asset


def _data(raw: str | None) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10]) if raw else None
    except ValueError:
        return None


@login_required
@require_GET
def asset_field_history(request: HttpRequest, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.only("id", "asset_tag", "name"), pk=id)
    gruppo = request.GET.get("gruppo") if request.GET.get("gruppo") in storico_asset.GRUPPI else ""
    campo = request.GET.get("campo") if request.GET.get("campo") in storico_asset.ETICHETTE else ""
    dal, al = _data(request.GET.get("dal")), _data(request.GET.get("al"))
    alla_data = _data(request.GET.get("alla_data"))
    campi = storico_asset.GRUPPI.get(gruppo) or list(storico_asset.ETICHETTE)
    stato = None
    if alla_data:
        fine_giornata = timezone.make_aware(datetime.combine(alla_data, time.max))
        stato = storico_asset.stato_alla_data(asset, fine_giornata)
    return render(request, "assets/partials/storico_campi.html", {
        "asset": asset,
        "voci": storico_asset.timeline(asset, gruppo=gruppo, campo=campo, dal=dal, al=al),
        "gruppo": gruppo,
        "campo": campo,
        "dal": dal,
        "al": al,
        "alla_data": alla_data,
        "stato_alla_data": stato,
        "gruppi": [("", "Tutto"), ("stato", "Stato"), ("assegnazione", "Assegnazione"), ("rete", "Rete")],
        "campi": [(c, storico_asset.ETICHETTE[c]) for c in campi],
        "url": reverse("assets:asset_field_history", kwargs={"id": asset.id}),
        # Solo id semplici: il valore finisce in id= e hx-target (niente selettori arbitrari).
        "target_id": target if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", target := request.GET.get("target") or "")
        else f"asset-storico-{asset.id}",
    })
