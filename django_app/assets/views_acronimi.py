"""«Proponi acronimi» (``/assets/edit/acronimi/``): compila in blocco l'acronimo degli asset che non ce l'hanno.

Il percorso sta sotto ``/assets/edit/``: vale il permesso ACL «Modifica asset», senza
binding nuovi. Si lavora solo sugli asset visibili all'utente (``services/visibilita``)
e si scrive solo dove l'acronimo è ancora vuoto: niente viene sovrascritto.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action

from .models import Asset
from .services import acronimi
from .services.visibilita import filtra as filtra_visibili

GUIDA_ANCORA = "#acronimo"
PER_PAGINA = 200  # due campi per riga: resta sotto il limite Django di campi per POST
VISTE = ("proposte", "senza")


def _url(vista: str) -> str:
    return reverse("assets:acronimi_proponi") + ("" if vista == VISTE[0] else f"?vista={vista}")


@login_required
def acronimi_proponi(request: HttpRequest) -> HttpResponse:
    from .views import _assets_shell_context

    vista = request.GET.get("vista") if request.GET.get("vista") in VISTE else VISTE[0]
    visibili = filtra_visibili(request, Asset.objects.all())

    if request.method == "POST":
        scelte = {
            int(pk): request.POST.get(f"acr_{pk}", "")
            for pk in request.POST.getlist("sel")[:PER_PAGINA]
            if pk.isdigit()
        }
        salvati = acronimi.applica(visibili, scelte)
        if salvati:
            log_action(request, "asset_acronimi_compilati", "assets", {"asset": salvati})
            messages.success(request, f"{salvati} acronim{'o salvato' if salvati == 1 else 'i salvati'}.")
        else:
            messages.warning(request, "Nessun acronimo salvato: spunta almeno una riga con la sigla compilata.")
        return redirect(_url(vista))

    con, senza = acronimi.righe(visibili)
    elenco = con if vista == "proposte" else senza
    return render(request, "assets/pages/acronimi_proponi.html", {
        **_assets_shell_context(request, search_placeholder="Cerca asset, seriali o utenti"),
        "page_title": "Proponi acronimi",
        "vista": vista,
        "righe": elenco[:PER_PAGINA],
        "totale": len(elenco),
        "oltre": max(0, len(elenco) - PER_PAGINA),
        "n_proposte": len(con),
        "n_senza": len(senza),
        "url_proposte": _url("proposte"),
        "url_senza": _url("senza"),
        "guida_url": reverse("assets:guida") + GUIDA_ANCORA,
    })
