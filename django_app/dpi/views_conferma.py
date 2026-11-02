"""Pagina pubblica del link «Conferma la ricevuta dei DPI» (sotto /approval-actions/dpi/).

Il segreto nell'URL e' la credenziale: GET mostra cosa si conferma, POST decide
come il destinatario del link (non chi lo apre). Nessun login, nessun dato oltre
a nome, DPI e data della consegna.
"""
from __future__ import annotations

from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.audit import log_action
from core.public_headers import risposta_pubblica_con_form

from . import conferme


@risposta_pubblica_con_form
@csrf_exempt  # il segreto nell'URL fa da protezione CSRF: un sito terzo non lo conosce
@require_http_methods(["GET", "POST"])
def conferma_ricevuta(request, token: str, decisione: str):
    link = conferme.link_da_token(token) if decisione in conferme.DECISIONI else None
    if link is None:
        return render(request, "dpi/pages/conferma_ricevuta.html", {"errore": True}, status=404)
    conferma = link.conferma
    contesto = {
        "conferma": conferma,
        "decisione": decisione,
        "consegne": conferma.consegne.select_related(
            "richiesta", "richiesta__categoria", "richiesta__modello_dpi", "richiesta__taglia_dpi"
        ),
        "per_dipendente": conferma.destinatario_tipo == conferma.Destinatario.DIPENDENTE,
        "email": link.email,
    }
    if request.method == "POST":
        ok = conferme.decidi(link, decisione, request.POST.get("nota", "").strip())
        if ok:
            # Il modulo PDF nei documenti del dipendente riporta l'esito della conferma.
            from .views import _archivia_pdf_consegna

            for consegna in conferma.consegne.select_related("richiesta", "richiesta__categoria", "conferma"):
                _archivia_pdf_consegna(request, consegna)
        log_action(request, "dpi_conferma_ricevuta" if ok else "dpi_conferma_ricevuta_gia_decisa", "dpi", {
            "conferma": conferma.pk, "decisione": decisione, "actor": link.email,
        })
        return redirect(request.path)
    return render(request, "dpi/pages/conferma_ricevuta.html", contesto)
