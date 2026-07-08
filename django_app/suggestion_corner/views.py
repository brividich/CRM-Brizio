"""Viste (sola lettura) del modulo Suggestion Corner.

Gating: `@login_required` + ACLMiddleware (binding canonico per rotta, vedi
acl_bootstrap.py). Lo scope dei dati è deciso da `permissions.visible_segnalazioni`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Elenco segnalazioni con scope per-utente.

    - team SMS / superuser: tutte + coda 'da gestire' (DA_CLASSIFICARE);
    - altri: solo le proprie + incarichi assegnati.
    """
    from .models import SuggestionCorner
    from .permissions import is_sms_team, visible_segnalazioni

    team = is_sms_team(request.user)
    segnalazioni = visible_segnalazioni(request.user).select_related(
        "reparto_provenienza", "incaricato", "controllore",
    )
    da_gestire = (
        segnalazioni.filter(stato=SuggestionCorner.Stato.DA_CLASSIFICARE)
        if team else SuggestionCorner.objects.none()
    )
    return render(request, "suggestion_corner/home.html", {
        "segnalazioni": segnalazioni,
        "da_gestire": da_gestire,
        "is_team": team,
    })


@login_required
def dettaglio(request, pk: int):
    """Dettaglio segnalazione (raffinato nel Task 4 con scope + storico)."""
    from django.shortcuts import get_object_or_404

    from .models import SuggestionCorner

    seg = get_object_or_404(SuggestionCorner, pk=pk)
    return render(request, "suggestion_corner/dettaglio.html", {"seg": seg})
