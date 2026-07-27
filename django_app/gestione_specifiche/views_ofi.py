"""Modulo OFI standalone — Registro OFI/NC centralizzato (MOD.174, 4.2).

Il registro è uno **strumento trasversale del portale**, montato al top-level
``/ofi-registro/`` (namespace ``registro_ofi``): gli altri moduli lo *richiamano*
con filtri (es. ``?modulo=gestione_specifiche``), non lo possiedono. Il modello
``RegistroOFI`` vive in ``gestione_specifiche`` per continuità con la generazione
da MOD.133 e con ``AzioneOFI`` — dettaglio implementativo invisibile all'utente.

Viste: elenco fedele al MOD.174 (colonne + contatori cumulativi P/D/C/A + KPI),
inserimento e modifica manuale (ACL ``registroofi.add``). L'accesso è gated dai
``RoutePermissionBinding`` (ACL v2, vedi ``acl_bootstrap``); i pulsanti di
scrittura sono mostrati solo a chi ha il permesso.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.acl_v2 import request_has_permission_code

from . import registro_ofi as reg
from .acl_bootstrap import PERM_OFI_ADD
from .forms import RegistroOFIForm
from .models import RegistroOFI


def _voci_filtrate(request):
    """Applica i filtri GET (modulo/fase/priorità/scaduti) e ritorna (voci, ctx_filtri)."""
    fase = (request.GET.get("fase") or "").strip().upper()
    priorita = (request.GET.get("priorita") or "").strip().upper()
    modulo = (request.GET.get("modulo") or "").strip()
    solo_scaduti = request.GET.get("scaduti") == "1"

    qs = RegistroOFI.objects.all().select_related("content_type")
    if modulo:
        qs = qs.filter(modulo_origine=modulo)
    if fase in dict(RegistroOFI.FASE_CHOICES):
        qs = qs.filter(fase=fase)
    if priorita in dict(RegistroOFI.PRIORITA_CHOICES):
        qs = qs.filter(priorita=priorita)
    voci = list(qs)
    if solo_scaduti:
        voci = [v for v in voci if v.is_scaduto]
    return voci, {"fase": fase, "priorita": priorita, "modulo": modulo,
                  "solo_scaduti": solo_scaduti}


@login_required
def lista(request):
    """Registro OFI/NC (MOD.174) — elenco fedele all'Excel, a tutta larghezza.

    Nessun filtro modulo = registro UNICO (tutti i moduli); ``?modulo=<chiave>``
    = registro del singolo modulo. Contatori cumulativi P/D/C/A + KPI ≥90% (A/P)
    come la riga 2 del MOD.174.
    """
    voci, f = _voci_filtrate(request)
    modulo = f["modulo"]
    # Contatori/KPI coerenti col filtro modulo (il "mio" registro vs unico).
    base = RegistroOFI.objects.filter(modulo_origine=modulo) if modulo else RegistroOFI.objects.all()

    return render(request, "registro_ofi/lista.html", {
        "voci": voci,
        "counters": reg.conta_pdca_cumulativo(base),
        "n_scaduti": sum(1 for v in base if v.is_scaduto),
        "fase": f["fase"], "priorita": f["priorita"], "solo_scaduti": f["solo_scaduti"],
        "modulo": modulo, "modulo_label": reg.modulo_label(modulo) if modulo else "",
        "moduli_opts": reg.moduli_presenti(),
        "FASE_CHOICES": RegistroOFI.FASE_CHOICES,
        "PRIORITA_CHOICES": RegistroOFI.PRIORITA_CHOICES,
        "can_add": request_has_permission_code(request, PERM_OFI_ADD),
    })


@login_required
def nuovo(request):
    """Inserimento manuale di una voce OFI (ACL ``registroofi.add``).

    ``numero`` è assegnato server-side da ``prossimo_numero()`` (spazio numeri
    condiviso con l'OFI legacy). Voce del registro unico (``modulo_origine`` vuoto).
    """
    if request.method == "POST":
        form = RegistroOFIForm(request.POST)
        if form.is_valid():
            voce = form.save(commit=False)
            voce.numero = reg.prossimo_numero()
            voce.save()
            messages.success(request, f"OFI {voce.numero} creato.")
            return redirect("registro_ofi:lista")
    else:
        form = RegistroOFIForm()
    return render(request, "registro_ofi/form.html", {
        "form": form, "voce": None, "numero_preview": reg.prossimo_numero(),
        "moduli_esistenti": reg.moduli_presenti(),
    })


@login_required
def modifica(request, pk: int):
    """Modifica di una voce OFI (ACL ``registroofi.add``)."""
    voce = get_object_or_404(RegistroOFI, pk=pk)
    if request.method == "POST":
        form = RegistroOFIForm(request.POST, instance=voce)
        if form.is_valid():
            form.save()
            messages.success(request, f"OFI {voce.numero} aggiornato.")
            return redirect("registro_ofi:lista")
    else:
        form = RegistroOFIForm(instance=voce)
    return render(request, "registro_ofi/form.html", {
        "form": form, "voce": voce, "numero_preview": voce.numero,
        "moduli_esistenti": reg.moduli_presenti(),
    })


@login_required
def dettaglio(request, pk: int):
    """Scheda di sola lettura di una voce OFI, con le eventuali azioni collegate."""
    voce = get_object_or_404(
        RegistroOFI.objects.select_related("content_type").prefetch_related("azioni"), pk=pk)
    return render(request, "registro_ofi/dettaglio.html", {
        "voce": voce,
        "can_add": request_has_permission_code(request, PERM_OFI_ADD),
    })
