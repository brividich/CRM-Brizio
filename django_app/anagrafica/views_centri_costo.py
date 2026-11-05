"""«Centri di costo» (05/11/2026): quali reparti stanno in quale centro di costo.

Il «reparto» dell'elenco dell'azienda è un'area del portale: un centro di costo
raggruppa più aree, un'area sta in un solo centro (FK sull'area). Vedono tutti
quelli con accesso a ``/anagrafica/aree/``; cambiano solo gli amministratori
dell'anagrafica.
"""
from __future__ import annotations

from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import AreaAziendale, CentroDiCosto, RuoloOperativo
from .services import capo_team
from .views import _helpers

MODULE = "anagrafica"


def _torna(ancora: str = ""):
    url = reverse("anagrafica:centri_costo")
    return redirect(f"{url}#{ancora}" if ancora else url)


def _solo_admin(request):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "I centri di costo li cambia l'amministrazione dell'anagrafica.")
        return _torna()
    return None


def persone_per_area() -> Counter:
    """Persone in forza per area: stesso conteggio di «Reparti, aree e capi»."""
    from .services.reparto_canonico import build_area_canonica_map

    return Counter(a.pk for a in build_area_canonica_map(list(capo_team.mappa_capi())).values())


def _riga(area, persone) -> dict:
    return {
        "area": area,
        "persone": persone.get(area.pk, 0),
        "ruoli": sorted(area.ruoli_reparto.all(), key=lambda r: r.nome.lower()),
    }


@login_required
def centri_costo(request):
    persone = persone_per_area()
    aree = (
        AreaAziendale.objects.select_related("reparto", "centro_di_costo")
        .prefetch_related("ruoli_reparto").order_by("nome")
    )
    per_centro: dict[int | None, list] = {}
    for area in aree:
        if area.is_active or area.centro_di_costo_id:
            per_centro.setdefault(area.centro_di_costo_id, []).append(_riga(area, persone))
    schede = []
    for centro in CentroDiCosto.objects.order_by("nome"):
        righe = per_centro.get(centro.pk, [])
        schede.append({"centro": centro, "righe": righe, "persone": sum(r["persone"] for r in righe)})
    senza = per_centro.get(None, [])
    return render(request, "anagrafica/pages/centri_costo.html", {
        "schede": schede,
        "senza_centro": senza,
        "kpi": {
            "centri": sum(1 for s in schede if s["centro"].is_active),
            "reparti": sum(len(s["righe"]) for s in schede),
            "persone": sum(s["persone"] for s in schede),
            "senza_centro": len(senza),
            "persone_senza_centro": sum(r["persone"] for r in senza),
        },
        "centri_opts": [s["centro"] for s in schede if s["centro"].is_active],
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).order_by("nome")),
        "is_admin": _helpers._is_anagrafica_admin(request),
        "puo_costi": _helpers._check_hr_permission(request),
    })


def _nome_da_post(request) -> str:
    return " ".join((request.POST.get("nome") or "").split())[:100]


@login_required
@require_POST
def centro_costo_crea(request):
    if (negato := _solo_admin(request)) is not None:
        return negato
    nome = _nome_da_post(request)
    if not nome:
        messages.error(request, "Il nome del centro di costo è obbligatorio.")
        return _torna()
    if CentroDiCosto.objects.filter(nome__iexact=nome).exists():
        messages.warning(request, f"Esiste già un centro di costo «{nome}».")
        return _torna()
    centro = CentroDiCosto.objects.create(nome=nome, descrizione=(request.POST.get("descrizione") or "").strip())
    log_action(request, "centro_costo_crea", MODULE, {"centro": centro.pk, "nome": nome}, oggetto=centro)
    messages.success(request, f"Centro di costo «{nome}» creato.")
    return _torna(f"cc-{centro.pk}")


@login_required
@require_POST
def centro_costo_modifica(request, centro_id: int):
    if (negato := _solo_admin(request)) is not None:
        return negato
    centro = get_object_or_404(CentroDiCosto, pk=centro_id)
    nome = _nome_da_post(request)
    if not nome:
        messages.error(request, "Il nome del centro di costo è obbligatorio.")
        return _torna(f"cc-{centro.pk}")
    if CentroDiCosto.objects.filter(nome__iexact=nome).exclude(pk=centro.pk).exists():
        messages.error(request, f"Esiste già un centro di costo «{nome}».")
        return _torna(f"cc-{centro.pk}")
    centro.nome = nome
    centro.descrizione = (request.POST.get("descrizione") or "").strip()
    centro.is_active = request.POST.get("is_active") == "1"
    centro.save()
    log_action(request, "centro_costo_modifica", MODULE,
               {"centro": centro.pk, "nome": nome, "attivo": centro.is_active}, oggetto=centro)
    messages.success(request, f"Centro di costo «{nome}» aggiornato.")
    return _torna(f"cc-{centro.pk}")


@login_required
@require_POST
def centro_costo_elimina(request, centro_id: int):
    if (negato := _solo_admin(request)) is not None:
        return negato
    centro = get_object_or_404(CentroDiCosto, pk=centro_id)
    collegate = centro.aree.count()
    if collegate:
        messages.error(request, f"«{centro.nome}» ha ancora {collegate} repart{'o' if collegate == 1 else 'i'}: "
                                "spostali prima di eliminarlo, o rendilo non attivo.")
        return _torna(f"cc-{centro.pk}")
    log_action(request, "centro_costo_elimina", MODULE, {"centro": centro.pk, "nome": centro.nome}, oggetto=centro)
    nome = centro.nome
    centro.delete()
    messages.success(request, f"Centro di costo «{nome}» eliminato.")
    return _torna()


@login_required
@require_POST
def centro_costo_reparto_salva(request, area_id: int):
    """Centro di costo e ruoli di un reparto (area). Il centro è uno solo: sceglierne un altro sposta il reparto."""
    if (negato := _solo_admin(request)) is not None:
        return negato
    area = get_object_or_404(AreaAziendale, pk=area_id)
    centro_id = request.POST.get("centro_di_costo") or ""
    area.centro_di_costo = CentroDiCosto.objects.filter(pk=int(centro_id)).first() if centro_id.isdigit() else None
    area.save(update_fields=["centro_di_costo"])
    ids = [int(v) for v in request.POST.getlist("ruoli") if str(v).isdigit()]
    ruoli = RuoloOperativo.objects.filter(pk__in=ids)
    area.ruoli_reparto.set(ruoli)
    log_action(request, "centro_costo_reparto", MODULE,
               {"area": area.pk, "centro": area.centro_di_costo_id, "ruoli": ids}, oggetto=area)
    dove = f"nel centro di costo «{area.centro_di_costo.nome}»" if area.centro_di_costo_id else "senza centro di costo"
    messages.success(request, f"{area.nome}: ora {dove}.")
    return _torna(f"cc-{area.centro_di_costo_id}" if area.centro_di_costo_id else "senza-centro")
