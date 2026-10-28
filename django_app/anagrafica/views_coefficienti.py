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
    # Gli ultimi 12 mesi di ciascuno, fino al mese scelto: sottoriga e mini-grafico.
    finestra = [m for m in mesi if m <= mese][:MESI_SERIE] if mese else []
    serie: dict = {}
    if finestra:
        for c in CostoOrarioMensile.objects.filter(mese__in=finestra, tax_code__in=[r.tax_code for r in righe]):
            serie.setdefault(c.tax_code, []).append(c)
    out = []
    for r in righe:
        d = anag.get(r.legacy_anagrafica_id or -1) or {}
        storia = sorted(serie.get(r.tax_code, [r]), key=lambda c: c.mese)
        prima = [c for c in storia if c.mese < r.mese]
        prec = prima[-1] if prima else None
        delta = r.costo_orario - prec.costo_orario if prec else None
        out.append({
            "c": r, "legacy_id": r.legacy_anagrafica_id,
            "nome": naming.nome_completo(d.get("nome"), d.get("cognome")) if d else r.tax_code,
            "ordine": naming.chiave_ordinamento(d.get("nome"), d.get("cognome")) if d else r.tax_code,
            "reparto": (d.get("reparto") or "").strip(),
            "classe": stati.get(r.legacy_anagrafica_id, {}).get("classe_principale_label", ""),
            "prec": prec, "delta": delta, "delta_pct": _pct(delta, prec.costo_orario) if prec else None,
            "serie": _serie(storia),
        })
    # Media di reparto sul mese intero (non sui filtrati): «rispetto al reparto».
    per_reparto: dict = {}
    for x in out:
        per_reparto.setdefault(x["reparto"], []).append(x["c"].costo_orario)
    q = (request.GET.get("q") or "").strip().casefold()
    reparto = (request.GET.get("reparto") or "").strip()
    reparti = sorted({x["reparto"] for x in out if x["reparto"]}, key=str.casefold)
    if q:
        out = [x for x in out if q in x["nome"].casefold() or q in x["c"].tax_code.casefold()]
    if reparto:
        out = [x for x in out if x["reparto"] == reparto]
    # Scostamento dalla media di chi resta con i filtri: cambia con i filtri.
    media = sum(x["c"].costo_orario for x in out) / len(out) if out else None
    for x in out:
        valori = per_reparto.get(x["reparto"]) or []
        media_rep = sum(valori) / len(valori) if valori else None
        x["scost"] = _pct(x["c"].costo_orario - media, media) if media else None
        x["scost_rep"] = _pct(x["c"].costo_orario - media_rep, media_rep) if media_rep and len(valori) > 1 else None
        x["barra"] = min(50, abs(float(x["scost"] or 0)) * 2)
    mostra = request.GET.get("mostra") or ""
    if mostra in FILTRI_MOSTRA:
        out = [x for x in out if FILTRI_MOSTRA[mostra][1](x)]
    out.sort(key=lambda x: x["ordine"])
    return {"mesi": mesi, "mese": mese, "righe": out, "reparti": reparti, "q": request.GET.get("q", ""),
            "reparto": reparto, "media": media, "mostra": mostra if mostra in FILTRI_MOSTRA else "",
            "filtri_mostra": [(k, v[0]) for k, v in FILTRI_MOSTRA.items()]}


MESI_SERIE = 12
SOGLIA_SCOSTAMENTO = 10

FILTRI_MOSTRA = {
    "sopra": ("Sopra la media", lambda x: x["scost"] is not None and x["scost"] > 0),
    "sotto": ("Sotto la media", lambda x: x["scost"] is not None and x["scost"] < 0),
    "lontani": (f"Lontani dalla media (oltre ±{SOGLIA_SCOSTAMENTO}%)",
                lambda x: x["scost"] is not None and abs(x["scost"]) > SOGLIA_SCOSTAMENTO),
    "aumentati": ("Aumentati sul mese prima", lambda x: x["delta"] is not None and x["delta"] > 0),
    "diminuiti": ("Diminuiti sul mese prima", lambda x: x["delta"] is not None and x["delta"] < 0),
}


