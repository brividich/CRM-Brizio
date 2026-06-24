"""View dell'app gestione_specifiche.

F1: elenco base + download allegato protetto. L'elenco ricco con pill di stato,
filtri e azioni inline arriva in F7; il flusso MOD.133 (HTMX) in F3.
Gating: `@login_required` + ACLMiddleware (binding canonico per rotta).
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from . import constants as C
from .models import Specifica


@login_required
def lista(request):
    """Elenco specifiche (versione base F1, default = solo attive)."""
    mostra_storico = request.GET.get("storico") == "1"
    qs = Specifica.objects.all().select_related("mod133")
    if not mostra_storico:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    qs = qs.order_by("-data_inserimento", "codice")
    context = {
        "specifiche": qs[:500],
        "mostra_storico": mostra_storico,
        "tot": qs.count(),
    }
    return render(request, "gestione_specifiche/lista.html", context)


@login_required
def allegato_download(request, pk: int):
    """Download protetto dell'allegato di una specifica (storage privato)."""
    spec = get_object_or_404(Specifica, pk=pk)
    if not spec.allegato:
        raise Http404("Allegato non presente")
    try:
        fh = spec.allegato.open("rb")
    except FileNotFoundError as exc:
        raise Http404("File non trovato") from exc
    filename = spec.allegato.name.rsplit("/", 1)[-1]
    return FileResponse(fh, as_attachment=True, filename=filename)
