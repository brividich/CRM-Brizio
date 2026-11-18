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


@risposta_pubblica_con_form
@csrf_exempt  # il segreto nell'URL fa da protezione CSRF: un sito terzo non lo conosce
@require_http_methods(["GET", "POST"])
def approva_da_mail(request, token: str, decisione: str):
    """Link «Accetta» / «Rifiuta» della mail «Richiesta DPI da approvare» (dpi/approva_mail.py).

    GET mostra la richiesta e non cambia niente (anteprime e filtri della posta non decidono);
    POST decide come il destinatario della mail, se la richiesta aspetta ancora lui."""
    from django.db import transaction
    from django.urls import reverse

    from . import approva_mail, flusso
    from .models import RichiestaDPI

    letto = approva_mail.leggi(token) if decisione in approva_mail.DECISIONI else None
    if letto is None:
        return render(request, "dpi/pages/approva_da_mail.html", {"errore": True}, status=404)
    richiesta, email = letto
    if request.method == "POST":
        from .views import _approva, _rifiuta

        nota = request.POST.get("nota", "").strip()[:1000]
        deciso = False
        with transaction.atomic():
            # Riga bloccata: due clic insieme (o mail e portale) non decidono due volte.
            richiesta = RichiestaDPI.objects.select_for_update().select_related("categoria").get(pk=richiesta.pk)
            if approva_mail.puo_decidere(richiesta, email):
                autore, utente = approva_mail.nome(email), approva_mail.utente(email)
                if decisione == "approva":
                    _approva(request, richiesta, nota, autore=autore, utente=utente)
                else:
                    _rifiuta(request, richiesta, nota, autore=autore, utente=utente)
                deciso = True
        if not deciso:
            log_action(request, "dpi_decisione_mail_non_valida", "dpi", {
                "richiesta": richiesta.numero, "decisione": decisione, "actor": email, "stato": richiesta.stato,
            })
        return redirect(request.path)
    altra = "rifiuta" if decisione == "approva" else "approva"
    return render(request, "dpi/pages/approva_da_mail.html", {
        "richiesta": richiesta,
        "decisione": decisione,
        "riga_dpi": flusso._riga_dpi(richiesta),
        "puo_decidere": approva_mail.puo_decidere(richiesta, email),
        "nome": approva_mail.nome(email),
        "url_altra": reverse("dpi_pubblico:approva_da_mail", args=[token, altra]),
    })
