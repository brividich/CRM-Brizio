"""Scadenzario Globale Unificato (`/scadenze`).

Vista aggregatrice cross-modulo: compone i provider per dominio
(`dashboard.scadenze_providers`) in un'unica tabella con filtri trasversali
(tipo/sorgente, stato, reparto) ed export CSV. Ogni sorgente rispetta l'ACL
del proprio modulo (gating dentro il provider).
"""
from __future__ import annotations

import csv
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from django.shortcuts import render

from .scadenze_providers import (
    PROVIDERS,
    SOURCE_LABELS,
    collect_all,
)

# Filtro stato → predicato sui giorni.
_STATI = {
    "scaduta": lambda g: g is not None and g < 0,
    "30": lambda g: g is not None and 0 <= g <= 30,
    "60": lambda g: g is not None and 0 <= g <= 60,
}


@login_required
def scadenze_globali(request: HttpRequest) -> HttpResponse:
    filtro_sorgente = request.GET.get("sorgente", "").strip()   # hr/asset/dpi/rentri/""
    filtro_stato = request.GET.get("stato", "").strip()          # scaduta/30/60/""
    filtro_reparto = request.GET.get("reparto", "").strip()
    export_csv = request.GET.get("format") == "csv"

    # Sorgenti da interrogare: solo quella selezionata, altrimenti tutte.
    if filtro_sorgente in PROVIDERS:
        sources = {filtro_sorgente}
    else:
        sources = None

    voci = collect_all(request, sources=sources)

    # Filtro stato (in memoria: le voci sono già normalizzate su `giorni`).
    if filtro_stato in _STATI:
        pred = _STATI[filtro_stato]
        voci = [v for v in voci if pred(v.giorni)]

    # Filtro reparto (case-insensitive).
    if filtro_reparto:
        rf = filtro_reparto.casefold()
        voci = [v for v in voci if v.reparto and v.reparto.casefold() == rf]

    # Export CSV (prima della paginazione: esporta il set filtrato completo).
    if export_csv:
        return _export_csv(voci)

    # KPI di sintesi.
    n_scadute = sum(1 for v in voci if v.scaduta)
    n_30gg = sum(1 for v in voci if not v.scaduta and v.giorni is not None and v.giorni <= 30)
    n_60gg = sum(1 for v in voci if not v.scaduta and v.giorni is not None and 30 < v.giorni <= 60)

    reparti = sorted({v.reparto for v in voci if v.reparto})

    paginator = Paginator(voci, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    context: dict[str, Any] = {
        "page_title": "Scadenzario globale",
        "page_obj": page_obj,
        "totale": len(voci),
        "n_scadute": n_scadute,
        "n_30gg": n_30gg,
        "n_60gg": n_60gg,
        "reparti": reparti,
        "sorgenti": [(code, SOURCE_LABELS[code]) for code in PROVIDERS],
        "filtro_sorgente": filtro_sorgente,
        "filtro_stato": filtro_stato,
        "filtro_reparto": filtro_reparto,
    }
    return render(request, "dashboard/pages/scadenze_globali.html", context)


def _export_csv(voci) -> HttpResponse:
    resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
    resp["Content-Disposition"] = 'attachment; filename="scadenzario_globale.csv"'
    resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
    writer = safe_csv_writer(resp, delimiter=";")
    writer.writerow(["Sorgente", "Tipo", "Soggetto", "Reparto", "Descrizione", "Scadenza", "Stato"])
    for v in voci:
        if v.scaduta:
            stato = f"Scaduta da {abs(v.giorni)} giorni"
        elif v.giorni is not None:
            stato = f"Scade tra {v.giorni} giorni"
        else:
            stato = ""
        writer.writerow([
            SOURCE_LABELS.get(v.source, v.source),
            v.kind_label,
            v.soggetto,
            v.reparto,
            v.titolo,
            v.data_scadenza.strftime("%d-%m-%Y") if v.data_scadenza else "",
            stato,
        ])
    return resp