def _pct(parte, base):
    from decimal import ROUND_HALF_UP, Decimal

    return (Decimal(parte) / Decimal(base) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if base else None


def _serie(storia: list) -> dict:
    """Mesi della persona per la sottoriga, con i punti del mini-grafico (SVG 96×26) e le barre."""
    valori = [float(c.costo_orario) for c in storia]
    lo, hi = (min(valori), max(valori)) if valori else (0, 0)
    ampiezza = (hi - lo) or 1
    n = len(valori)
    punti = " ".join(f"{(i * 92 / (n - 1) + 2) if n > 1 else 48:.1f},{22 - (v - lo) / ampiezza * 18:.1f}"
                     for i, v in enumerate(valori))
    mesi, prec = [], None
    for c in storia:
        delta = c.costo_orario - prec.costo_orario if prec else None
        mesi.append({"c": c, "delta": delta, "pct": _pct(delta, prec.costo_orario) if prec else None,
                     "h": round(12 + (float(c.costo_orario) - lo) / ampiezza * 48)})
        prec = c
    ux, uy = punti.rsplit(" ", 1)[-1].split(",") if punti else ("48", "13")
    return {"punti": punti, "mesi": mesi, "n": n, "ux": ux, "uy": uy}


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
    costi = [x["c"].costo_orario for x in ctx["righe"]]
    kpi = {
        "media": _euro(sum(costi) / len(costi)) if costi else "—",
        "minimo": _euro(min(costi)) if costi else "—",
        "massimo": _euro(max(costi)) if costi else "—",
        "manuali": sum(1 for x in ctx["righe"] if x["c"].rml_manuale),
        "aumentati": sum(1 for x in ctx["righe"] if x["delta"] is not None and x["delta"] > 0),
        "diminuiti": sum(1 for x in ctx["righe"] if x["delta"] is not None and x["delta"] < 0),
        "lontani": sum(1 for x in ctx["righe"] if x["scost"] is not None and abs(x["scost"]) > SOGLIA_SCOSTAMENTO),
    }
    return render(request, "anagrafica/pages/costo_orario.html", {
        **ctx, "page_title": "Costo orario", "report_costi": _report_costi(request), "giorni": giorni, "ore": ore, "ore_mese": giorni * ore, "kpi": kpi,
        "soglia": SOGLIA_SCOSTAMENTO, "media_euro": _euro(ctx["media"]) if ctx["media"] is not None else "—",
    })


def _report_costi(request) -> int | None:
    """Il modello pronto «Costo orario del personale» della Reportistica, se c'è e se si può aprire."""
    from .models_reportistica import ReportModello
    from .reportistica.permessi import can_view

    if not can_view(request):
        return None
    return ReportModello.objects.filter(codice_sistema="costo_personale").values_list("pk", flat=True).first()


def _euro(valore) -> str:
    return f"{valore:.2f}".replace(".", ",")


# ── Storico del costo orario (27/10/2026) ───────────────────────────────────────

MESI_DEFAULT = 12


def _mese_da(valore, mesi):
    try:
        d = date.fromisoformat(valore) if valore else None
    except ValueError:
        return None
    return d.replace(day=1) if d else None


def _storico(request) -> dict:
    """Una riga per dipendente, una colonna per mese (dal più vecchio al più recente).

    Filtri: «dal»/«al» (mesi, di serie gli ultimi 12 con dati), reparto, ricerca,
    persona (dalla scheda). Ogni cella ha il costo, il confronto con il mese prima
    e l'RML; in fondo la media di ogni mese; a destra la variazione nel periodo.
    """
    from decimal import ROUND_HALF_UP, Decimal

    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    tutti = list(CostoOrarioMensile.objects.order_by("mese").values_list("mese", flat=True).distinct())
    g = request.GET
    al = _mese_da(g.get("al"), tutti) or (tutti[-1] if tutti else None)
    dal = _mese_da(g.get("dal"), tutti)
    if dal is None and al is not None:
        prima = [m for m in tutti if m <= al]
        dal = prima[-MESI_DEFAULT:][0] if prima else al
    if dal and al and dal > al:
        dal, al = al, dal
    mesi = [m for m in tutti if dal and al and dal <= m <= al]
    qs = CostoOrarioMensile.objects.filter(mese__in=mesi)
    persona = g.get("persona") or ""
    if persona.isdigit():
        qs = qs.filter(legacy_anagrafica_id=int(persona))
    per_chiave: dict = {}
    for c in qs:
        chiave = c.legacy_anagrafica_id or c.tax_code
        per_chiave.setdefault(chiave, {})[c.mese] = c
    ids = [k for k in per_chiave if isinstance(k, int)]
    anag = {int(d["id"]): d for d in fetch_anagrafica_rows(ids=ids)} if ids else {}
    righe = []
    for chiave, valori in per_chiave.items():
        d = anag.get(chiave) if isinstance(chiave, int) else None
        celle, prec = [], None
        for m in mesi:
            c = valori.get(m)
            delta = (c.costo_orario - prec.costo_orario) if c and prec else None
            celle.append({"c": c, "delta": delta, "su": bool(delta and delta > 0), "giu": bool(delta and delta < 0)})
            if c:
                prec = c
        presenti = [x["c"] for x in celle if x["c"]]
        primo, ultimo = (presenti[0], presenti[-1]) if presenti else (None, None)
        var = (ultimo.costo_orario - primo.costo_orario) if primo and ultimo and primo is not ultimo else None
        var_pct = ((var / primo.costo_orario * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                   if var is not None and primo.costo_orario else None)
        righe.append({
            "legacy_id": chiave if isinstance(chiave, int) else None,
            "nome": naming.nome_completo(d.get("nome"), d.get("cognome")) if d else str(next(iter(valori.values())).tax_code),
            "ordine": naming.chiave_ordinamento(d.get("nome"), d.get("cognome")) if d else str(chiave),
            "reparto": ((d or {}).get("reparto") or "").strip(),
            "celle": celle, "ultimo": ultimo, "var": var, "var_pct": var_pct,
        })
    reparti = sorted({r["reparto"] for r in righe if r["reparto"]}, key=str.casefold)
    q = (g.get("q") or "").strip().casefold()
    reparto = (g.get("reparto") or "").strip()
    if q:
        righe = [r for r in righe if q in r["nome"].casefold()
                 or any(x["c"] and q in x["c"].tax_code.casefold() for x in r["celle"])]
    if reparto:
        righe = [r for r in righe if r["reparto"] == reparto]
    righe.sort(key=lambda r: r["ordine"])
    medie = []
    for i, _m in enumerate(mesi):
        valori = [r["celle"][i]["c"].costo_orario for r in righe if r["celle"][i]["c"]]
        medie.append(sum(valori) / len(valori) if valori else None)
    media_prima = next((x for x in medie if x is not None), None)
    media_ultima = next((x for x in reversed(medie) if x is not None), None)
    persona_nome = righe[0]["nome"] if persona.isdigit() and righe else ""
    return {
        "tutti_mesi": list(reversed(tutti)), "mesi": mesi, "dal": dal, "al": al, "righe": righe, "medie": medie,
        "reparti": reparti, "reparto": reparto, "q": g.get("q", ""), "persona": persona if persona.isdigit() else "",
        "persona_nome": persona_nome,
        "kpi": {
            "mesi": len(mesi),
            "media_ultima": _euro(media_ultima) if media_ultima is not None else "—",
            "variazione": (f"{(media_ultima - media_prima) / media_prima * 100:+.1f}%".replace(".", ",")
                           if media_prima and media_ultima is not None and len(mesi) > 1 else "—"),
            "aumenti": sum(1 for r in righe if r["var"] is not None and r["var"] > 0),
            "cali": sum(1 for r in righe if r["var"] is not None and r["var"] < 0),
        },
    }


@login_required
def costo_orario_storico(request):
    if not _puo_costo(request):
        messages.error(request, "Accesso non autorizzato ai dati HR.")
        return redirect("anagrafica:index")
    log_consultazione(request, "COSTO_ORARIO_STORICO_VISUALIZZATO", MODULE,
                      {"filtri": sorted(k for k in request.GET.keys())}, chiave="costo_orario_storico")
    ctx = _storico(request)
    giorni, ore = costo_svc.divisori()
    return render(request, "anagrafica/pages/costo_orario_storico.html", {
        **ctx, "page_title": "Storico del costo orario", "report_costi": _report_costi(request), "giorni": giorni, "ore": ore, "ore_mese": giorni * ore,
    })
