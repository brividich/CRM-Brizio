from __future__ import annotations

import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponseGone, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.models import LegacyRedirect


_ADMIN_GET_REDIRECTS: dict[str, str] = {
    "gestione_utenti": "admin_portale:utenti_list",
    "gestione_ruoli": "admin_portale:permessi",
    "permessi": "admin_portale:permessi",
    "gestione_pulsanti": "admin_portale:pulsanti",
    "gestione_completa": "admin_portale:index",
    "log-audit": "admin_portale:schema_dati",
    "anagrafica": "admin_portale:utenti_list",
    "anagrafica/sync_ad": "admin_portale:ldap_diagnostica",
    "ricarica_capi": "admin_portale:utenti_list",
    "export_utenti": "admin_portale:utenti_list",
    "sync_info_personali": "admin_portale:utenti_list",
    "sync_mansioni": "admin_portale:utenti_list",
    "force_migrations": "admin_portale:schema_dati",
    "test": "admin_portale:index",
    "sync/pending-anomalie": "gestione_anomalie_page",
}


def _wants_json(request: HttpRequest) -> bool:
    content_type = (request.headers.get("Content-Type") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in content_type or "application/json" in accept


def _legacy_removed_response(request: HttpRequest, endpoint: str):
    payload = {
        "ok": False,
        "legacy_endpoint": endpoint,
        "message": "Endpoint Flask dismesso: usare le nuove route Django in /admin-portale/.",
    }
    if _wants_json(request):
        return JsonResponse(payload, status=410)
    return HttpResponseGone(payload["message"])


def _redirect_with_notice(request: HttpRequest, route_name: str, kwargs: dict | None = None):
    messages.info(
        request,
        "URL legacy Flask reindirizzato alla nuova pagina Django.",
    )
    return redirect(reverse(route_name, kwargs=kwargs or {}))


def _route_for_legacy_sync(path_value: str) -> str:
    lista = (path_value.split("/", 1)[1] if "/" in path_value else "").strip().lower()
    if lista in {"anomalie", "ordini"}:
        return "gestione_anomalie_page"
    if lista in {"assenze"}:
        return "assenze_menu"
    if lista in {"dipendenti", "capi_reparto", "all"}:
        return "admin_portale:utenti_list"
    return "admin_portale:index"


def _normalize_legacy_redirect_path(path_value: str) -> str:
    raw = (path_value or "").strip()
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw != "/":
        raw = raw.rstrip("/")
    return raw.lower()


def _resolve_db_legacy_redirect(request: HttpRequest, full_path: str):
    try:
        row = (
            LegacyRedirect.objects.filter(
                legacy_path__iexact=_normalize_legacy_redirect_path(full_path),
                is_enabled=True,
            )
            .order_by("id")
            .first()
        )
    except Exception:
        return None
    if not row:
        return None
    target_route = (row.target_route_name or "").strip()
    target_path = (row.target_url_path or "").strip()
    if target_route:
        return _redirect_with_notice(request, target_route)
    if target_path:
        messages.info(request, "URL legacy reindirizzato tramite mappa redirect configurata.")
        return redirect(target_path)
    return None


def legacy_flask_check(request: HttpRequest):
    db_engine = ""
    try:
        db_engine = str(settings.DATABASES.get("default", {}).get("ENGINE", ""))
    except Exception:
        db_engine = ""
    return JsonResponse(
        {
            "app": "Portale Applicativo (Django)",
            "framework": "django",
            "version": str(getattr(settings, "APP_VERSION", "")),
            "debug": bool(getattr(settings, "DEBUG", False)),
            "db_engine": db_engine,
            "legacy_flask": "removed",
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def legacy_admin_entry(request: HttpRequest):
    if request.method != "GET":
        return _legacy_removed_response(request, "/admin")
    return _redirect_with_notice(request, "admin_portale:index")


@login_required
@require_http_methods(["GET", "POST"])
def legacy_admin_dispatch(request: HttpRequest, legacy_path: str):
    path_value = (legacy_path or "").strip().strip("/")
    endpoint = f"/admin/{path_value}" if path_value else "/admin/"

    if request.method != "GET":
        return _legacy_removed_response(request, endpoint)

    db_redirect = _resolve_db_legacy_redirect(request, endpoint)
    if db_redirect is not None:
        return db_redirect

    route_name = _ADMIN_GET_REDIRECTS.get(path_value)
    if route_name:
        return _redirect_with_notice(request, route_name)

    if path_value.startswith("sync/"):
        return _redirect_with_notice(request, _route_for_legacy_sync(path_value))

    m = re.match(r"^utente/(?P<user_id>\d+)(?:/pdf)?$", path_value)
    if m:
        return _redirect_with_notice(
            request,
            "admin_portale:utente_edit",
            {"user_id": int(m.group("user_id"))},
        )

    return _redirect_with_notice(request, "admin_portale:index")


@login_required
@require_http_methods(["GET", "POST"])
def legacy_root_removed(request: HttpRequest, endpoint: str, user_id: int | None = None):
    _ = user_id  # path compat, non usato
    return _legacy_removed_response(request, f"/{endpoint}")
