"""«Importa planimetrie»: più PDF in una volta, piante create e allineate da sole, poi la validazione.

Pagina servita dalla rotta dell'editor (``?importa=1``), quindi con lo stesso
permesso «Editor mappa officina». I PDF partono uno alla volta dal browser
(ognuno qualche secondo), così la pagina mostra l'avanzamento e nessuna
richiesta dura troppo. Gli asset si collocano solo da «Valida asset».
"""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from ..models import PlantLayout
from ..services import planimetria_import as importa

_MAX_PDF = 60 * 1024 * 1024


def _basi():
    return list(PlantLayout.objects.filter(base__isnull=True, is_active=True).exclude(image="").order_by("category", "name"))


def _base_predefinita(basi):
    for parola in ("generale", "azienda", "muri"):
        for b in basi:
            if parola in f"{b.category} {b.name}".casefold():
                return b
    return basi[0] if basi else None


def _utente(request) -> str:
    u = getattr(request, "user", None)
    return (u.get_full_name() or u.get_username()) if u is not None and u.is_authenticated else ""


def importa_planimetrie(request: HttpRequest) -> HttpResponse:
    action = (request.POST.get("action") or "").strip() if request.method == "POST" else ""
    if action == "importa_uno":
        return _importa_uno(request)
    if action == "scarta":
        return _scarta(request)
    basi = _basi()
    try:
        base_id = int(request.GET.get("base") or 0)
    except ValueError:
        base_id = 0
    base = next((b for b in basi if b.id == base_id), None) or _base_predefinita(basi)
    importate = [
        importa.riga(x) for x in PlantLayout.objects.exclude(importazione={}).order_by("category", "name", "id")
        if (x.importazione or {}).get("file")
    ]
    return render(request, "assets/pages/planimetria_importa.html", {
        "basi": basi, "base": base, "importate": importate,
        "da_validare": sum(1 for r in importate if not r["validata"]),
    })


def _importa_uno(request: HttpRequest) -> JsonResponse:
    file_pdf = request.FILES.get("pdf")
    if not file_pdf:
        return JsonResponse({"ok": False, "errore": "Nessun file ricevuto."}, status=400)
    nome = file_pdf.name or "planimetria.pdf"
    if not nome.lower().endswith(".pdf"):
        return JsonResponse({"ok": False, "file": nome, "errore": "Non è un PDF."}, status=400)
    if file_pdf.size > _MAX_PDF:
        return JsonResponse({"ok": False, "file": nome, "errore": "Il PDF è troppo grande (massimo 60 MB)."}, status=400)
    try:
        base = PlantLayout.objects.get(pk=int(request.POST.get("base_id") or 0), base__isnull=True)
    except (ValueError, PlantLayout.DoesNotExist):
        return JsonResponse({"ok": False, "file": nome, "errore": "Scegli la pianta base."}, status=400)
    try:
        esito = importa.importa_pdf(file_pdf.read(), nome, base, _utente(request))
    except importa.ErroreImportazione as exc:
        return JsonResponse({"ok": False, "file": nome, "errore": str(exc)}, status=400)
    return JsonResponse({"ok": True, **esito})


def _scarta(request: HttpRequest) -> HttpResponse:
    """Una pianta importata che non serve: si cancella (solo se non ancora validata)."""
    url = f"{reverse('assets:plant_layout_editor')}?importa=1"
    try:
        layout = PlantLayout.objects.get(pk=int(request.POST.get("layout_id") or 0))
    except (ValueError, PlantLayout.DoesNotExist):
        return redirect(url)
    imp = layout.importazione or {}
    if not imp.get("file") or imp.get("validata"):
        messages.error(request, "Si scartano solo le piante importate e non ancora validate.")
        return redirect(url)
    nome = layout.name
    layout.delete()
    messages.success(request, f"Pianta «{nome}» scartata.")
    return redirect(url)
