"""Viste (sola lettura) del modulo Suggestion Corner.

Gating: `@login_required` + ACLMiddleware (binding canonico per rotta, vedi
acl_bootstrap.py). Lo scope dei dati è deciso da `permissions.visible_segnalazioni`.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Elenco segnalazioni (raffinato nel Task 3 con queryset filtrati)."""
    from .models import SuggestionCorner

    segnalazioni = SuggestionCorner.objects.all().order_by("-data_segnalazione", "-id")
    return render(request, "suggestion_corner/home.html", {"segnalazioni": segnalazioni})


@login_required
def dettaglio(request, pk: int):
    """Dettaglio segnalazione (raffinato nel Task 4 con scope + storico)."""
    from django.shortcuts import get_object_or_404

    from .models import SuggestionCorner

    seg = get_object_or_404(SuggestionCorner, pk=pk)
    return render(request, "suggestion_corner/dettaglio.html", {"seg": seg})
