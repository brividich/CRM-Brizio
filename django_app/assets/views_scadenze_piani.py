"""Pagina «Sposta nei piani»: anteprima con controllo doppioni e spostamento delle
scadenze amministrative nei piani di manutenzione (``services/scadenze_in_piani``)."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action

from .services import scadenze_in_piani as sp
from .views import _assets_shell_context
from .views_maintenance import can_manage_maintenance_plans

MESI_MAX = 120


def _mesi_scelti(request: HttpRequest, chiavi: list[str]) -> dict[str, int]:
    mesi: dict[str, int] = {}
    for chiave in chiavi:
        valore = (request.POST.get(f"mesi_{chiave}") or "").strip()
        if valore.isdigit() and 0 < int(valore) <= MESI_MAX:
            mesi[chiave] = int(valore)
    return mesi


@login_required
def scadenze_sposta_nei_piani(request: HttpRequest) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        messages.error(request, "Spostare le scadenze nei piani è riservato a chi configura i piani di manutenzione.")
        return redirect("assets:asset_administrative_deadline_list")
    if request.method == "POST":
        chiavi = [c for c in request.POST.getlist("scelta") if c and all(p.isdigit() for p in c.split(","))]
        if not chiavi:
            messages.warning(request, "Nessuna scadenza scelta.")
            return redirect("assets:scadenze_sposta_nei_piani")
        esito = sp.applica(chiavi, mesi=_mesi_scelti(request, chiavi), user=request.user)
        log_action(request, "scadenze_spostate_nei_piani", "assets", {
            "scelte": len(chiavi), "applicazioni": esito.applicazioni, "doppioni": esito.doppioni,
            "righe": esito.righe_spostate, "piani_creati": esito.piani_creati, "saltate": len(esito.saltate),
        })
        if esito.applicazioni or esito.doppioni:
            messages.success(
                request,
                f"Spostate {esito.righe_spostate} righe: {esito.applicazioni} applicazioni di piano "
                f"({esito.piani_creati} piani nuovi), {esito.doppioni} doppioni spenti, "
                f"{esito.occorrenze} manutenzioni generate.",
            )
        if esito.saltate:
            messages.warning(request, "Non spostate: " + "; ".join(esito.saltate[:20]))
        return redirect("assets:scadenze_sposta_nei_piani")

    analisi = sp.analizza()
    conteggi = [
        {"azione": azione, "label": label, "n": analisi.conta(azione)}
        for azione, label in sp.AZIONI_LABEL.items()
    ]
    return render(request, "assets/pages/scadenze_sposta_nei_piani.html", {
        **_assets_shell_context(request),
        "page_title": "Sposta nei piani",
        "analisi": analisi,
        "conteggi": conteggi,
        "mesi_max": MESI_MAX,
        "registro_url": reverse("assets:asset_administrative_deadline_list"),
    })
