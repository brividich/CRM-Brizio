"""«Livello, allineamento e scala» di una planimetria.

Pagina servita dalla rotta dell'editor (``?livello=<id>``), con lo stesso
permesso. Qui una planimetria diventa un **livello** di una pianta base
(servizio: condizionatori, differenziali...), si allinea con due punti, si
scelgono le categorie di asset che ci stanno (servono alla lettura della pianta
e alla copertura) e si tara la **scala reale** su una quota nota.
"""
from __future__ import annotations

import re

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from ..models import AssetCategory, PlantLayout
from ..services import planimetria_livelli as livelli

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _url(layout: PlantLayout) -> str:
    return f"{reverse('assets:plant_layout_editor')}?livello={layout.id}"


def _num(valore) -> float | None:
    try:
        v = float(str(valore).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v


def _pct(valore) -> float | None:
    v = _num(valore)
    return v if v is not None and 0 <= v <= 100 else None


def livello_planimetria(request: HttpRequest) -> HttpResponse:
    try:
        layout = PlantLayout.objects.get(pk=int(request.GET.get("livello") or request.POST.get("layout_id") or 0))
    except (PlantLayout.DoesNotExist, ValueError, TypeError):
        messages.error(request, "Planimetria non trovata.")
        return redirect("assets:plant_layout_editor")

    if request.method == "POST":
        azione = (request.POST.get("action") or "").strip()
        if azione == "salva_impostazioni":
            _salva_impostazioni(request, layout)
        elif azione == "salva_allineamento":
            _salva_allineamento(request, layout)
        elif azione == "togli_livello":
            layout.base = None
            layout.allineamento = {}
            layout.save(update_fields=["base", "allineamento", "updated_at"])
            messages.success(request, f"«{layout.name}» non è più un livello: torna una planimetria a sé.")
        elif azione == "salva_scala":
            _salva_scala(request, layout)
        elif azione == "togli_scala":
            layout.scala = {}
            layout.save(update_fields=["scala", "updated_at"])
            messages.success(request, "Scala tolta.")
        return redirect(_url(layout))

    basi = list(
        PlantLayout.objects.filter(base__isnull=True).exclude(pk=layout.pk).order_by("category", "-is_active", "name")
    )
    scelte = set(layout.asset_categories.values_list("id", flat=True))
    categorie = list(AssetCategory.objects.filter(is_active=True).select_related("parent").order_by("label"))
    categorie.sort(key=lambda c: ((c.parent.label if c.parent_id else c.label).casefold(), bool(c.parent_id), c.label.casefold()))
    dim = livelli.dimensioni_immagine(layout)
    dim_base = livelli.dimensioni_immagine(layout.base) if layout.base_id else (0, 0)
    descrizione = livelli.descrivi_matrice(layout.matrice, dim, dim_base) if layout.matrice else {}
    contesto = {
        "layout": layout,
        "basi": basi,
        "categorie": [{"id": c.id, "label": c.label, "figlia": bool(c.parent_id), "scelta": c.id in scelte} for c in categorie],
        "livelli_qui": list(layout.livelli.order_by("category", "name")) if not layout.base_id else [],
        "dim": dim,
        "dim_base": dim_base,
        "descrizione": descrizione,
        "punti": (layout.allineamento or {}).get("punti") or [],
        "scala_punti": (layout.scala or {}).get("punti") or [],
        "copertura": livelli.copertura(layout),
        "colori": livelli.COLORI_LIVELLI,
        "plv_dati": {
            "punti": (layout.allineamento or {}).get("punti") or [],
            "scala": (layout.scala or {}).get("punti") or [],
            "dim": list(dim),
            "dimBase": list(dim_base),
        },
    }
    return render(request, "assets/pages/planimetria_livello.html", contesto)


def _salva_impostazioni(request: HttpRequest, layout: PlantLayout) -> None:
    base_id = request.POST.get("base") or ""
    nuova_base = None
    if base_id:
        nuova_base = PlantLayout.objects.filter(pk=base_id, base__isnull=True).exclude(pk=layout.pk).first()
        if nuova_base is None:
            messages.error(request, "Pianta base non valida: dev'essere una planimetria che non è a sua volta un livello.")
            return
        if layout.livelli.exists():
            messages.error(request, "Questa planimetria ha già dei livelli sopra: non può diventare un livello.")
            return
    if (nuova_base.pk if nuova_base else None) != layout.base_id:
        layout.base = nuova_base
        layout.allineamento = {}  # base cambiata: i punti vanno ripresi
    colore = (request.POST.get("colore") or "").strip()
    layout.colore = colore.upper() if _HEX.match(colore) else ""
    layout.save(update_fields=["base", "allineamento", "colore", "updated_at"])
    ids = [int(x) for x in request.POST.getlist("categorie") if str(x).isdigit()]
    layout.asset_categories.set(AssetCategory.objects.filter(id__in=ids))
    if layout.base_id and not layout.matrice:
        messages.success(request, "Salvato. Ora indica i due punti per allineare il livello alla pianta base.")
    else:
        messages.success(request, "Impostazioni della planimetria salvate.")


def _salva_allineamento(request: HttpRequest, layout: PlantLayout) -> None:
    if not layout.base_id:
        messages.error(request, "Scegli prima la pianta base.")
        return
    punti = []
    for i in (1, 2):
        p = [_pct(request.POST.get(f"p{i}{k}")) for k in ("x", "y", "bx", "by")]
        if any(v is None for v in p):
            messages.error(request, "Indica tutti e quattro i punti: 1 e 2 sul livello, 1 e 2 sulla pianta base.")
            return
        punti.append(p)
    try:
        livelli.salva_allineamento(layout, layout.base, punti)
    except livelli.ErroreAllineamento as exc:
        messages.error(request, str(exc))
        return
    messages.success(request, f"Livello allineato a «{layout.base.name}»: i suoi asset compaiono sulla pianta base.")


def _salva_scala(request: HttpRequest, layout: PlantLayout) -> None:
    p = [_pct(request.POST.get(k)) for k in ("s1x", "s1y", "s2x", "s2y")]
    metri = _num(request.POST.get("metri"))
    if any(v is None for v in p) or not metri or metri <= 0:
        messages.error(request, "Indica i due estremi della quota sulla pianta e la sua lunghezza in metri.")
        return
    w, h = livelli.dimensioni_immagine(layout)
    if not (w and h):
        messages.error(request, "L'immagine della planimetria non si può leggere.")
        return
    if abs(p[0] - p[2]) + abs(p[1] - p[3]) < 1:
        messages.error(request, "I due estremi sono troppo vicini: usa una quota lunga (es. un lato del capannone).")
        return
    layout.scala = {"punti": [[p[0], p[1]], [p[2], p[3]]], "metri": round(metri, 3), "rapporto": round(h / w, 6)}
    layout.save(update_fields=["scala", "updated_at"])
    messages.success(request, f"Scala salvata: {metri:g} m tra i due punti. Sulla mappa ora puoi misurare distanze e superfici.")
