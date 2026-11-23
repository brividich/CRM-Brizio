"""«Organizzazione»: la pagina d'ingresso della sezione (numeri, collegamenti diretti, cose da fare).

Si apre a chi apre «Il mio team» (stesso permesso di rotta). I numeri della struttura compaiono
solo a chi vede la Struttura organizzativa; le tessere solo per le pagine che l'utente può aprire;
le richieste sono quelle della pagina «Da fare». Decide tutto ``services/organizzazione_panoramica.py``.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import organizzazione_panoramica


@login_required
def panoramica(request):
    ctx = organizzazione_panoramica.costruisci(request)
    ctx["page_title"] = "Organizzazione"
    return render(request, "anagrafica/pages/organizzazione_panoramica.html", ctx)
