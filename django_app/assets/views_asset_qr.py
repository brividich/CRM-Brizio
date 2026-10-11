"""QR degli asset: immagine, pannello di anteprima, link pubblico, etichette multiple.

Le route stanno sotto ``/assets/view/`` e ereditano il binding ACL v2 del dettaglio
asset (migrazione 0124): chi vede la scheda vede il suo QR. Abilitare, revocare o
rigenerare il link pubblico richiede in piu' ``admin_assets`` o l'azione
``assets/asset_qr_public`` concessa dal pannello Accessi.
"""
from __future__ import annotations

import io
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.acl import user_can_modulo_action
from core.audit import log_action

from .models import Asset
from .services import asset_qr

#: Etichette per singola stampa multipla: oltre questo numero si spezza la selezione.
MAX_ETICHETTE = 200


def can_manage_public_qr(request: HttpRequest) -> bool:
    from .views import _is_assets_admin

    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_qr_public")
    )


def _wants_json(request: HttpRequest) -> bool:
    return (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest" or "application/json" in (
        request.headers.get("Accept") or ""
    ).lower()


def qr_context(request: HttpRequest, asset: Asset) -> dict:
    """Contesto del componente QR (pannello e miniatura): nessuna query oltre all'asset."""
    dest = asset_qr.destinazione(request, asset)
    image_url = reverse("assets:asset_qr_image", kwargs={"id": asset.id})
    return {
        "qr_asset": asset,
        "qr_dest": dest,
        "qr_public_active": dest.kind == asset_qr.DEST_PUBLIC,
        "qr_image_url": image_url,
        "qr_download_url": f"{image_url}?size=l&download=1",
        "qr_label_url": reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
        "qr_panel_url": reverse("assets:asset_qr_panel", kwargs={"id": asset.id}),
        "qr_public_action_url": reverse("assets:asset_qr_public_link", kwargs={"id": asset.id}),
        "qr_can_manage_public": can_manage_public_qr(request),
        "qr_has_token": bool((asset.public_qr_token or "").strip()),
    }


@login_required
@require_GET
def asset_qr_image(request: HttpRequest, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.only("id", "asset_tag", "public_qr_token", "public_qr_enabled"), pk=id)
    size = (request.GET.get("size") or "m").strip().lower()
    dest = asset_qr.destinazione(request, asset)
    response = HttpResponse(asset_qr.png_asset(asset.id, dest, size), content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=300"
    if request.GET.get("download"):
        nome = re.sub(r"[^A-Za-z0-9._-]", "_", asset.asset_tag or str(asset.id))[:60]
        response["Content-Disposition"] = f'attachment; filename="{nome}-qr.png"'
    return response


@login_required
@require_GET
def asset_qr_panel(request: HttpRequest, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset, pk=id)
    return render(request, "assets/partials/qr_panel.html", qr_context(request, asset))


@login_required
@require_POST
def asset_qr_public_link(request: HttpRequest, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset, pk=id)
    if not can_manage_public_qr(request):
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
        return HttpResponse("Permesso negato.", status=403)
    azione = (request.POST.get("azione") or "").strip().lower()
    if azione == "abilita":
        changed = asset_qr.abilita_link_pubblico(asset)
    elif azione == "revoca":
        changed = asset_qr.revoca_link_pubblico(asset)
    elif azione == "rigenera":
        asset_qr.rigenera_link_pubblico(asset)
        changed = True
    else:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "Azione non valida."}, status=400)
        return HttpResponse("Azione non valida.", status=400)
    if changed:
        # Mai il token nel log: basta sapere chi ha aperto/chiuso il link e quando.
        log_action(request, f"asset_qr_pubblico_{azione}", "assets", {"asset_tag": asset.asset_tag}, oggetto=asset)
    if _wants_json(request):
        return JsonResponse({"ok": True, "public": asset_qr.link_pubblico_attivo(asset)})
    target = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse("assets:asset_view", kwargs={"id": asset.id})
    return redirect(target)


def _parse_ids(raw: str) -> list[int]:
    """Id unici nell'ordine dato; si ferma oltre il limite (il chiamante risponde 400)."""
    ids: list[int] = []
    visti: set[int] = set()
    for chunk in (raw or "")[:5000].replace(";", ",").split(","):
        chunk = chunk.strip()
        if re.fullmatch(r"[0-9]{1,10}", chunk) and int(chunk) not in visti:
            visti.add(int(chunk))
            ids.append(int(chunk))
            if len(ids) > MAX_ETICHETTE:
                break
    return ids


@login_required
@require_GET
def asset_qr_labels_bulk(request: HttpRequest) -> HttpResponse:
    """Un PDF con un'etichetta per pagina, nell'ordine di selezione."""
    from .views import _draw_asset_label_pdf, _resolve_asset_label_template

    ids = _parse_ids(request.GET.get("ids", ""))
    if not ids:
        return HttpResponse("Nessun asset selezionato.", status=400)
    if len(ids) > MAX_ETICHETTE:
        return HttpResponse(f"Massimo {MAX_ETICHETTE} etichette per stampa.", status=400)
    assets_by_id = Asset.objects.in_bulk(ids)
    ordered = [assets_by_id[pk] for pk in ids if pk in assets_by_id]
    if not ordered:
        return HttpResponse("Nessun asset trovato.", status=404)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setTitle("Etichette QR asset")
    pdf.setAuthor("NOVICROM HUB")
    for asset in ordered:
        template = _resolve_asset_label_template(asset)
        pdf.setPageSize((float(template.page_width_mm or 100) * mm, float(template.page_height_mm or 62) * mm))
        dest = asset_qr.destinazione(request, asset)
        _draw_asset_label_pdf(pdf, asset=asset, template=template, target_url=dest.url, target_label=dest.label)
        pdf.showPage()
    pdf.save()
    log_action(request, "asset_qr_etichette_multiple", "assets", {"asset": len(ordered)})
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="etichette-qr-asset.pdf"'
    return response
