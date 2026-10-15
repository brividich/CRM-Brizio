"""Ricerca di Anagrafica: tendina mentre si scrive (HTMX ``?suggest=1``) e pagina dei risultati.

``?ambito=`` sceglie dove cercare (vedi ``services.ricerca_sezioni.AMBITI``): ``tutto`` dalla
dashboard del modulo, il nome della sezione dalla sua pagina d'ingresso. I gruppi di risultati
arrivano già filtrati per permesso: la view non ne aggiunge e non ne toglie.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import ricerca_sezioni


@login_required
def ricerca(request):
    q = (request.GET.get("q") or "").strip()[:100]
    ambito = request.GET.get("ambito") or "tutto"
    if ambito not in ricerca_sezioni.AMBITI:
        ambito = "tutto"
    gruppi = ricerca_sezioni.cerca(request, q, ambito)
    contesto = {
        "q": q, "ambito": ambito, "ambito_label": ricerca_sezioni.AMBITI[ambito], "gruppi": gruppi,
        "totale": sum(len(g.voci) for g in gruppi), "troppo_corta": 0 < len(q) < ricerca_sezioni.MIN_CARATTERI,
        "ambiti": ricerca_sezioni.AMBITI,
    }
    if request.headers.get("HX-Request") and request.GET.get("suggest"):
        return render(request, "anagrafica/partials/_ricerca_suggest.html", contesto)
    return render(request, "anagrafica/pages/ricerca.html", contesto)
