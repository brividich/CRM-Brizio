"""Classificazione e coefficienti delle mansioni di una persona; costo orario (ottobre 2026).

- «Classificazione e coefficienti»: per ogni mansione svolta Diretto/Indiretto
  1T/2T e il coefficiente (somma 1). La vede e la salva chi vede il Mansionario
  (amministrazione anagrafica o HR).
- «Costo orario»: RML del mese ÷ giorni ÷ ore, uno per persona e mese. Dato
  retributivo: solo con il permesso HR riservato; ogni lettura va nell'audit.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from core.audit import log_action, log_consultazione

from .models import CostoOrarioMensile
from .services import costo_orario as costo_svc
from .services import mansioni_coefficienti as coeff_svc
from .views_mansionario import _nega, _puo_vedere

MODULE = "anagrafica"


def _nome(legacy_id: int) -> tuple[str, dict | None]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    righe = fetch_anagrafica_rows(ids=[legacy_id])
    if not righe:
        return f"#{legacy_id}", None
    return naming.nome_completo(righe[0].get("nome"), righe[0].get("cognome")), righe[0]


@login_required
def mansioni_coefficienti(request, legacy_id: int):
    if not _puo_vedere(request):
        return _nega(request)
    nome, dip = _nome(legacy_id)
    if dip is None:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:mansionario")
    if request.method == "POST":
        try:
            if request.POST.get("azione") == "uguale":
                coeff_svc.ripartisci_uguale(legacy_id, user=request.user)
                messages.success(request, "Coefficienti ripartiti in parti uguali.")
            else:
                righe = {}
                for chiave in request.POST:
                    if chiave.startswith("classe_"):
                        pk = int(chiave.removeprefix("classe_"))
                        righe[pk] = (request.POST.get(chiave, ""), request.POST.get(f"coeff_{pk}", ""))
                coeff_svc.salva(legacy_id, righe, prevalente_scelta=request.POST.get("prevalente", ""),
                                user=request.user)
                messages.success(request, "Classificazione e coefficienti salvati.")
            log_action(request, "mansioni_coefficienti_salva", MODULE,
                       {"legacy_id": legacy_id, "azione": request.POST.get("azione") or "salva"},
                       oggetto_tipo="dipendente", oggetto_id=str(legacy_id))
            return redirect("anagrafica:mansioni_coefficienti", legacy_id=legacy_id)
        except ValueError as exc:
            messages.error(request, str(exc))

    tutte = list(coeff_svc.AbilitazioneMacchina.objects
                 .filter(legacy_anagrafica_id=legacy_id, in_lista=True, competenza__isnull=False)
                 .select_related("competenza__area", "competenza__reparto")
                 .prefetch_related("competenza__ruoli").order_by("competenza__display"))
    inviato = request.POST if request.method == "POST" else {}
    righe = []
    for ab in tutte:
        conta = ab.stato == ab.STATO_ATTIVA
        righe.append({
            "ab": ab, "conta": conta,
            "ruoli": ", ".join(r.nome for r in ab.competenza.ruoli.all()),
            "classe": inviato.get(f"classe_{ab.pk}", ab.classificazione),
            "coeff": inviato.get(f"coeff_{ab.pk}", "" if ab.coefficiente is None
                                   else f"{ab.coefficiente:.4f}".replace(".", ",")),
        })
    stato = coeff_svc.stato(legacy_id)
    return render(request, "anagrafica/pages/mansioni_coefficienti.html", {
        "page_title": f"{nome} · coefficienti",
        "legacy_id": legacy_id, "nome": nome, "righe": righe, "stato": stato,
        "classificazioni": coeff_svc.CLASSIFICAZIONI.items(),
        "prevalente": inviato.get("prevalente", stato["prevalente"]),
    })


# ── Costo orario ─────────────────────────────────────────────────────────────

def _puo_costo(request) -> bool:
    from .views import _check_hr_permission

    return _check_hr_permission(request)


def _righe_costo(request):
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    mesi = list(CostoOrarioMensile.objects.order_by("-mese").values_list("mese", flat=True).distinct())
    try:
        mese = date.fromisoformat(request.GET.get("mese", "")) if request.GET.get("mese") else None
    except ValueError:
        mese = None
    if mese not in mesi:
        mese = mesi[0] if mesi else None
    righe = list(CostoOrarioMensile.objects.filter(mese=mese)) if mese else []
    ids = [r.legacy_anagrafica_id for r in righe if r.legacy_anagrafica_id]
    anag = {int(d["id"]): d for d in fetch_anagrafica_rows(ids=ids)} if ids else {}
    stati = coeff_svc.stati(ids) if ids else {}
    out = []
    for r in righe:
        d = anag.get(r.legacy_anagrafica_id or -1) or {}
        out.append({
            "c": r, "legacy_id": r.legacy_anagrafica_id,
            "nome": naming.nome_completo(d.get("nome"), d.get("cognome")) if d else r.tax_code,
            "ordine": naming.chiave_ordinamento(d.get("nome"), d.get("cognome")) if d else r.tax_code,
            "reparto": (d.get("reparto") or "").strip(),
            "classe": stati.get(r.legacy_anagrafica_id, {}).get("classe_principale_label", ""),
        })
    q = (request.GET.get("q") or "").strip().casefold()
    reparto = (request.GET.get("reparto") or "").strip()
    reparti = sorted({x["reparto"] for x in out if x["reparto"]}, key=str.casefold)
    if q:
        out = [x for x in out if q in x["nome"].casefold() or q in x["c"].tax_code.casefold()]
    if reparto:
        out = [x for x in out if x["reparto"] == reparto]
    out.sort(key=lambda x: x["ordine"])
    return {"mesi": mesi, "mese": mese, "righe": out, "reparti": reparti, "q": request.GET.get("q", ""),
            "reparto": reparto}


@login_required
def costo_orario(request):
    if not _puo_costo(request):
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")
    if request.method == "POST":
        try:
            if request.POST.get("azione") == "divisori":
                giorni, ore = costo_svc.imposta_divisori(request.POST.get("giorni"), request.POST.get("ore"))
                n = costo_svc.ricalcola()
                messages.success(request, f"Divisori salvati ({giorni.normalize():f} giorni × "
                                          f"{ore.normalize():f} ore): ricalcolati {n} costi orari.")
            else:
                n = costo_svc.ricalcola()
                messages.success(request, f"Ricalcolati {n} costi orari.")
            log_action(request, "costo_orario_ricalcola", MODULE, {"azione": request.POST.get("azione") or "tutto"})
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(request.get_full_path())
    log_consultazione(request, "COSTO_ORARIO_VISUALIZZATO", MODULE,
                      {"filtri": sorted(k for k in request.GET.keys())}, chiave="costo_orario")
    ctx = _righe_costo(request)
    giorni, ore = costo_svc.divisori()
    return render(request, "anagrafica/pages/costo_orario.html", {
        **ctx, "page_title": "Costo orario", "giorni": giorni, "ore": ore, "ore_mese": giorni * ore,
        "export_url": f"{reverse('anagrafica:costo_orario_export')}?{request.GET.urlencode()}",
    })


@login_required
def costo_orario_export(request):
    if not _puo_costo(request):
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")
    from core.excel_export import make_xlsx_response

    ctx = _righe_costo(request)
    log_action(request, "COSTO_ORARIO_ESPORTATO", MODULE,
               {"mese": str(ctx["mese"] or ""), "righe": len(ctx["righe"])})
    righe = [[x["nome"], x["reparto"], x["classe"], x["c"].mese, float(x["c"].rml),
              float(x["c"].divisore_giorni), float(x["c"].divisore_ore), float(x["c"].costo_orario),
              "sì" if x["c"].rml_manuale else ""] for x in ctx["righe"]]
    mese = ctx["mese"]
    return make_xlsx_response(
        filename=f"costo_orario_{mese:%Y_%m}.xlsx" if mese else "costo_orario.xlsx",
        columns=["Persona", "Reparto", "Classificazione", "Mese", "RML (€)", "Giorni", "Ore al giorno",
                 "Costo orario (€)", "RML corretta a mano"],
        rows=righe, sheet_title="Costo orario", title="Costo orario",
        subtitle=f"RML ÷ giorni ÷ ore · {mese:%m/%Y}" if mese else "RML ÷ giorni ÷ ore",
    )
