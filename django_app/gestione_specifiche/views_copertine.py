"""Personalizzazione delle copertine delle cartelle nel catalogo (colore, sigla, icona, logo)."""
from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.copertine import CopertinaNonValida
from core.copertine_librerie import NOMI as ICONE_NOMI, risposta_logo, salva_logo, togli_logo

from .admin_views import utente_puo_admin
from .models import CopertinaCliente


@login_required
@require_POST
def copertina_salva(request):
    cliente = (request.POST.get("cartella") or "").strip()[:200]
    torna = f"{reverse('gestione_specifiche:lista')}?{urlencode({'cartella': cliente or '_'})}"
    if not utente_puo_admin(request):
        messages.error(request, "Solo l'amministrazione del modulo cambia le copertine.")
        return redirect(torna)
    if not cliente:
        messages.error(request, "La copertina «Senza cartella» non si personalizza.")
        return redirect(torna)
    p, _ = CopertinaCliente.objects.get_or_create(chiave=cliente.lower())
    colore = (request.POST.get("colore") or "").strip()
    p.colore = colore if len(colore) == 7 and colore.startswith("#") and request.POST.get("colore_auto") != "1" else ""
    p.sigla = (request.POST.get("sigla") or "").strip()[:20].upper()
    icona = (request.POST.get("icona") or "").strip()
    p.icona = icona if icona in ICONE_NOMI else ""
    if request.POST.get("togli_logo"):
        togli_logo(p)
    elif request.FILES.get("logo"):
        try:
            salva_logo(p, request.FILES["logo"])
        except CopertinaNonValida as exc:
            messages.error(request, str(exc))
    p.save()
    log_action(request, "modifica", "gestione_specifiche", {"message": "Copertina cartella aggiornata", "cartella": cliente})
    messages.success(request, "Copertina aggiornata.")
    return redirect(torna)


@login_required
def copertina_logo(request, pk: int):
    return risposta_logo(get_object_or_404(CopertinaCliente, pk=pk).logo)
