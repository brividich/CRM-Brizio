"""Gestione admin della bacheca 'Documenti & Collegamenti'.

CRUD di categorie e voci (file/URL/scorciatoia interna) + visibilità per ruolo.
Tutte le view sono admin-only (@legacy_admin_required, che esclude anche dal gate ACL).
"""
from __future__ import annotations

import json
import os

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action
from core.legacy_models import Ruolo
from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess

from .decorators import legacy_admin_required

ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _json_body(request) -> dict:
    try:
        data = json.loads(request.body or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, AttributeError):
        return {}


def _unique_slug(name: str) -> str:
    base = slugify(name) or "categoria"
    slug, i = base, 2
    while HubLinkCategory.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _set_roles(link, role_ids):
    HubLinkRoleAccess.objects.filter(link=link).delete()
    for rid in {int(r) for r in (role_ids or []) if str(r).strip().lstrip("-").isdigit()}:
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=rid, can_view=True)


@legacy_admin_required
@require_GET
def bacheca(request):
    categories = (HubLinkCategory.objects
                  .prefetch_related("links__role_accesses")
                  .order_by("order", "name", "id"))
    try:
        ruoli = list(Ruolo.objects.all().order_by("nome"))
    except Exception:
        ruoli = []
    return render(request, "admin_portale/pages/bacheca.html", {
        "categories": categories,
        "ruoli": ruoli,
        "kinds": HubLink.KIND_CHOICES,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_create(request):
    data = _json_body(request)
    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "Nome obbligatorio."}, status=400)
    cat = HubLinkCategory.objects.create(
        name=name, slug=_unique_slug(name), icon=(data.get("icon") or "").strip(),
        description=(data.get("description") or "").strip(),
        order=int(data.get("order") or 100), created_by=request.user, updated_by=request.user,
    )
    log_action(request, "create", "bacheca", {"category_id": cat.id, "name": name})
    return JsonResponse({"ok": True, "id": cat.id, "slug": cat.slug})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_update(request):
    data = _json_body(request)
    try:
        cat = HubLinkCategory.objects.get(pk=int(data.get("id")))
    except (HubLinkCategory.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Categoria non trovata."}, status=404)
    for field in ("name", "icon", "description"):
        if field in data:
            setattr(cat, field, (data.get(field) or "").strip())
    if "is_visible" in data:
        cat.is_visible = bool(data.get("is_visible"))
    if "order" in data:
        cat.order = int(data.get("order") or 100)
    cat.updated_by = request.user
    cat.save()
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_category_delete(request):
    data = _json_body(request)
    HubLinkCategory.objects.filter(pk=data.get("id")).delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_create(request):
    # Supporta JSON (url/internal) e multipart (upload file).
    if (request.content_type or "").startswith("multipart/"):
        data = request.POST
        role_ids = request.POST.getlist("role_ids")
        upload = request.FILES.get("file")
    else:
        data = _json_body(request)
        role_ids = data.get("role_ids") or []
        upload = None

    try:
        cat = HubLinkCategory.objects.get(pk=int(data.get("category_id")))
    except (HubLinkCategory.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Categoria non valida."}, status=400)

    kind = (data.get("kind") or "").strip()
    title = (data.get("title") or "").strip()
    if not title:
        return JsonResponse({"ok": False, "error": "Titolo obbligatorio."}, status=400)

    link = HubLink(
        category=cat, kind=kind, title=title,
        description=(data.get("description") or "").strip(),
        icon=(data.get("icon") or "").strip(),
        open_in_new_tab=bool(data.get("open_in_new_tab")) or kind == HubLink.KIND_URL,
        order=int(data.get("order") or 100),
        created_by=request.user, updated_by=request.user,
    )
    if kind == HubLink.KIND_URL:
        link.url = (data.get("url") or "").strip()
    elif kind == HubLink.KIND_INTERNAL:
        link.route_name = (data.get("route_name") or "").strip()
    elif kind == HubLink.KIND_FILE:
        if not upload:
            return JsonResponse({"ok": False, "error": "File obbligatorio."}, status=400)
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            return JsonResponse({"ok": False, "error": f"Estensione {ext} non ammessa."}, status=400)
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse({"ok": False, "error": "File troppo grande (max 25 MB)."}, status=400)
        link.file = upload
        link.original_filename = upload.name
        link.file_size = upload.size
        link.content_type = upload.content_type or ""
    else:
        return JsonResponse({"ok": False, "error": "Tipo non valido."}, status=400)

    try:
        link.clean()
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    with transaction.atomic():
        link.save()
        _set_roles(link, role_ids)
    log_action(request, "create", "bacheca", {"link_id": link.id, "kind": kind, "title": title})
    return JsonResponse({"ok": True, "id": link.id})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_delete(request):
    data = _json_body(request)
    HubLink.objects.filter(pk=data.get("id")).delete()
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_link_toggle(request):
    data = _json_body(request)
    try:
        link = HubLink.objects.get(pk=int(data.get("id")))
    except (HubLink.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Voce non trovata."}, status=404)
    link.is_visible = bool(data.get("is_visible"))
    link.updated_by = request.user
    link.save(update_fields=["is_visible", "updated_by", "updated_at"])
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_hub_reorder(request):
    """Payload: {"links": [id,...]} oppure {"categories": [id,...]} → riscrive order."""
    data = _json_body(request)
    for model, key in ((HubLink, "links"), (HubLinkCategory, "categories")):
        ids = data.get(key)
        if isinstance(ids, list):
            for i, pk in enumerate(ids):
                model.objects.filter(pk=pk).update(order=i * 10)
    return JsonResponse({"ok": True})
