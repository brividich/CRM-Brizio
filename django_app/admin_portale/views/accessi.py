"""Viste del Pannello di amministrazione — Accessi e permessi: ACL v2/legacy, ruoli, matrice, wizard ruolo, diagnostica.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.acl import diagnose_permesso_for_context
from core.acl_v2 import (
    diagnose_acl_access,
    normalize_binding_path_pattern,
    normalize_permission_code,
    validate_permission_code,
)
from core.audit import log_action
from core.legacy_cache import (
    bump_legacy_cache_version,
    get_cached_pulsanti_catalog,
    normalize_legacy_path,
)
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.navigation_registry import (
    bump_navigation_registry_version,
)
from core.legacy_utils import get_legacy_user, legacy_table_has_column
from core.acl_capability import STALE_MISSING_ROUTE, STALE_SHADOWED, capability_index
from core.permission_categories import (
    category_for,
    category_order,
    display_module,
    module_label,
    readable_label,
)
from core.permission_taxonomy import (
    ACCESS_LEVELS,
    AREA_ORDER,
    CAPABILITY_IGNOTO,
    NATURE_ORDER,
    area_for_module,
    area_label,
    capability_for_code,
    capability_label,
    nature_for_code,
    nature_label,
)
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    LegacyRedirect,
    NavigationItem,
    NavigationRoleAccess,
    PermissionDefinition,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionGrant,
    UserPermissionOverride,
)

from ..decorators import legacy_admin_required

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _module_perm_rows_for_role(ruolo_id: int) -> list[_helpers.ModuloPermRow]:
    return _helpers._aggregate_to_module_rows(_helpers._permission_rows_for_role(ruolo_id))


def _build_gestione_accessi_data(ruolo_id: int) -> list[dict]:
    """Dati per la pagina Gestione Accessi unificata.

    Restituisce una lista ordinata per modulo, ciascuna con:
      modulo, total_count, active_count, all_on, partial, pulsanti_rows
    dove ogni riga pulsante ha: pulsante, can_view, can_edit, can_delete, can_approve.

    Carica pulsanti e permessi con 2 query (no N+1).
    """
    try:
        all_pulsanti = list(Pulsante.objects.all().order_by("modulo", "nome_visibile", "id"))
    except DatabaseError:
        return []

    # Raggruppa per modulo
    grouped: dict[str, list[Pulsante]] = {}
    for p in all_pulsanti:
        mod = (p.modulo or "").strip()
        if not mod:
            continue
        grouped.setdefault(mod, []).append(p)

    # Carica tutti i permessi per il ruolo in una query sola
    try:
        raw_perms = list(Permesso.objects.filter(ruolo_id=ruolo_id))
    except DatabaseError:
        raw_perms = []

    # Indice (modulo_lower, azione_lower) â†’ permesso piÃ¹ recente
    perm_index: dict[tuple[str, str], Permesso] = {}
    for p in raw_perms:
        key = ((p.modulo or "").strip().lower(), (p.azione or "").strip().lower())
        # In caso di duplicati usa l'id piÃ¹ alto (piÃ¹ recente)
        if key not in perm_index or int(p.id) > int(perm_index[key].id):
            perm_index[key] = p

    optional_fields = [f for f in _helpers.PERM_OPTIONAL_FIELDS if legacy_table_has_column("permessi", f)]

    result: list[dict] = []
    for modulo in sorted(grouped.keys(), key=str.lower):
        pulsanti_list = grouped[modulo]
        pulsanti_rows: list[dict] = []
        active_count = 0

        for pulsante in pulsanti_list:
            azione = (pulsante.codice or "").strip()
            if not azione:
                continue
            perm = perm_index.get((modulo.lower(), azione.lower()))
            can_view = bool(getattr(perm, "can_view", 0)) or bool(getattr(perm, "consentito", 0)) if perm else False
            can_edit = bool(getattr(perm, "can_edit", 0)) if perm and "can_edit" in optional_fields else False
            can_delete = bool(getattr(perm, "can_delete", 0)) if perm and "can_delete" in optional_fields else False
            can_approve = bool(getattr(perm, "can_approve", 0)) if perm and "can_approve" in optional_fields else False
            if can_view:
                active_count += 1
            pulsanti_rows.append({
                "pulsante": pulsante,
                "azione": azione,
                "can_view": can_view,
                "can_edit": can_edit,
                "can_delete": can_delete,
                "can_approve": can_approve,
            })

        total = len(pulsanti_rows)
        result.append({
            "modulo": modulo,
            "pulsanti_rows": pulsanti_rows,
            "total_count": total,
            "active_count": active_count,
            "all_on": total > 0 and active_count == total,
            "partial": 0 < active_count < total,
            "optional_fields": optional_fields,
        })

    return result


_ACCESSI_SEMPLICE_ROUTE_ALIASES = {
    "anomalie_menu": "anomalie",
    "coming_assenze": "assenze",
    "employee_board": "dashboard",
    "dashboard_home": "dashboard",
    "scheda_dipendente": "dashboard",
    "richieste": "assenze",
}
_ACCESSI_SEMPLICE_PATH_ALIASES = {
    "/": "dashboard",
    "/dashboard": "dashboard",
    "/scheda-dipendente": "dashboard",
    "/richieste": "assenze",
    "/anomalie-menu": "anomalie",
}


def _normalize_accessi_semplice_module_key(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("._:/")


def _accessi_semplice_module_display_label(module_key: str) -> str:
    key = _normalize_accessi_semplice_module_key(module_key)
    catalog = _helpers.MODULE_CATALOG.get(key) or {}
    label = str(catalog.get("label") or "").strip()
    if label:
        return label
    return key.replace("_", " ").strip().title() or "N/D"


def _infer_accessi_semplice_module_from_route(route_name: str, known_modules: set[str]) -> str:
    route = str(route_name or "").strip()
    if not route:
        return ""

    route_norm = _normalize_accessi_semplice_module_key(route)
    alias = _ACCESSI_SEMPLICE_ROUTE_ALIASES.get(route_norm)
    if alias:
        return alias

    namespace = ""
    local_name = route
    if ":" in route:
        namespace, local_name = route.split(":", 1)
        namespace_norm = _normalize_accessi_semplice_module_key(namespace)
        if namespace_norm in known_modules:
            return namespace_norm

    local_norm = _normalize_accessi_semplice_module_key(local_name)
    if local_norm in known_modules:
        return local_norm
    if local_norm.startswith("coming_"):
        coming_target = _normalize_accessi_semplice_module_key(local_norm[len("coming_"):])
        if coming_target in known_modules:
            return coming_target

    tokens = [token for token in re.split(r"[_\-]+", local_name.lower()) if token]
    if tokens:
        first_token = _normalize_accessi_semplice_module_key(tokens[0])
        if first_token in known_modules:
            return first_token
        two_tokens = _normalize_accessi_semplice_module_key("_".join(tokens[:2]))
        if two_tokens in known_modules:
            return two_tokens

    return ""


def _infer_accessi_semplice_module_from_path(path_value: str, known_modules: set[str]) -> str:
    path_norm = normalize_legacy_path(path_value or "/")
    alias = _ACCESSI_SEMPLICE_PATH_ALIASES.get(path_norm)
    if alias:
        return alias

    pieces = [piece for piece in path_norm.strip("/").split("/") if piece]
    if not pieces:
        return ""
    first_piece = pieces[0]
    full_candidate = _normalize_accessi_semplice_module_key(first_piece)
    if full_candidate in known_modules:
        return full_candidate

    split_candidate = _normalize_accessi_semplice_module_key(first_piece.split("-", 1)[0])
    if split_candidate in known_modules:
        return split_candidate
    return ""


def _infer_navigation_item_module_key(item: NavigationItem, known_modules: set[str]) -> str:
    category = getattr(item, "category", None)
    category_key = _normalize_accessi_semplice_module_key(getattr(category, "key", ""))
    if category_key and category_key in known_modules:
        return category_key

    parent_code = _normalize_accessi_semplice_module_key(getattr(item, "parent_code", ""))
    if parent_code and parent_code in known_modules:
        return parent_code

    route_candidate = _infer_accessi_semplice_module_from_route(str(item.route_name or ""), known_modules)
    if route_candidate:
        return route_candidate

    target = _navigation_item_target_payload(item)
    path_candidate = _infer_accessi_semplice_module_from_path(
        str(target.get("normalized_path") or item.url_path or ""),
        known_modules,
    )
    if path_candidate:
        return path_candidate

    return ""


def _build_accessi_semplice_rows(selected_role_id: int | None) -> list[dict]:
    """Righe sintetiche modulo->canonical/menu con legacy come solo contesto."""
    try:
        _helpers.pulsanti = list(Pulsante.objects.all().order_by("modulo", "nome_visibile", "id"))
    except DatabaseError:
        return []

    try:
        permission_defs = list(
            PermissionDefinition.objects.filter(is_active=True).order_by("module", "code")
        )
    except Exception:
        permission_defs = []

    try:
        nav_items = list(
            NavigationItem.objects.filter(
                is_visible=True,
                is_enabled=True,
            )
            .exclude(section="admin_subnav")
            .select_related("category")
            .order_by("section", "order", "label", "id")
        )
    except Exception:
        nav_items = []

    known_modules = {
        _normalize_accessi_semplice_module_key(key)
        for key in _helpers.MODULE_CATALOG.keys()
        if _normalize_accessi_semplice_module_key(key)
    }
    for pulsante in _helpers.pulsanti:
        modulo_key = _normalize_accessi_semplice_module_key(pulsante.modulo or "")
        if modulo_key:
            known_modules.add(modulo_key)
    for perm in permission_defs:
        modulo_key = _normalize_accessi_semplice_module_key(perm.module or "")
        if modulo_key:
            known_modules.add(modulo_key)
    for item in nav_items:
        parent_code = _normalize_accessi_semplice_module_key(item.parent_code or "")
        if parent_code:
            known_modules.add(parent_code)

    grouped: dict[str, list[Pulsante]] = {}
    for pulsante in _helpers.pulsanti:
        modulo_key = _normalize_accessi_semplice_module_key(pulsante.modulo or "")
        if not modulo_key:
            continue
        grouped.setdefault(modulo_key, []).append(pulsante)

    canonical_by_module: dict[str, list[PermissionDefinition]] = {}
    for perm in permission_defs:
        modulo_key = _normalize_accessi_semplice_module_key(perm.module or "")
        if not modulo_key:
            continue
        canonical_by_module.setdefault(modulo_key, []).append(perm)

    navigation_by_module: dict[str, list[NavigationItem]] = {}
    for item in nav_items:
        modulo_key = _infer_navigation_item_module_key(item, known_modules)
        if not modulo_key:
            continue
        navigation_by_module.setdefault(modulo_key, []).append(item)

    module_perm_map: dict[str, _helpers.ModuloPermRow] = {}
    if selected_role_id is not None:
        try:
            for row in _module_perm_rows_for_role(selected_role_id):
                modulo_key = _normalize_accessi_semplice_module_key(row.modulo or "")
                if modulo_key:
                    module_perm_map[modulo_key] = row
        except DatabaseError:
            pass

    canonical_grants_map = _helpers._canonical_grants_map_for_role(selected_role_id)

    ui_meta_map = _helpers._pulsanti_ui_meta_map()
    rows: list[dict] = []
    all_modules = sorted(
        set(grouped.keys()) | set(canonical_by_module.keys()) | set(navigation_by_module.keys()),
        key=str.lower,
    )
    for modulo_key in all_modules:
        module_pulsanti = grouped.get(modulo_key, [])
        perm_row = module_perm_map.get(modulo_key)
        canonical_permissions = canonical_by_module.get(modulo_key, [])
        nav_module_items = navigation_by_module.get(modulo_key, [])

        enabled_values: list[bool] = []
        pulsanti_rows: list[dict] = []
        for pulsante in module_pulsanti:
            pid = int(pulsante.id)
            meta = ui_meta_map.get(pid, {})
            enabled = bool(meta.get("enabled", True))
            enabled_values.append(enabled)
            pulsanti_rows.append(
                {
                    "id": pid,
                    "label": pulsante.label,
                    "enabled": enabled,
                }
            )

        enabled_count = sum(1 for item in enabled_values if item)
        buttons_total = len(enabled_values)

        canonical_codes: list[str] = []
        seen_canonical_codes: set[str] = set()
        for perm in canonical_permissions:
            permission_code = normalize_permission_code(str(perm.code or ""))
            if not permission_code or permission_code in seen_canonical_codes:
                continue
            seen_canonical_codes.add(permission_code)
            canonical_codes.append(permission_code)
        canonical_enabled_count = sum(
            1 for code in canonical_codes if canonical_grants_map.get(code, False)
        )
        canonical_total = len(canonical_codes)
        canonical_enabled = canonical_total > 0 and canonical_enabled_count == canonical_total
        canonical_partial = canonical_enabled_count > 0 and canonical_enabled_count < canonical_total

        nav_item_ids = [int(item.id) for item in nav_module_items]
        nav_permission_codes = [_helpers._navigation_item_permission_code(item) for item in nav_module_items]
        nav_total = len(nav_item_ids)
        nav_mapped_count = sum(1 for code in nav_permission_codes if code)
        nav_unmapped_count = nav_total - nav_mapped_count
        nav_enabled_count = sum(1 for code in nav_permission_codes if code and canonical_grants_map.get(code, False))
        nav_enabled = nav_total > 0 and nav_unmapped_count == 0 and nav_enabled_count == nav_total
        nav_partial = (nav_enabled_count > 0 and nav_enabled_count < nav_total) or (nav_total > 0 and nav_unmapped_count > 0)

        legacy_role_enabled = bool(perm_row.can_view) if perm_row else False
        legacy_role_partial = bool(perm_row.partial) if perm_row else False
        canonical_managed = canonical_total > 0
        simple_enabled = canonical_managed and canonical_enabled
        legacy_drift = perm_row is not None and (legacy_role_partial or legacy_role_enabled != simple_enabled)
        simple_partial = (
            canonical_partial
            or (canonical_managed and nav_partial)
            or (not canonical_managed)
            or legacy_drift
        )
        display_label = _accessi_semplice_module_display_label(modulo_key)

        rows.append(
            {
                "modulo": modulo_key,
                "display_label": display_label,
                "pulsanti": pulsanti_rows,
                "pulsanti_count": len(pulsanti_rows),
                "sample_labels": [p["label"] for p in pulsanti_rows[:3]],
                "legacy_role_enabled": legacy_role_enabled,
                "legacy_role_partial": legacy_role_partial,
                "canonical_permissions_count": canonical_total,
                "canonical_permission_codes": canonical_codes,
                "canonical_enabled": canonical_enabled,
                "canonical_partial": canonical_partial,
                "canonical_managed": canonical_managed,
                "navigation_items_count": nav_total,
                "navigation_item_ids": nav_item_ids,
                "navigation_enabled": nav_enabled,
                "navigation_partial": nav_partial,
                "navigation_mapped_count": nav_mapped_count,
                "navigation_unmapped_count": nav_unmapped_count,
                "legacy_drift": legacy_drift,
                "buttons_enabled_count": enabled_count,
                "buttons_total_count": buttons_total,
                "simple_enabled": simple_enabled,
                "simple_partial": simple_partial,
            }
        )
    return rows


def _build_perm_detail(rows: list[_helpers.PermRow]) -> dict[str, list[dict]]:
    """Raggruppa i PermRow per modulo in un dict {modulo: [{azione, label, can_view}]}."""
    result: dict[str, list[dict]] = {}
    for row in rows:
        key = (row.modulo or "").strip() or "N/D"
        result.setdefault(key, []).append({
            "azione": row.azione,
            "label": row.label or row.azione,
            "can_view": bool(row.values.get("can_view", 0)),
        })
    return result


def _normalize_acl_diag_path(raw_path: str) -> str:
    raw = str(raw_path or "").strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw


def _safe_reverse_route(route_name: str) -> tuple[str, str]:
    route = str(route_name or "").strip()
    if not route:
        return "", ""
    try:
        return reverse(route), ""
    except Exception as exc:
        return "", str(exc)


def _resolve_view_name_for_path(path_value: str) -> str:
    try:
        match = resolve(path_value)
        return str(getattr(match, "view_name", "") or "").strip()
    except Resolver404:
        return ""
    except Exception:
        return ""


def _navigation_item_target_payload(item: NavigationItem) -> dict:
    route_name = str(item.route_name or "").strip()
    url_path = str(item.url_path or "").strip()
    href = ""
    reverse_error = ""
    coming = False
    if route_name:
        href, reverse_error = _safe_reverse_route(route_name)
        if reverse_error:
            coming = True
            href = reverse("coming_admin")
    elif url_path:
        href = url_path
    else:
        coming = True
        href = reverse("coming_admin")
    if route_name == "coming_admin":
        coming = True
    is_external = str(href).lower().startswith(("http://", "https://"))
    normalized_path = normalize_legacy_path(href) if href and not is_external else ""
    return {
        "href": href,
        "normalized_path": normalized_path,
        "route_name": route_name,
        "reverse_error": reverse_error,
        "coming": coming,
        "is_external": is_external,
    }


def _canonical_role_ids_for_permission(permission_code: str) -> list[int]:
    permission_norm = normalize_permission_code(permission_code)
    if not permission_norm:
        return []
    try:
        return sorted(
            {
                int(row.legacy_role_id)
                for row in RolePermissionGrant.objects.filter(
                    permission_id=permission_norm,
                    enabled=True,
                ).only("legacy_role_id")
            }
        )
    except Exception:
        return []


def _role_ids_to_labels(role_ids: list[int], role_name_map: dict[int, str]) -> list[str]:
    labels: list[str] = []
    for role_id in role_ids:
        rid = int(role_id)
        role_name = role_name_map.get(rid, "?") or "?"
        labels.append(f"{rid} - {role_name}")
    return labels


def _collect_registry_matches_for_path(
    *,
    path_norm: str,
    route_name: str,
    role_name_map: dict[int, str],
) -> list[dict]:
    try:
        items = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    except DatabaseError:
        return []
    if not items:
        return []

    item_ids = [int(item.id) for item in items]
    access_rows = list(
        NavigationRoleAccess.objects.filter(item_id__in=item_ids, can_view=True)
        .order_by("item_id", "legacy_role_id")
    )
    access_map: dict[int, list[int]] = {}
    for row in access_rows:
        access_map.setdefault(int(row.item_id), []).append(int(row.legacy_role_id))

    matched_rows: list[dict] = []
    for item in items:
        target = _navigation_item_target_payload(item)
        permission_code = _helpers._navigation_item_permission_code(item)
        item_route_name = str(item.route_name or "").strip()
        item_url_path = str(item.url_path or "").strip()
        item_url_norm = normalize_legacy_path(item_url_path) if item_url_path and item_url_path.startswith("/") else ""

        is_match = False
        if route_name and route_name == item_route_name:
            is_match = True
        if path_norm and target["normalized_path"] == path_norm:
            is_match = True
        if path_norm and item_url_norm and item_url_norm == path_norm:
            is_match = True
        if not is_match:
            continue

        role_ids = (
            _canonical_role_ids_for_permission(permission_code)
            if permission_code
            else sorted(set(access_map.get(int(item.id), [])))
        )
        matched_rows.append(
            {
                "id": int(item.id),
                "code": item.code,
                "label": item.label,
                "section": item.section,
                "group": item.group or "",
                "required_permission_code": permission_code,
                "route_name": item.route_name or "",
                "url_path": item.url_path or "",
                "target_href": target["href"],
                "target_path": target["normalized_path"],
                "coming": bool(target["coming"]),
                "reverse_error": target["reverse_error"],
                "role_ids": role_ids,
                "role_labels": _role_ids_to_labels(role_ids, role_name_map),
                "is_visible": bool(item.is_visible),
                "is_enabled": bool(item.is_enabled),
            }
        )
    return matched_rows


def _collect_legacy_redirect_matches(*, path_norm: str, route_name: str) -> dict:
    try:
        rows = list(LegacyRedirect.objects.filter(is_enabled=True).order_by("legacy_path", "id"))
    except Exception:
        return {"inbound": [], "outbound": []}

    inbound: list[dict] = []
    outbound: list[dict] = []
    for row in rows:
        legacy_norm = normalize_legacy_path(str(row.legacy_path or "/"))
        target_route_name = str(row.target_route_name or "").strip()
        target_url_path = str(row.target_url_path or "").strip()
        target_route_path = ""
        reverse_error = ""
        target_route_norm = ""
        if target_route_name:
            target_route_path, reverse_error = _safe_reverse_route(target_route_name)
            if target_route_path:
                target_route_norm = normalize_legacy_path(target_route_path)
        target_url_norm = normalize_legacy_path(target_url_path) if target_url_path.startswith("/") else ""
        target_norm = target_route_norm or target_url_norm
        payload = {
            "id": int(row.id),
            "legacy_path": legacy_norm,
            "target_route_name": target_route_name,
            "target_route_path": target_route_path,
            "target_url_path": target_url_path,
            "target_path_normalized": target_norm,
            "reverse_error": reverse_error,
            "note": row.note or "",
        }
        if legacy_norm == path_norm:
            inbound.append(payload)
        if (route_name and target_route_name == route_name) or (target_norm and target_norm == path_norm):
            outbound.append(payload)

    return {"inbound": inbound, "outbound": outbound}


def _acl_diag_badges(*, diag: dict, registry_matches: list[dict], redirect_matches: dict) -> list[str]:
    badges: list[str] = []
    canonical_result = diag.get("canonical_result") or {}
    canonical_payload = canonical_result.get("canonical") or {}
    final_source = str(diag.get("final_decision_source") or canonical_result.get("decision_source") or "").strip()
    if canonical_payload.get("binding_found"):
        badges.append("CANONICAL_BINDING")
    if final_source == "canonical":
        badges.append("CANONICAL_DECISION")
    if final_source == "legacy_fallback":
        badges.append("LEGACY_FALLBACK")
    if final_source == "legacy_admin_bypass":
        badges.append("LEGACY_ADMIN_BYPASS")
    if final_source == "superuser_bypass":
        badges.append("SUPERUSER_BYPASS")
    if registry_matches:
        badges.append("REGISTRY")
    override = diag.get("override") or {}
    inbound = (redirect_matches.get("inbound") or [])
    outbound = (redirect_matches.get("outbound") or [])
    if inbound or outbound:
        badges.append("REDIRECT")
    if any(bool(row.get("coming")) for row in registry_matches):
        badges.append("COMING")
    if final_source == "legacy_fallback" and diag.get("pulsante"):
        badges.append("LEGACY_MATCH")
    if final_source == "legacy_fallback" and override.get("can_view") is not None:
        badges.append("LEGACY_OVERRIDE")
    return badges


def _acl_human_summary(diag: dict) -> dict:
    canonical_result = diag.get("canonical_result") or {}
    canonical_payload = canonical_result.get("canonical") or {}
    final_allowed = bool(diag.get("final_allowed", canonical_result.get("allowed", False)))
    final_source = str(diag.get("final_decision_source") or canonical_result.get("decision_source") or "").strip()
    permission_code = str((canonical_payload.get("binding") or {}).get("permission_code") or "")
    effective_level = str(canonical_payload.get("effective_level") or "")
    role_name = str((diag.get("role") or {}).get("nome") or "ruolo")

    if final_source == "superuser_bypass":
        return {
            "title": "Accesso consentito: bypass superuser Django.",
            "detail": "La route non e stata valutata da binding/grant perche l'utente e superuser.",
            "tone": "allow",
        }
    if final_source == "legacy_admin_bypass":
        return {
            "title": "Accesso consentito: bypass admin legacy.",
            "detail": "Il resolver ha riconosciuto l'utente come admin legacy.",
            "tone": "allow",
        }
    if final_source == "canonical":
        if final_allowed:
            if effective_level == "user_override":
                return {
                    "title": f"Accesso consentito: override utente canonico su '{permission_code}'.",
                    "detail": "La route e bindata al permission code e l'override utente ha precedenza sul grant ruolo.",
                    "tone": "allow",
                }
            return {
                "title": f"Accesso consentito: il ruolo '{role_name}' ha grant su '{permission_code}'.",
                "detail": "Decisione canonica route -> permission_code -> grant ruolo.",
                "tone": "allow",
            }
        if effective_level == "user_override":
            return {
                "title": f"Accesso negato: override utente canonico nega '{permission_code}'.",
                "detail": "L'override utente ha precedenza sul grant ruolo.",
                "tone": "deny",
            }
        role_grant = canonical_payload.get("role_grant") or {}
        if role_grant.get("exists") is False:
            return {
                "title": f"Accesso negato: route bindata a '{permission_code}' ma grant ruolo assente.",
                "detail": "Il fallback legacy non viene usato perche il binding canonico esiste.",
                "tone": "deny",
            }
        return {
            "title": f"Accesso negato: route bindata a '{permission_code}' e grant ruolo non abilitato.",
            "detail": "Decisione canonica prioritaria rispetto al legacy.",
            "tone": "deny",
        }
    if final_source == "legacy_fallback":
        if final_allowed:
            return {
                "title": "Accesso consentito dal fallback legacy.",
                "detail": "Manca un binding canonico per questa route/path; la decisione arriva dalla catena legacy.",
                "tone": "allow",
            }
        return {
            "title": "Accesso negato dal fallback legacy.",
            "detail": "Manca un binding canonico e il controllo legacy ha negato l'accesso.",
            "tone": "deny",
        }
    if final_allowed:
        return {
            "title": "Accesso consentito.",
            "detail": str(diag.get("final_reason") or canonical_result.get("reason") or ""),
            "tone": "allow",
        }
    return {
        "title": "Accesso negato.",
        "detail": str(diag.get("final_reason") or canonical_result.get("reason") or ""),
        "tone": "deny",
    }


def _permission_row_is_allowed(can_view, consentito) -> bool:
    return bool(can_view) or bool(consentito)


def _build_allowed_roles_by_permission_key() -> dict[tuple[str, str], set[int]]:
    result: dict[tuple[str, str], set[int]] = {}
    try:
        rows = list(
            Permesso.objects.all().values(
                "ruolo_id",
                "modulo",
                "azione",
                "can_view",
                "consentito",
            )
        )
    except Exception:
        return result
    for row in rows:
        if not _permission_row_is_allowed(row.get("can_view"), row.get("consentito")):
            continue
        modulo = str(row.get("modulo") or "").strip().lower()
        azione = str(row.get("azione") or "").strip().lower()
        ruolo_id = _helpers._int_or_none(row.get("ruolo_id"))
        if not modulo or not azione or ruolo_id is None:
            continue
        result.setdefault((modulo, azione), set()).add(int(ruolo_id))
    return result


def _build_override_counts_by_permission_key() -> dict[tuple[str, str], dict[str, int]]:
    result: dict[tuple[str, str], dict[str, int]] = {}
    try:
        rows = list(
            UserPermissionOverride.objects.exclude(can_view__isnull=True).values(
                "modulo",
                "azione",
                "can_view",
            )
        )
    except Exception:
        return result
    for row in rows:
        modulo = str(row.get("modulo") or "").strip().lower()
        azione = str(row.get("azione") or "").strip().lower()
        if not modulo or not azione:
            continue
        key = (modulo, azione)
        bucket = result.setdefault(key, {"allow": 0, "deny": 0})
        if bool(row.get("can_view")):
            bucket["allow"] += 1
        else:
            bucket["deny"] += 1
    return result


def _canonical_binding_matches_path(binding: RoutePermissionBinding, path_norm: str) -> bool:
    strategy = (binding.match_strategy or RoutePermissionBinding.MATCH_EXACT).lower()
    if strategy == RoutePermissionBinding.MATCH_REGEX:
        try:
            return re.search(binding.path_pattern or "", path_norm) is not None
        except re.error:
            return False
    pattern = normalize_binding_path_pattern(binding.path_pattern, for_regex=False)
    if not pattern:
        return False
    if strategy == RoutePermissionBinding.MATCH_PREFIX:
        return path_norm == pattern or path_norm.startswith(pattern + "/")
    return path_norm == pattern


def _build_permission_navigation_map_rows(
    *,
    q_filter: str,
    source_filter: str,
    selected_role_id: int | None,
    role_name_map: dict[int, str],
) -> list[dict]:
    rows_by_key: dict[str, dict] = {}
    q_norm = str(q_filter or "").strip().lower()
    allowed_roles_map = _build_allowed_roles_by_permission_key()
    override_map = _build_override_counts_by_permission_key()
    canonical_route_map: dict[str, list[RoutePermissionBinding]] = {}
    canonical_path_bindings: list[RoutePermissionBinding] = []
    canonical_grants_by_code: dict[str, dict] = {}
    registry_enabled = bool(getattr(settings, "NAVIGATION_REGISTRY_ENABLED", True))
    fallback_enabled = bool(getattr(settings, "NAVIGATION_LEGACY_FALLBACK_ENABLED", False))

    try:
        canonical_bindings = list(
            RoutePermissionBinding.objects.filter(is_active=True)
            .select_related("permission")
            .order_by("priority", "id")
        )
    except Exception:
        canonical_bindings = []
    for binding in canonical_bindings:
        route_name_norm = str(binding.route_name or "").strip().lower()
        if route_name_norm:
            canonical_route_map.setdefault(route_name_norm, []).append(binding)
        if str(binding.path_pattern or "").strip():
            canonical_path_bindings.append(binding)

    if selected_role_id is not None:
        try:
            grants = list(
                RolePermissionGrant.objects.filter(legacy_role_id=int(selected_role_id)).values(
                    "id", "permission_id", "enabled"
                )
            )
        except Exception:
            grants = []
        for grant_row in grants:
            permission_code = str(grant_row.get("permission_id") or "").strip()
            if not permission_code:
                continue
            canonical_grants_by_code[permission_code] = {
                "id": int(grant_row.get("id") or 0),
                "enabled": bool(grant_row.get("enabled")),
            }

    def ensure_row(path_norm: str) -> dict:
        key = f"path:{path_norm}"
        row = rows_by_key.get(key)
        if row is None:
            row = {
                "path": path_norm,
                "route_names": set(),
                "menu_labels": set(),
                "registry_sections": set(),
                "registry_role_ids": set(),
                "legacy_role_ids": set(),
                "source_flags": set(),
                "redirect_paths": set(),
                "override_allow": 0,
                "override_deny": 0,
                "coming": False,
                "admin_bypass": False,
                "legacy_buttons": [],
                "registry_items": [],
                "applied_override_keys": set(),
                "canonical_permissions": {},
            }
            rows_by_key[key] = row
        return row

    for route in _helpers._route_catalog():
        path = str(route.get("path") or "").strip()
        if not path:
            continue
        path_norm = normalize_legacy_path(path)
        row = ensure_row(path_norm)
        route_name = str(route.get("route_name") or "").strip()
        if route_name:
            row["route_names"].add(route_name)

    try:
        registry_items = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    except Exception:
        registry_items = []
    access_map: dict[int, set[int]] = {}
    if registry_items:
        access_rows = list(
            NavigationRoleAccess.objects.filter(
                item_id__in=[int(item.id) for item in registry_items],
                can_view=True,
            ).order_by("item_id", "legacy_role_id")
        )
        for row in access_rows:
            access_map.setdefault(int(row.item_id), set()).add(int(row.legacy_role_id))

    for item in registry_items:
        target = _navigation_item_target_payload(item)
        permission_code = _helpers._navigation_item_permission_code(item)
        path_norm = str(target.get("normalized_path") or "").strip()
        if not path_norm:
            continue
        row = ensure_row(path_norm)
        row["source_flags"].add("REGISTRY")
        row["menu_labels"].add(str(item.label or item.code or path_norm))
        row["registry_sections"].add(str(item.section or ""))
        if target.get("coming"):
            row["coming"] = True
        if item.route_name:
            row["route_names"].add(str(item.route_name).strip())
        role_ids = (
            set(_canonical_role_ids_for_permission(permission_code))
            if permission_code
            else access_map.get(int(item.id), set())
        )
        row["registry_role_ids"].update(role_ids)
        row["registry_items"].append(
            {
                "id": int(item.id),
                "code": item.code,
                "label": item.label,
                "section": item.section,
                "required_permission_code": permission_code,
                "route_name": item.route_name or "",
                "url_path": item.url_path or "",
                "role_ids": sorted(role_ids),
            }
        )

    for pulsante in get_cached_pulsanti_catalog():
        path_norm = str(pulsante.get("url_normalized") or "").strip()
        if not path_norm:
            continue
        row = ensure_row(path_norm)
        row["source_flags"].add("LEGACY")
        row["menu_labels"].add(str(pulsante.get("label") or pulsante.get("codice") or path_norm))
        row["admin_bypass"] = True
        modulo_norm = str(pulsante.get("modulo_norm") or "").strip().lower()
        codice_norm = str(pulsante.get("codice_norm") or "").strip().lower()
        perm_key = (modulo_norm, codice_norm)
        row["legacy_role_ids"].update(allowed_roles_map.get(perm_key, set()))
        if perm_key in override_map and perm_key not in row["applied_override_keys"]:
            row["applied_override_keys"].add(perm_key)
            row["override_allow"] += int(override_map[perm_key]["allow"])
            row["override_deny"] += int(override_map[perm_key]["deny"])
        row["legacy_buttons"].append(
            {
                "id": int(pulsante["id"]),
                "modulo": pulsante.get("modulo") or "",
                "azione": pulsante.get("codice") or "",
                "label": pulsante.get("label") or "",
            }
        )

    try:
        redirects = list(LegacyRedirect.objects.filter(is_enabled=True).order_by("legacy_path", "id"))
    except Exception:
        redirects = []
    for redirect_row in redirects:
        target_route_name = str(redirect_row.target_route_name or "").strip()
        target_url_path = str(redirect_row.target_url_path or "").strip()
        target_path = ""
        if target_route_name:
            target_path, _err = _safe_reverse_route(target_route_name)
        if not target_path and target_url_path.startswith("/"):
            target_path = target_url_path
        if not target_path:
            continue
        target_norm = normalize_legacy_path(target_path)
        row = ensure_row(target_norm)
        row["source_flags"].add("REDIRECT")
        row["redirect_paths"].add(normalize_legacy_path(str(redirect_row.legacy_path or "/")))
        if target_route_name:
            row["route_names"].add(target_route_name)

    rows: list[dict] = []
    for row in rows_by_key.values():
        source_flags = set(row["source_flags"])
        role_ids = sorted(set(row["registry_role_ids"]) | set(row["legacy_role_ids"]))
        selected_role_visible = selected_role_id is None or selected_role_id in role_ids

        has_override = bool(row["override_allow"] or row["override_deny"])
        is_fallback = bool(registry_enabled and fallback_enabled and "LEGACY" in source_flags and "REGISTRY" not in source_flags)
        badges: list[str] = []
        if "REGISTRY" in source_flags:
            badges.append("REGISTRY")
        if "LEGACY" in source_flags:
            badges.append("LEGACY")
        if has_override:
            badges.append("OVERRIDE")
        if row["admin_bypass"]:
            badges.append("ADMIN BYPASS")
        if row["redirect_paths"]:
            badges.append("REDIRECT")
        if row["coming"]:
            badges.append("COMING")
        if is_fallback:
            badges.append("FALLBACK")

        if source_filter == "registry" and "REGISTRY" not in source_flags:
            continue
        if source_filter == "legacy" and "LEGACY" not in source_flags:
            continue
        if source_filter == "redirect" and not row["redirect_paths"]:
            continue
        if source_filter == "override" and not has_override:
            continue
        if source_filter == "fallback" and not is_fallback:
            continue

        legacy_buttons = sorted(
            row["legacy_buttons"],
            key=lambda item: (
                str(item.get("modulo") or "").lower(),
                str(item.get("azione") or "").lower(),
                int(item.get("id") or 0),
            ),
        )
        for button in legacy_buttons:
            modulo_norm = str(button.get("modulo") or "").strip().lower()
            azione_norm = str(button.get("azione") or "").strip().lower()
            allowed_roles = sorted(allowed_roles_map.get((modulo_norm, azione_norm), set()))
            button["allowed_role_ids"] = allowed_roles
            button["selected_role_allowed"] = (
                bool(selected_role_id in allowed_roles) if selected_role_id is not None else None
            )

        if selected_role_id is not None and not selected_role_visible:
            if not legacy_buttons:
                continue

        route_names = sorted([v for v in row["route_names"] if v])
        matched_bindings: dict[int, dict] = {}
        for route_name in route_names:
            for binding in canonical_route_map.get(route_name.lower(), []):
                slot = matched_bindings.setdefault(
                    int(binding.id),
                    {"binding": binding, "matched_by": set()},
                )
                slot["matched_by"].add("route_name")
        for binding in canonical_path_bindings:
            if not _canonical_binding_matches_path(binding, row["path"]):
                continue
            slot = matched_bindings.setdefault(
                int(binding.id),
                {"binding": binding, "matched_by": set()},
            )
            slot["matched_by"].add("path_pattern")

        canonical_permissions_map: dict[str, dict] = {}
        for payload in matched_bindings.values():
            binding = payload["binding"]
            permission_code = str(binding.permission_id or "").strip()
            if not permission_code:
                continue
            permission_label = ""
            permission_module = ""
            permission_active = True
            try:
                permission_label = str(binding.permission.label or "").strip()
                permission_module = str(binding.permission.module or "").strip()
                permission_active = bool(binding.permission.is_active)
            except Exception:
                permission_label = ""
                permission_module = ""
                permission_active = True

            row_entry = canonical_permissions_map.setdefault(
                permission_code,
                {
                    "permission_code": permission_code,
                    "permission_label": permission_label,
                    "permission_module": permission_module,
                    "permission_active": permission_active,
                    "bindings": [],
                },
            )
            matched_by = sorted([value for value in payload["matched_by"] if value])
            row_entry["bindings"].append(
                {
                    "id": int(binding.id),
                    "route_name": str(binding.route_name or "").strip(),
                    "path_pattern": str(binding.path_pattern or "").strip(),
                    "match_strategy": str(binding.match_strategy or "").strip(),
                    "source_app": str(binding.source_app or "").strip(),
                    "priority": int(binding.priority or 0),
                    "matched_by": matched_by,
                }
            )

        canonical_permissions = sorted(
            canonical_permissions_map.values(),
            key=lambda item: str(item.get("permission_code") or "").lower(),
        )
        canonical_missing_grants = 0
        canonical_denied_grants = 0
        canonical_enabled_grants = 0
        for canonical_row in canonical_permissions:
            permission_code = str(canonical_row.get("permission_code") or "").strip()
            grant_info = canonical_grants_by_code.get(permission_code)
            grant_exists = grant_info is not None
            grant_enabled = bool(grant_info.get("enabled")) if grant_info else False
            canonical_row["selected_role_grant_exists"] = bool(grant_exists) if selected_role_id is not None else None
            canonical_row["selected_role_grant_enabled"] = bool(grant_enabled) if selected_role_id is not None else None
            canonical_row["selected_role_grant_id"] = int(grant_info.get("id") or 0) if grant_info else None
            canonical_row["bindings"] = sorted(
                canonical_row["bindings"],
                key=lambda item: (
                    int(item.get("priority") or 0),
                    str(item.get("route_name") or "").lower(),
                    str(item.get("path_pattern") or "").lower(),
                    int(item.get("id") or 0),
                ),
            )
            if selected_role_id is None:
                continue
            if grant_info is None:
                canonical_missing_grants += 1
            elif grant_enabled:
                canonical_enabled_grants += 1
            else:
                canonical_denied_grants += 1

        menu_labels = sorted([v for v in row["menu_labels"] if v])
        role_labels = _role_ids_to_labels(role_ids, role_name_map)
        search_blob = " ".join(
            [
                row["path"],
                " ".join(route_names),
                " ".join(menu_labels),
                " ".join(role_labels),
                " ".join(sorted(source_flags)),
                " ".join(sorted(row["registry_sections"])),
                " ".join(
                    [str(item.get("permission_code") or "") for item in canonical_permissions]
                ),
                " ".join(
                    [str(item.get("permission_label") or "") for item in canonical_permissions]
                ),
            ]
        ).lower()
        if q_norm and q_norm not in search_blob:
            continue

        rows.append(
            {
                "path": row["path"],
                "route_names": route_names,
                "menu_labels": menu_labels,
                "source_flags": sorted(source_flags),
                "source_label": " + ".join(sorted(source_flags)) if source_flags else "-",
                "registry_sections": sorted([s for s in row["registry_sections"] if s]),
                "role_ids": role_ids,
                "role_labels": role_labels,
                "selected_role_visible": bool(selected_role_visible),
                "override_allow": int(row["override_allow"]),
                "override_deny": int(row["override_deny"]),
                "redirect_paths": sorted(row["redirect_paths"]),
                "badges": badges,
                "is_fallback": is_fallback,
                "legacy_buttons_count": len(row["legacy_buttons"]),
                "registry_items_count": len(row["registry_items"]),
                "canonical_permissions_count": len(canonical_permissions),
                "canonical_permissions": canonical_permissions,
                "canonical_selected_role_missing_grants": int(canonical_missing_grants),
                "canonical_selected_role_denied_grants": int(canonical_denied_grants),
                "canonical_selected_role_enabled_grants": int(canonical_enabled_grants),
                "legacy_buttons": legacy_buttons,
                "registry_items": sorted(
                    row["registry_items"],
                    key=lambda item: (
                        str(item.get("section") or "").lower(),
                        str(item.get("label") or "").lower(),
                        int(item.get("id") or 0),
                    ),
                ),
            }
        )

    rows.sort(key=lambda r: (r["path"], ", ".join(r["route_names"])))
    return rows


@legacy_admin_required
def acl_diagnostica(request):
    source = request.POST if request.method == "POST" else request.GET
    requested_user_id = _helpers._int_or_none(source.get("legacy_user_id"))
    requested_role_id = _helpers._int_or_none(source.get("legacy_role_id"))
    path_input = str(source.get("path") or "").strip()
    route_name_input = str(source.get("route_name") or "").strip()

    selected_route_path = ""
    route_reverse_error = ""
    if route_name_input:
        selected_route_path, route_reverse_error = _safe_reverse_route(route_name_input)
        if not path_input and selected_route_path:
            path_input = selected_route_path
    if route_name_input and route_reverse_error:
        messages.warning(request, f"Route '{route_name_input}' non risolvibile: {route_reverse_error}")

    if not path_input:
        path_input = "/assenze/"
    path_value = _normalize_acl_diag_path(path_input)
    resolved_route_name = _resolve_view_name_for_path(path_value)
    effective_route_name = route_name_input or resolved_route_name
    path_normalized = normalize_legacy_path(path_value)

    current_legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    target_legacy_user = current_legacy_user
    if requested_user_id is not None:
        try:
            target_legacy_user = UtenteLegacy.objects.filter(id=requested_user_id).first()
            if target_legacy_user is None:
                messages.warning(request, f"Utente legacy ID {requested_user_id} non trovato.")
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura utente legacy: {exc}")
            target_legacy_user = None

    role_choices = _helpers._role_choices()
    role_name_map = {int(role.id): str(role.nome or "") for role in role_choices}
    valid_role_ids = set(role_name_map.keys())
    if requested_role_id is not None and requested_role_id not in valid_role_ids:
        messages.warning(request, f"Ruolo legacy ID {requested_role_id} non trovato: ignorato.")
        requested_role_id = None

    legacy_diag = diagnose_permesso_for_context(
        legacy_user=target_legacy_user,
        path=path_value,
        forced_role_id=requested_role_id,
    )

    canonical_legacy_user = target_legacy_user
    if requested_role_id is not None:
        role_name = role_name_map.get(int(requested_role_id), "")
        if target_legacy_user is not None:
            canonical_legacy_user = UtenteLegacy(
                id=target_legacy_user.id,
                nome=target_legacy_user.nome,
                email=target_legacy_user.email,
                password=target_legacy_user.password,
                ruolo=role_name or target_legacy_user.ruolo,
                attivo=target_legacy_user.attivo,
                deve_cambiare_password=target_legacy_user.deve_cambiare_password,
                ruolo_id=requested_role_id,
            )
        else:
            canonical_legacy_user = UtenteLegacy(
                id=-1,
                nome=f"Simulazione ruolo #{requested_role_id}",
                email="",
                password="",
                ruolo=role_name or "",
                attivo=True,
                deve_cambiare_password=False,
                ruolo_id=requested_role_id,
            )

    canonical_diag = diagnose_acl_access(
        path=path_value,
        legacy_user=canonical_legacy_user,
        # In diagnostica admin mostriamo la decisione ACL "reale" del target legacy
        # senza bypass automatico del superuser che sta consultando la pagina.
        django_user=None,
    )
    diag = dict(legacy_diag)
    diag["legacy_result"] = legacy_diag
    diag["canonical_result"] = canonical_diag
    diag["final_allowed"] = bool(canonical_diag.get("allowed", False))
    diag["final_reason"] = str(canonical_diag.get("reason") or legacy_diag.get("reason") or "")
    diag["final_decision_source"] = str(canonical_diag.get("decision_source") or legacy_diag.get("decision_source") or "")
    diag["route_name_canonical"] = str(canonical_diag.get("route_name") or "")
    diag["path_normalized"] = str(canonical_diag.get("path_normalized") or legacy_diag.get("path_normalized") or "")
    diag["trace"] = list(canonical_diag.get("trace") or [])

    if requested_user_id is not None and not target_legacy_user:
        diag["reason"] = diag.get("reason") or "Utente legacy richiesto non disponibile."

    registry_matches = _collect_registry_matches_for_path(
        path_norm=path_normalized,
        route_name=effective_route_name,
        role_name_map=role_name_map,
    )
    redirect_matches = _collect_legacy_redirect_matches(
        path_norm=path_normalized,
        route_name=effective_route_name,
    )
    diag["route_resolution"] = {
        "selected_route_name": route_name_input,
        "selected_route_path": selected_route_path,
        "resolved_route_name": resolved_route_name,
        "path_normalized": path_normalized,
    }
    diag["registry_matches"] = registry_matches
    diag["redirect_matches"] = redirect_matches
    diag["badges"] = _acl_diag_badges(
        diag=diag,
        registry_matches=registry_matches,
        redirect_matches=redirect_matches,
    )
    diag["human_summary"] = _acl_human_summary(diag)
    diag["navigation_summary"] = {
        "registry_match_count": len(registry_matches),
        "redirect_inbound_count": len(redirect_matches.get("inbound") or []),
        "redirect_outbound_count": len(redirect_matches.get("outbound") or []),
        "legacy_acl_match": bool(legacy_diag.get("pulsante")),
    }

    return render(
        request,
        "admin_portale/pages/acl_diagnostica.html",
        {
            "diag": diag,
            "path_value": path_value,
            "route_name_value": route_name_input,
            "requested_user_id": requested_user_id if requested_user_id is not None else "",
            "requested_role_id": requested_role_id if requested_role_id is not None else "",
            "current_legacy_user": current_legacy_user,
            "target_legacy_user": target_legacy_user,
            "route_catalog": _helpers._route_catalog(),
            "role_choices": role_choices,
        },
    )


@legacy_admin_required
@require_GET
def mappa_permessi_navigazione(request):
    q_filter = str(request.GET.get("q") or "").strip()
    source_filter = str(request.GET.get("source") or "all").strip().lower()
    if source_filter not in {"all", "registry", "legacy", "redirect", "override", "fallback"}:
        source_filter = "all"

    selected_role_id = _helpers._int_or_none(request.GET.get("legacy_role_id"))
    role_choices = _helpers._role_choices()
    role_name_map = {int(role.id): str(role.nome or "") for role in role_choices}
    if selected_role_id is not None and selected_role_id not in set(role_name_map.keys()):
        messages.warning(request, f"Ruolo legacy ID {selected_role_id} non trovato: filtro ignorato.")
        selected_role_id = None

    rows = _build_permission_navigation_map_rows(
        q_filter=q_filter,
        source_filter=source_filter,
        selected_role_id=selected_role_id,
        role_name_map=role_name_map,
    )
    summary = {
        "rows_total": len(rows),
        "rows_canonical": sum(1 for row in rows if row["canonical_permissions_count"] > 0),
        "rows_registry": sum(1 for row in rows if "REGISTRY" in row["source_flags"]),
        "rows_legacy": sum(1 for row in rows if "LEGACY" in row["source_flags"]),
        "rows_override": sum(1 for row in rows if "OVERRIDE" in row["badges"]),
        "rows_redirect": sum(1 for row in rows if "REDIRECT" in row["badges"]),
    }
    selected_role_label = ""
    if selected_role_id is not None:
        selected_role_label = role_name_map.get(int(selected_role_id), "")

    return render(
        request,
        "admin_portale/pages/mappa_permessi_navigazione.html",
        {
            "rows": rows,
            "summary": summary,
            "filters": {
                "q": q_filter,
                "source": source_filter,
                "legacy_role_id": selected_role_id if selected_role_id is not None else "",
            },
            "role_choices": role_choices,
            "selected_role_id": selected_role_id,
            "selected_role_label": selected_role_label,
            "api_permessi_toggle_url": reverse("admin_portale:api_permessi_toggle"),
            "api_acl_v2_role_grant_toggle_url": reverse("admin_portale:api_acl_v2_role_grant_toggle"),
        },
    )


@legacy_admin_required
@require_GET
def permessi(request):
    # Fase 3 dismissione legacy: la gestione permessi e' consolidata su una
    # sola schermata canonica (/admin-portale/acl-canonico/). La vecchia UI
    # legacy mostrava permessi che — sui moduli con binding canonico — non
    # hanno effetto a runtime, generando confusione (caso a.astarita). Qui
    # reindirizziamo, preservando ruolo/utente selezionato. Il corpo legacy
    # resta sotto come rete di sicurezza, riattivabile con
    # ACL_LEGACY_PERMESSI_UI_ENABLED=True finche' la migrazione non e' chiusa.
    if not getattr(settings, "ACL_LEGACY_PERMESSI_UI_ENABLED", False):
        params = {}
        ruolo_id = _helpers._int_or_none(request.GET.get("ruolo_id"))
        user_id = _helpers._int_or_none(request.GET.get("user_id"))
        if ruolo_id is not None:
            params["role_id"] = str(ruolo_id)
        if user_id is not None:
            params["selected_user_id"] = str(user_id)
        url = reverse("admin_portale:acl_canonico")
        if params:
            url = f"{url}?{urlencode(params)}"
        return redirect(url)

    roles = _helpers._role_choices()
    users = list(UtenteLegacy.objects.order_by("nome", "id"))
    target_type = request.GET.get("target_type", "role")  # "role" | "user"
    selected_role_id = _helpers._int_or_none(request.GET.get("ruolo_id"))
    selected_user_id = _helpers._int_or_none(request.GET.get("user_id"))

    module_rows: list[_helpers.ModuloPermRow] = []
    perm_detail: dict[str, list[dict]] = {}
    selected_user = None
    if target_type == "user":
        if selected_user_id is not None:
            selected_user = UtenteLegacy.objects.filter(id=selected_user_id).first()
            try:
                raw_rows = _helpers._full_perm_rows_for_user(selected_user_id)
                module_rows = _helpers._aggregate_to_module_rows(raw_rows)
                perm_detail = _build_perm_detail(raw_rows)
            except DatabaseError as exc:
                messages.error(request, f"Errore lettura permessi: {exc}")
    else:
        target_type = "role"
        if selected_role_id is None and roles:
            selected_role_id = int(roles[0].id)
        try:
            if selected_role_id is not None:
                raw_rows = _helpers._permission_rows_for_role(selected_role_id)
                module_rows = _helpers._aggregate_to_module_rows(raw_rows)
                perm_detail = _build_perm_detail(raw_rows)
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi: {exc}")

    return render(
        request,
        "admin_portale/pages/permessi.html",
        {
            "roles": roles,
            "users": users,
            "target_type": target_type,
            "selected_role_id": selected_role_id,
            "selected_user_id": selected_user_id,
            "selected_user": selected_user,
            "module_rows": module_rows,
            "perm_detail": perm_detail,
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_role_module_set(request):
    """POST {role_id, module, value}  — abilita/disabilita tutti i permessi di un modulo per un ruolo."""
    payload = _helpers._json_payload(request)
    role_id = _helpers._int_or_none(payload.get("role_id") or payload.get("ruolo_id"))
    module = str(payload.get("module") or "").strip().lower()
    value = _helpers._bool_from_any(payload.get("value"))
    if role_id is None or not module:
        return _helpers._json_error("Parametri non validi.")
    permissions = list(PermissionDefinition.objects.filter(is_active=True, module__iexact=module))
    if not permissions:
        return _helpers._json_error(f"Nessun permesso trovato per modulo '{module}'.", status=404)
    try:
        with transaction.atomic():
            for perm in permissions:
                RolePermissionGrant.objects.update_or_create(
                    legacy_role_id=int(role_id),
                    permission_id=perm.code,
                    defaults={"enabled": value},
                )
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": len(permissions), "module": module, "value": value})


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_user_grant_toggle(request, user_id: int):
    """POST {permission_code, state}  state: 'allow'|'deny'|'inherit'"""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    permission_code = normalize_permission_code(str(payload.get("permission_code") or ""))
    state = str(payload.get("state") or "inherit").strip().lower()
    is_valid, err = validate_permission_code(permission_code)
    if not is_valid:
        return _helpers._json_error(err or "Permission code non valido.")
    if state not in {"allow", "deny", "inherit"}:
        return _helpers._json_error("State non valido. Valori: allow, deny, inherit.")
    if not PermissionDefinition.objects.filter(code=permission_code).exists():
        return _helpers._json_error(f"Permission code non trovato: {permission_code}.", status=404)
    try:
        with transaction.atomic():
            if state == "inherit":
                UserPermissionGrant.objects.filter(legacy_user_id=user_id, permission_id=permission_code).delete()
            else:
                UserPermissionGrant.objects.update_or_create(
                    legacy_user_id=user_id,
                    permission_id=permission_code,
                    defaults={"enabled": state == "allow"},
                )
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "state": state, "permission_code": permission_code, "user_id": user_id})


@legacy_admin_required
@csrf_protect
@require_POST
def api_acl_v2_user_module_set(request, user_id: int):
    """POST {module, state}  state: 'allow'|'deny'|'inherit'"""
    utente = get_object_or_404(UtenteLegacy, id=user_id)
    payload = _helpers._json_payload(request)
    module = str(payload.get("module") or "").strip().lower()
    state = str(payload.get("state") or "inherit").strip().lower()
    if not module:
        return _helpers._json_error("Modulo non valido.")
    if state not in {"allow", "deny", "inherit"}:
        return _helpers._json_error("State non valido. Valori: allow, deny, inherit.")
    permissions = list(PermissionDefinition.objects.filter(is_active=True, module__iexact=module))
    if not permissions:
        return _helpers._json_error(f"Nessun permesso trovato per modulo '{module}'.", status=404)
    try:
        with transaction.atomic():
            for perm in permissions:
                if state == "inherit":
                    UserPermissionGrant.objects.filter(legacy_user_id=user_id, permission_id=perm.code).delete()
                else:
                    UserPermissionGrant.objects.update_or_create(
                        legacy_user_id=user_id,
                        permission_id=perm.code,
                        defaults={"enabled": state == "allow"},
                    )
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "state": state, "module": module, "user_id": user_id})


# ---------------------------------------------------------------------------
# PERMESSI â€” toggle modulo intero per ruolo o per utente
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
@require_POST
def api_permessi_modulo_set(request):
    """Imposta can_view per TUTTI i pulsanti di un modulo per un ruolo.
    Payload: {ruolo_id, modulo, can_view}
    """
    payload = _helpers._json_payload(request)
    ruolo_id = _helpers._int_or_none(payload.get("ruolo_id"))
    modulo = str(payload.get("modulo") or "").strip()
    can_view = _helpers._bool_from_any(payload.get("can_view"))
    if ruolo_id is None or not modulo:
        return _helpers._json_error("Parametri non validi.")
    blocked = _helpers._canonical_module_write_block(modulo)
    if blocked is not None:
        return blocked
    acl_keys = [(m, a) for m, a in _helpers._pulsanti_acl_keys() if m.lower() == modulo.lower()]
    if not acl_keys:
        return _helpers._json_error("Nessun pulsante trovato per il modulo indicato.", status=404)
    try:
        with transaction.atomic():
            affected = 0
            for mod, azione in acl_keys:
                perm = _helpers._get_or_create_permesso(ruolo_id, mod, azione)
                perm.can_view = 1 if can_view else 0
                update_fields = ["can_view"]
                if hasattr(perm, "consentito"):
                    perm.consentito = perm.can_view
                    update_fields.append("consentito")
                perm.save(update_fields=update_fields)
                affected += 1
            _helpers._schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "affected": affected})


# ---------------------------------------------------------------------------
# Dashboard Gestione Accessi
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def accessi_dashboard(request):
    """Dashboard unica: ruoli con conteggi, pulsanti, override utenti recenti."""
    ruoli_info = []
    pulsanti_count = 0
    override_count = 0
    override_recenti = []

    try:
        ruoli = list(Ruolo.objects.all().order_by("nome"))
        pulsanti_count = Pulsante.objects.count()
        for r in ruoli:
            cnt = Permesso.objects.filter(ruolo_id=r.id, can_view=1).count()
            tot = Permesso.objects.filter(ruolo_id=r.id).count()
            ruoli_info.append({"ruolo": r, "perm_attivi": cnt, "perm_totali": tot})
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura tabelle legacy: {exc}")

    try:
        override_count = UserPermissionOverride.objects.count()
        override_recenti = list(
            UserPermissionOverride.objects.order_by("-id")[:15]
        )
        # Arricchisci con nome utente
        uid_set = {o.legacy_user_id for o in override_recenti}
        utenti_map = {}
        try:
            for u in UtenteLegacy.objects.filter(id__in=uid_set):
                utenti_map[int(u.id)] = u.nome or str(u.id)
        except DatabaseError:
            pass
        for o in override_recenti:
            o.nome_utente = utenti_map.get(int(o.legacy_user_id), f"ID {o.legacy_user_id}")
    except Exception as exc:
        messages.warning(request, f"Errore lettura override: {exc}")

    return render(request, "admin_portale/pages/accessi.html", {
        "page_title": "Accessi Avanzati",
        "ruoli_info": ruoli_info,
        "pulsanti_count": pulsanti_count,
        "override_count": override_count,
        "override_recenti": override_recenti,
    })


@legacy_admin_required
@csrf_protect
def accessi_semplice(request):
    """Vista per modulo dei grant canonici di un ruolo. SOLA LETTURA.

    Concedeva per modulo intero, senza granularita' di pagina: si concede da
    ``accessi_unificati``, qui resta la lettura d'insieme.
    """
    if request.method == "POST":
        # Il salvataggio vive nel pannello unico: questi due pannelli restano
        # consultabili (mostrano il layer legacy e la vista per modulo) ma non
        # possono piu' creare stati che contraddicono i grant canonici.
        messages.warning(
            request,
            "Questa pagina e' in sola lettura: i permessi si concedono da Accessi, "
            "che scrive il layer canonico.",
        )
        return redirect(reverse("admin_portale:accessi"))

    roles = _helpers._role_choices()
    selected_role_id = _helpers._int_or_none(request.GET.get("ruolo_id") or request.POST.get("ruolo_id"))
    if selected_role_id is None and roles:
        selected_role_id = int(roles[0].id)

    module_rows = _build_accessi_semplice_rows(selected_role_id)
    selected_role = None
    if selected_role_id is not None:
        selected_role = next((r for r in roles if int(r.id) == int(selected_role_id)), None)

    return render(
        request,
        "admin_portale/pages/accessi_semplice.html",
        {
            "page_title": "Accessi Semplificati",
            "roles": roles,
            "selected_role_id": selected_role_id,
            "selected_role": selected_role,
            "module_rows": module_rows,
        },
    )


# ---------------------------------------------------------------------------
# Gestione Accessi â€” pagina unificata (ruolo + moduli + pulsanti + flag)
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
def gestione_accessi(request):
    """Vista dei permessi LEGACY (tabella ``permessi``) di un ruolo. SOLA LETTURA.

    Scriveva un layer che il portale ignora appena esiste un grant canonico: era
    la ragione per cui una spunta qui poteva non avere alcun effetto. Resta come
    lettura dello stato legacy durante la migrazione.
    """
    if request.method == "POST":
        # Il salvataggio vive nel pannello unico: questi due pannelli restano
        # consultabili (mostrano il layer legacy e la vista per modulo) ma non
        # possono piu' creare stati che contraddicono i grant canonici.
        messages.warning(
            request,
            "Questa pagina e' in sola lettura: i permessi si concedono da Accessi, "
            "che scrive il layer canonico.",
        )
        return redirect(reverse("admin_portale:accessi"))

    roles = _helpers._role_choices()
    selected_role_id = _helpers._int_or_none(request.GET.get("ruolo_id") or request.POST.get("ruolo_id"))
    if selected_role_id is None and roles:
        selected_role_id = int(roles[0].id)

    # GET â€” costruisce i dati per il template
    module_data: list[dict] = []
    selected_role = None
    total_active = 0
    total_pulsanti = 0

    if selected_role_id is not None:
        selected_role = next((r for r in roles if int(r.id) == selected_role_id), None)
        try:
            module_data = _build_gestione_accessi_data(selected_role_id)
            for mod in module_data:
                total_active += mod["active_count"]
                total_pulsanti += mod["total_count"]
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura permessi: {exc}")

    optional_fields = [f for f in _helpers.PERM_OPTIONAL_FIELDS if legacy_table_has_column("permessi", f)]

    return render(
        request,
        "admin_portale/pages/gestione_accessi.html",
        {
            "roles": roles,
            "selected_role_id": selected_role_id,
            "selected_role": selected_role,
            "module_data": module_data,
            "total_active": total_active,
            "total_pulsanti": total_pulsanti,
            "optional_fields": optional_fields,
        },
    )


# ---------------------------------------------------------------------------
# Matrice Permessi â€” vista ruoli Ã— pulsanti per modulo
# ---------------------------------------------------------------------------

@legacy_admin_required
@csrf_protect
def matrice_permessi(request):
    """Matrice permessi: righe = pulsanti del modulo, colonne = tutti i ruoli.
    Permette di abilitare/disabilitare can_view per ogni cella con un solo POST.
    """
    roles = _helpers._role_choices()
    try:
        modules = sorted(
            {(p.modulo or "").strip() for p in Pulsante.objects.all() if (p.modulo or "").strip()},
            key=str.lower,
        )
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura moduli: {exc}")
        modules = []

    selected_module = (request.GET.get("modulo") or request.POST.get("modulo") or "").strip()
    if not selected_module and modules:
        selected_module = modules[0]

    if request.method == "POST":
        if not selected_module:
            messages.error(request, "Seleziona un modulo prima di salvare.")
            return redirect(reverse("admin_portale:matrice_permessi"))

        try:
            pulsanti_modulo = list(
                Pulsante.objects.filter(modulo__iexact=selected_module).order_by("codice")
            )
            with transaction.atomic():
                saved = 0
                for pulsante in pulsanti_modulo:
                    azione = (pulsante.codice or "").strip()
                    modulo = (pulsante.modulo or "").strip()
                    if not azione or not modulo:
                        continue
                    for role in roles:
                        field_name = f"perm_{int(role.id)}_{azione}"
                        can_view = field_name in request.POST
                        perm = _helpers._get_or_create_permesso(int(role.id), modulo, azione)
                        new_val = 1 if can_view else 0
                        if int(perm.can_view or 0) != new_val or int(perm.consentito or 0) != new_val:
                            perm.can_view = new_val
                            perm.consentito = new_val
                            perm.save(update_fields=["can_view", "consentito"])
                            saved += 1
                if saved:
                    _helpers._schedule_legacy_acl_cache_invalidation()
            messages.success(request, f"Matrice salvata. {saved} permessi aggiornati.")
        except DatabaseError as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")

        return redirect(f"{reverse('admin_portale:matrice_permessi')}?modulo={selected_module}")

    # Costruisce la matrice per il modulo selezionato.
    # pulsante_rows = [{"pulsante": Pulsante, "cells": [{"role": Ruolo, "can_view": bool}]}]
    pulsante_rows: list[dict] = []

    if selected_module:
        try:
            pulsanti_modulo = list(
                Pulsante.objects.filter(modulo__iexact=selected_module).order_by("codice")
            )
            # Carica tutti i permessi per il modulo in una query sola
            perms = Permesso.objects.filter(modulo__iexact=selected_module)
            perm_index: dict[tuple[str, int], bool] = {}
            for p in perms:
                key = ((p.azione or "").strip().lower(), int(p.ruolo_id or 0))
                can = bool(p.can_view) or bool(p.consentito)
                perm_index[key] = perm_index.get(key, False) or can

            for pulsante in pulsanti_modulo:
                azione = (pulsante.codice or "").strip()
                if not azione:
                    continue
                cells = [
                    {
                        "role": role,
                        "field_name": f"perm_{int(role.id)}_{azione}",
                        "can_view": perm_index.get((azione.lower(), int(role.id)), False),
                    }
                    for role in roles
                ]
                pulsante_rows.append({"pulsante": pulsante, "cells": cells})
        except DatabaseError as exc:
            messages.error(request, f"Errore lettura matrice: {exc}")

    return render(
        request,
        "admin_portale/pages/matrice_permessi.html",
        {
            "modules": modules,
            "selected_module": selected_module,
            "roles": roles,
            "pulsante_rows": pulsante_rows,
        },
    )


# ---------------------------------------------------------------------------
# Gestione Ruoli (CRUD)
# ---------------------------------------------------------------------------

@legacy_admin_required
def ruoli_list(request):
    """Lista ruoli con conteggio utenti. POST crea un nuovo ruolo."""
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        if not nome:
            messages.error(request, "Il nome del ruolo è obbligatorio.")
            return redirect(reverse("admin_portale:ruoli_list"))
        try:
            if Ruolo.objects.filter(nome__iexact=nome).exists():
                messages.error(request, f"Esiste già un ruolo con nome «{nome}».")
                return redirect(reverse("admin_portale:ruoli_list"))
            ruolo = Ruolo.objects.create(nome=nome)
            bump_legacy_cache_version()
            log_action(request, "crea_ruolo", "admin_portale", f"Ruolo creato: {nome} (id={ruolo.id})")
            messages.success(request, f"Ruolo «{nome}» creato con successo.")
        except DatabaseError as exc:
            messages.error(request, f"Errore database: {exc}")
        return redirect(reverse("admin_portale:ruoli_list"))

    ruoli = []
    user_counts: dict[int, int] = {}
    try:
        ruoli = list(Ruolo.objects.all().order_by("id"))
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura ruoli: {exc}")
    try:
        from django.db.models import Count as _Count
        for row in UtenteLegacy.objects.values("ruolo_id").annotate(n=_Count("id")):
            if row["ruolo_id"] is not None:
                user_counts[int(row["ruolo_id"])] = row["n"]
    except DatabaseError:
        pass
    for r in ruoli:
        r.user_count = user_counts.get(int(r.id), 0)

    return render(request, "admin_portale/pages/ruoli_list.html", {
        "ruoli": ruoli,
        "page_title": "Gestione Ruoli",
    })


@legacy_admin_required
@require_POST
def ruolo_update(request, ruolo_id: int):
    """Aggiorna il nome di un ruolo e sincronizza la colonna stringa utenti.ruolo."""
    try:
        ruolo = Ruolo.objects.get(pk=ruolo_id)
    except Ruolo.DoesNotExist:
        messages.error(request, "Ruolo non trovato.")
        return redirect(reverse("admin_portale:ruoli_list"))
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome non può essere vuoto.")
        return redirect(reverse("admin_portale:ruoli_list"))
    try:
        if Ruolo.objects.filter(nome__iexact=nome).exclude(pk=ruolo_id).exists():
            messages.error(request, f"Esiste già un ruolo con nome «{nome}».")
            return redirect(reverse("admin_portale:ruoli_list"))
        old_nome = ruolo.nome
        ruolo.nome = nome
        ruolo.save(update_fields=["nome"])
        UtenteLegacy.objects.filter(ruolo_id=ruolo_id).update(ruolo=nome)
        bump_legacy_cache_version()
        log_action(request, "modifica_ruolo", "admin_portale", f"Ruolo {ruolo_id}: '{old_nome}' → '{nome}'")
        messages.success(request, f"Ruolo aggiornato: «{nome}».")
    except DatabaseError as exc:
        messages.error(request, f"Errore database: {exc}")
    return redirect(reverse("admin_portale:ruoli_list"))


@legacy_admin_required
@require_POST
def ruolo_delete(request, ruolo_id: int):
    """Elimina ruolo solo se non ha utenti assegnati. Rimuove anche i permessi collegati."""
    try:
        ruolo = Ruolo.objects.get(pk=ruolo_id)
    except Ruolo.DoesNotExist:
        messages.error(request, "Ruolo non trovato.")
        return redirect(reverse("admin_portale:ruoli_list"))
    try:
        user_count = UtenteLegacy.objects.filter(ruolo_id=ruolo_id).count()
        if user_count > 0:
            messages.error(
                request,
                f"Impossibile eliminare «{ruolo.nome}»: {user_count} utent{'e' if user_count == 1 else 'i'} "
                f"{'è assegnato' if user_count == 1 else 'sono assegnati'} a questo ruolo.",
            )
            return redirect(reverse("admin_portale:ruoli_list"))
        nome = ruolo.nome
        Permesso.objects.filter(ruolo_id=ruolo_id).delete()
        ruolo.delete()
        bump_legacy_cache_version()
        log_action(request, "elimina_ruolo", "admin_portale", f"Ruolo eliminato: {nome} (id={ruolo_id})")
        messages.success(request, f"Ruolo «{nome}» eliminato.")
    except DatabaseError as exc:
        messages.error(request, f"Errore database: {exc}")
    return redirect(reverse("admin_portale:ruoli_list"))


@legacy_admin_required
@require_POST
def api_ruolo_create(request):
    """API JSON — crea un nuovo ruolo (usato dal wizard inline)."""
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        return JsonResponse({"ok": False, "error": "Nome obbligatorio."}, status=400)
    try:
        if Ruolo.objects.filter(nome__iexact=nome).exists():
            return JsonResponse({"ok": False, "error": f"Esiste già un ruolo con nome «{nome}»."}, status=400)
        ruolo = Ruolo.objects.create(nome=nome)
        bump_legacy_cache_version()
        log_action(request, "crea_ruolo", "admin_portale", f"Ruolo creato via wizard: {nome} (id={ruolo.id})")
        return JsonResponse({"ok": True, "ruolo": {"id": ruolo.id, "nome": ruolo.nome}})
    except DatabaseError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Wizard Configura Ruolo
# ---------------------------------------------------------------------------

@legacy_admin_required
@require_GET
def wizard_ruolo(request):
    """Wizard step-by-step per configurare i permessi di un ruolo."""
    ruoli = []
    moduli_pulsanti: dict[str, list] = {}
    perm_map_json = "{}"
    ruolo_id_presel = request.GET.get("ruolo_id", "")

    try:
        ruoli = list(Ruolo.objects.all().order_by("nome"))
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura ruoli: {exc}")

    try:
        for p in Pulsante.objects.order_by("modulo", "nome_visibile"):
            mod = (p.modulo or "").strip() or "altro"
            moduli_pulsanti.setdefault(mod, []).append(p)
    except DatabaseError as exc:
        messages.error(request, f"Errore lettura pulsanti: {exc}")

    # Carica permessi attuali per il ruolo pre-selezionato
    if ruolo_id_presel:
        try:
            rid = int(ruolo_id_presel)
            perm_map: dict[str, dict] = {}
            for p in Permesso.objects.filter(ruolo_id=rid):
                key = f"{p.modulo}__{p.azione}"
                perm_map[key] = {
                    "can_view": int(p.can_view or 0),
                    "can_edit": int(p.can_edit or 0),
                    "can_delete": int(p.can_delete or 0),
                    "can_approve": int(p.can_approve or 0),
                }
            perm_map_json = json.dumps(perm_map)
        except (DatabaseError, ValueError) as exc:
            messages.warning(request, f"Errore caricamento permessi ruolo: {exc}")

    return render(request, "admin_portale/pages/wizard_ruolo.html", {
        "page_title": "Wizard Configura Ruolo",
        "ruoli": ruoli,
        "moduli_pulsanti": moduli_pulsanti,
        "perm_map_json": perm_map_json,
        "ruolo_id_presel": ruolo_id_presel,
        "api_bulk_url": reverse("admin_portale:api_permessi_bulk"),
        "api_perm_ruolo_url": reverse("admin_portale:api_wizard_permessi_ruolo"),
        "accessi_url": reverse("admin_portale:gestione_accessi"),
    })


@legacy_admin_required
@require_GET
def api_wizard_permessi_ruolo(request):
    """Ritorna la perm_map JSON per un ruolo (usato dal wizard AJAX)."""
    ruolo_id = request.GET.get("ruolo_id", "")
    if not ruolo_id:
        return JsonResponse({"ok": False, "error": "ruolo_id required"}, status=400)
    try:
        rid = int(ruolo_id)
        perm_map: dict[str, dict] = {}
        for p in Permesso.objects.filter(ruolo_id=rid):
            key = f"{p.modulo}__{p.azione}"
            perm_map[key] = {
                "can_view": int(p.can_view or 0),
                "can_edit": int(p.can_edit or 0),
                "can_delete": int(p.can_delete or 0),
                "can_approve": int(p.can_approve or 0),
            }
        return JsonResponse({"ok": True, "perm_map": perm_map})
    except (DatabaseError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Accessi - pannello unico: gruppi e ruoli, un solo layer (canonico)
# ---------------------------------------------------------------------------

SUBJECT_GROUP = "group"
SUBJECT_ROLE = "role"


def _parse_subject(raw: str) -> tuple[str, int | None]:
    """"group:3" / "role:2" -> ("group", 3). Stringa vuota se non riconosciuto."""
    value = str(raw or "").strip().lower()
    if ":" not in value:
        return "", None
    kind, _sep, ident = value.partition(":")
    if kind not in (SUBJECT_GROUP, SUBJECT_ROLE):
        return "", None
    return kind, _helpers._int_or_none(ident)


# Quante rotte elencare nel tooltip di un permesso: oltre, il riquadro diventa
# illeggibile e il numero totale basta a dire "governa mezzo modulo".
ACCESSI_ROUTES_PREVIEW = 12

LINK_PAGES = "pagine"
LINK_MENU = "menu"
LINK_SECTION = "sezione"
LINK_SHADOWED = "oscurato"
LINK_STATUSES = (LINK_PAGES, LINK_MENU, LINK_SECTION, LINK_SHADOWED)


def _accessi_menu_codes() -> set[str]:
    """Permessi richiesti esplicitamente da una voce di menu (topbar, sidebar)."""
    try:
        return {
            str(code).strip().lower()
            for code in NavigationItem.objects.exclude(required_permission_code="").values_list(
                "required_permission_code", flat=True
            )
            if str(code or "").strip()
        }
    except DatabaseError:
        return set()


def _accessi_link_status(code: str, capabilities, menu_codes: set[str] | frozenset = frozenset()) -> tuple[str, list[str]]:
    """Che cosa collega il permesso: rotte vere, voci di menu, sezioni o nulla.

    ``pagine``: il resolver lo sceglie per almeno una rotta con nome.
    ``menu``: nessuna rotta lo sceglie, ma una voce di menu lo richiede: decide
    cosa si vede nella navigazione (che non e' un confine di sicurezza).
    ``sezione``: nessun binding, lo verifica il codice dentro una pagina.
    ``oscurato``: ha binding attivi ma nessuna rotta lo sceglie mai e nessun
    menu lo richiede: i binding puntano a rotte sparite o uno piu' specifico li
    scavalca. Concesso da solo non apre pagine: e' cio' che la verifica dei
    collegamenti deve far vedere.
    """
    routes = list(capabilities.governed_routes.get(code, []))
    if routes:
        return LINK_PAGES, routes
    if code.lower() in menu_codes:
        return LINK_MENU, []
    if code in capabilities.bound_codes:
        return LINK_SHADOWED, []
    return LINK_SECTION, []


def _accessi_permission_rows(*, kind: str, subject_id: int | None, capabilities=None) -> list[dict]:
    """Permessi canonici per modulo, con lo stato del soggetto selezionato.

    Le righe sono i permessi, non i pulsanti legacy: e' il layer su cui il
    portale decide davvero. Ogni riga dice anche che cosa il permesso collega
    davvero: le rotte che governa, nessuna (controllo di sezione) o binding che
    non decidono piu' nulla.

    I moduli sono quelli di pagina (``core.permission_categories``), ordinati
    per area; dentro il modulo i permessi sono divisi per natura e categoria.
    Sono raggruppamenti di presentazione: la lista completa resta in
    ``permissions`` e si salva sempre un grant per code.
    """
    permissions = list(PermissionDefinition.objects.filter(is_active=True).order_by("module", "code"))
    if not permissions:
        return []

    granted: dict[str, bool] = {}
    from_matrix: set[str] = set()
    if kind == SUBJECT_GROUP and subject_id:
        from core.permessi.sync import NOTA_MATRICE

        for row in GroupPermissionGrant.objects.filter(group_id=subject_id):
            granted[str(row.permission_id)] = bool(row.enabled)
            if row.note == NOTA_MATRICE:
                from_matrix.add(str(row.permission_id))
    elif kind == SUBJECT_ROLE and subject_id:
        granted = {
            str(row.permission_id): bool(row.enabled)
            for row in RolePermissionGrant.objects.filter(legacy_role_id=subject_id)
        }

    # La capacita' non si legge dal solo nome: un permesso legato a un prefisso
    # di URL governa anche le rotte che gli stanno sotto, e quelle possono
    # scrivere. Lo stesso indice dice quali rotte ogni permesso governa davvero.
    # Vedi core/acl_capability.py.
    if capabilities is None:
        capabilities = capability_index()
    menu_codes = _accessi_menu_codes()

    grouped: dict[str, list[dict]] = {}
    for permission in permissions:
        module = (permission.module or "senza modulo").strip().lower()
        target = display_module(permission.code, module)
        capability = capabilities.capabilities.get(permission.code) or capability_for_code(
            permission.code, module
        )
        category, category_label = category_for(permission.code, module)
        link_status, routes = _accessi_link_status(permission.code, capabilities, menu_codes)
        grouped.setdefault(target, []).append(
            {
                "code": permission.code,
                "label": readable_label(permission.code, module, permission.label),
                "stored_label": permission.label,
                "description": permission.description,
                "enabled": bool(granted.get(permission.code, False)),
                # Acceso dalla matrice dei ruoli: spegnerlo qui vale fino al
                # prossimo salvataggio della matrice di quel ruolo.
                "from_matrix": permission.code in from_matrix,
                "governs_route": link_status == LINK_PAGES,
                "link_status": link_status,
                "route_count": len(routes),
                "routes_preview": routes[:ACCESSI_ROUTES_PREVIEW],
                "routes_title": "\n".join(routes[:ACCESSI_ROUTES_PREVIEW])
                + (
                    f"\n… e altre {len(routes) - ACCESSI_ROUTES_PREVIEW}"
                    if len(routes) > ACCESSI_ROUTES_PREVIEW
                    else ""
                ),
                # Il modulo a database, quando la pagina lo mostra in un altro
                # banco (es. `admin_portale.automazioni_*` sotto Automazioni).
                "source_module": module if module != target else "",
                "nature": nature_for_code(permission.code, module),
                "submodule": category,
                "submodule_label": category_label,
                "capability": capability,
                "capability_label": capability_label(capability),
                "capability_unknown": capability == CAPABILITY_IGNOTO,
                # Governa un sottoalbero di URL: la capacita' puo' essere stata
                # alzata da cio' che ci sta sotto, non dal suo nome.
                "governs_subtree": permission.code in capabilities.subtree_routes,
            }
        )

    rows: list[dict] = []
    for module, entries in grouped.items():
        order = category_order(module)
        active = sum(1 for entry in entries if entry["enabled"])
        entries.sort(key=lambda entry: (order.get(entry["submodule"], len(order)), entry["label"].lower(), entry["code"]))
        gruppi: list[dict] = []
        for nature in NATURE_ORDER:
            subset = [entry for entry in entries if entry["nature"] == nature]
            if not subset:
                continue
            submodules: dict[str, list[dict]] = {}
            for entry in subset:
                submodules.setdefault(entry["submodule"], []).append(entry)
            gruppi.append(
                {
                    "nature": nature,
                    "label": nature_label(nature),
                    "permissions": subset,
                    "submodules": [
                        {
                            "key": key,
                            "label": members[0]["submodule_label"],
                            "permissions": members,
                            "total_count": len(members),
                            "active_count": sum(1 for row in members if row["enabled"]),
                            "pages_count": sum(row["route_count"] for row in members),
                            "shadowed_count": sum(1 for row in members if row["link_status"] == LINK_SHADOWED),
                        }
                        for key, members in sorted(
                            submodules.items(), key=lambda pair: order.get(pair[0], len(order))
                        )
                    ],
                    "total_count": len(subset),
                    "active_count": sum(1 for entry in subset if entry["enabled"]),
                }
            )
        area = area_for_module(module)
        rows.append(
            {
                "modulo": module,
                "label": module_label(module),
                "area": area,
                "area_label": area_label(area),
                "permissions": entries,
                "gruppi": gruppi,
                "categories_count": len({entry["submodule"] for entry in entries}),
                "total_count": len(entries),
                "active_count": active,
                "all_on": bool(entries) and active == len(entries),
                "partial": 0 < active < len(entries),
            }
        )
    area_rank = {area: _helpers.index for _helpers.index, area in enumerate(AREA_ORDER)}
    rows.sort(key=lambda row: (area_rank.get(row["area"], len(area_rank)), row["label"].lower()))
    return rows


def _accessi_link_summary(module_rows: list[dict], capabilities) -> dict:
    """Verifica dei collegamenti ACL: i numeri che dicono se la mappa e' sana.

    Calcolata dallo stesso indice che il resolver usa per scegliere i binding,
    quindi descrive cio' che succede davvero, non cio' che e' scritto a
    database. I binding "morti" sono elencati uno per uno: sono quelli da
    correggere o disattivare in ACL canonico.
    """
    entries = [entry for row in module_rows for entry in row["permissions"]]
    by_status = {status: 0 for status in LINK_STATUSES}
    for entry in entries:
        by_status[entry["link_status"]] = by_status.get(entry["link_status"], 0) + 1
    stale = list(capabilities.stale_bindings)
    return {
        "permissions": len(entries),
        "with_pages": by_status[LINK_PAGES],
        "menu_only": by_status[LINK_MENU],
        "section_only": by_status[LINK_SECTION],
        "shadowed": by_status[LINK_SHADOWED],
        "shadowed_codes": sorted(entry["code"] for entry in entries if entry["link_status"] == LINK_SHADOWED),
        "routes_total": capabilities.routes_total,
        "routes_bound": capabilities.routes_bound,
        "stale_bindings": stale,
        "stale_missing_route": sum(1 for row in stale if row["reason"] == STALE_MISSING_ROUTE),
        "stale_shadowed": sum(1 for row in stale if row["reason"] == STALE_SHADOWED),
        "modules": len(module_rows),
        "categories": sum(row["categories_count"] for row in module_rows),
    }


def _group_members(group) -> list[dict]:
    memberships = list(AccessGroupMembership.objects.filter(group=group).order_by("legacy_user_id"))
    if not memberships:
        return []
    users = {
        int(u.id): u
        for u in UtenteLegacy.objects.filter(id__in=[m.legacy_user_id for m in memberships])
    }
    members = []
    for membership in memberships:
        legacy_user = users.get(int(membership.legacy_user_id))
        members.append(
            {
                "membership_id": int(membership.id),
                "legacy_user_id": int(membership.legacy_user_id),
                "nome": getattr(legacy_user, "nome", "") or f"ID {membership.legacy_user_id}",
                "email": getattr(legacy_user, "email", "") or "",
                "orfano": legacy_user is None,
            }
        )
    return members


@legacy_admin_required
@csrf_protect
def accessi_unificati(request):
    """Un solo posto per concedere accessi, e un solo layer su cui scrive.

    Storia del perche': "Gestione Accessi" scriveva la tabella legacy
    ``permessi``, ignorata appena esiste un grant canonico; "Accessi
    Semplificati" scriveva i grant canonici ma per modulo intero. La stessa
    spunta poteva quindi funzionare o non funzionare a seconda della pagina.
    Qui si scrivono solo grant canonici, per singolo permesso.
    """
    if request.method == "GET" and request.GET.get("guida") == "1":
        # Stessa rotta (stesso permesso) della pagina: la guida non apre un varco.
        return render(
            request,
            "admin_portale/pages/accessi_guida.html",
            {"page_title": "Guida Accessi", "subject": str(request.GET.get("subject") or "")[:40]},
        )
    groups =list(AccessGroup.objects.all().order_by("-priority", "label", "id"))
    try:
        roles = list(Ruolo.objects.all().order_by("nome"))
    except DatabaseError:
        roles = []

    raw_subject = request.POST.get("subject") or request.GET.get("subject") or ""
    kind, subject_id = _parse_subject(raw_subject)
    if not kind and groups:
        kind, subject_id = SUBJECT_GROUP, int(groups[0].id)
    elif not kind and roles:
        kind, subject_id = SUBJECT_ROLE, int(roles[0].id)

    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        current_subject = f"{kind}:{subject_id}" if kind and subject_id else ""
        redirect_subject = current_subject
        try:
            if action == "group_create":
                redirect_subject = _accessi_group_create(request)
            elif action == "group_update":
                _accessi_group_update(request)
            elif action == "member_add":
                _accessi_member_add(request)
            elif action == "member_remove":
                _accessi_member_remove(request)
            elif action == "save_grants":
                _accessi_save_grants(request, kind=kind, subject_id=subject_id)
            else:
                messages.warning(request, "Azione non riconosciuta.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        except DatabaseError as exc:
            messages.error(request, f"Errore durante il salvataggio: {exc}")
        else:
            bump_legacy_cache_version()
        return redirect(f"{reverse('admin_portale:accessi')}?subject={redirect_subject or current_subject}")

    capabilities = capability_index()
    module_rows = _accessi_permission_rows(kind=kind, subject_id=subject_id, capabilities=capabilities)
    selected_group = None
    selected_role = None
    if kind == SUBJECT_GROUP and subject_id:
        selected_group = next((g for g in groups if int(g.id) == int(subject_id)), None)
    elif kind == SUBJECT_ROLE and subject_id:
        selected_role = next((r for r in roles if int(r.id) == int(subject_id)), None)

    return render(
        request,
        "admin_portale/pages/accessi_unificati.html",
        {
            "page_title": "Accessi",
            "groups": groups,
            "roles": roles,
            "subject_kind": kind,
            "subject_id": subject_id,
            "subject_value": f"{kind}:{subject_id}" if kind and subject_id else "",
            "selected_group": selected_group,
            "selected_role": selected_role,
            "members": _group_members(selected_group) if selected_group else [],
            "module_rows": module_rows,
            "link_summary": _accessi_link_summary(module_rows, capabilities),
            "total_active": sum(row["active_count"] for row in module_rows),
            "total_permissions": sum(row["total_count"] for row in module_rows),
            # I livelli sono macro di selezione lato pagina: accendono gli
            # interruttori giusti, poi si salva come sempre un grant per
            # permesso. Nessuno stato "livello" viene mai scritto a database.
            "access_levels": [
                {
                    "key": level["key"],
                    "label": level["label"],
                    "description": level["description"],
                    "capabilities": sorted(level["capabilities"]),
                }
                for level in ACCESS_LEVELS
            ],
            "preset_modulo": _preset_modulo_per_pagina(),
        },
    )


def _preset_modulo_per_pagina() -> dict[str, list[dict]]:
    """modulo -> preset salvati, per il menu «Livello» della pagina Accessi."""
    from core.models import PresetPermessiModulo

    risultato: dict[str, list[dict]] = {}
    try:
        for preset in PresetPermessiModulo.objects.all():
            risultato.setdefault(preset.modulo, []).append(
                {"id": preset.id, "nome": preset.nome, "descrizione": preset.descrizione, "codici": preset.codici}
            )
    except DatabaseError:
        return {}
    return risultato


@legacy_admin_required
@csrf_protect
@require_POST
def accessi_preset(request):
    """Salva o elimina un preset di permessi di un modulo (risposta JSON).

    Il preset e' solo un elenco di permessi con un nome: non concede nulla da
    solo. Applicarlo muove gli interruttori; i grant si scrivono col «Salva» di
    sempre. Ogni creazione/modifica/eliminazione va in AuditLog.
    """
    from core.models import PresetPermessiModulo

    azione = str(request.POST.get("azione") or "").strip()
    modulo = str(request.POST.get("modulo") or "").strip().lower()[:80]
    if azione == "elimina":
        preset = PresetPermessiModulo.objects.filter(id=_safe_int_or_none(request.POST.get("id")), modulo=modulo).first()
        if preset is None:
            return JsonResponse({"ok": False, "errore": "Preset non trovato."}, status=404)
        nome = preset.nome
        preset.delete()
        log_action(request, "accessi_preset_elimina", "permessi", {"modulo": modulo, "nome": nome})
        return JsonResponse({"ok": True})
    if azione != "salva":
        return JsonResponse({"ok": False, "errore": "Azione non riconosciuta."}, status=400)

    nome = " ".join(str(request.POST.get("nome") or "").split())[:80]
    if not modulo or not nome:
        return JsonResponse({"ok": False, "errore": "Servono il nome del preset e il modulo."}, status=400)
    try:
        richiesti = json.loads(request.POST.get("codici") or "[]")
    except ValueError:
        return JsonResponse({"ok": False, "errore": "Selezione non leggibile."}, status=400)
    if not isinstance(richiesti, list):
        return JsonResponse({"ok": False, "errore": "Selezione non leggibile."}, status=400)
    # Solo permessi attivi del modulo: un codice inventato non entra nel preset.
    validi = set(
        PermissionDefinition.objects.filter(is_active=True, code__in=[str(c) for c in richiesti]).values_list("code", flat=True)
    )
    codici = sorted(validi)
    if not codici:
        return JsonResponse({"ok": False, "errore": "Accendi almeno un permesso del modulo prima di salvare il preset."}, status=400)
    descrizione = " ".join(str(request.POST.get("descrizione") or "").split())[:300]
    preset, creato = PresetPermessiModulo.objects.update_or_create(
        modulo=modulo,
        nome=nome,
        defaults={
            "descrizione": descrizione,
            "codici_json": json.dumps(codici),
            "creato_da": str(getattr(request.user, "username", "") or "")[:150],
        },
    )
    log_action(
        request,
        "accessi_preset_salva",
        "permessi",
        {"modulo": modulo, "nome": nome, "permessi": len(codici), "nuovo": creato},
    )
    return JsonResponse(
        {
            "ok": True,
            "preset": {"id": preset.id, "nome": preset.nome, "descrizione": preset.descrizione, "codici": codici},
            "nuovo": creato,
        }
    )


def _safe_int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _accessi_group_create(request) -> str:
    group = AccessGroup(
        code=str(request.POST.get("code") or "").strip().lower(),
        label=str(request.POST.get("label") or "").strip(),
        description=str(request.POST.get("description") or "").strip(),
        priority=_helpers._int_or_none(request.POST.get("priority")) or 100,
    )
    group.full_clean()
    group.save()
    messages.success(request, f"Gruppo <<{group.label}>> creato.")
    return f"{SUBJECT_GROUP}:{group.id}"


def _accessi_group_update(request) -> None:
    group = AccessGroup.objects.filter(pk=_helpers._int_or_none(request.POST.get("group_id"))).first()
    if group is None:
        messages.error(request, "Gruppo non trovato.")
        return
    group.label = str(request.POST.get("label") or group.label).strip()
    group.priority = _helpers._int_or_none(request.POST.get("priority")) or group.priority
    group.is_active = str(request.POST.get("is_active") or "1") != "0"
    group.full_clean()
    group.save()
    messages.success(request, f"Gruppo <<{group.label}>> aggiornato.")


def _accessi_member_add(request) -> None:
    group = AccessGroup.objects.filter(pk=_helpers._int_or_none(request.POST.get("group_id"))).first()
    if group is None:
        messages.error(request, "Gruppo non trovato.")
        return
    raw = str(request.POST.get("member") or "").strip()
    legacy_user = None
    if raw.isdigit():
        legacy_user = UtenteLegacy.objects.filter(id=int(raw)).first()
    if legacy_user is None and raw:
        legacy_user = UtenteLegacy.objects.filter(email__iexact=raw).first()
    if legacy_user is None and raw:
        legacy_user = UtenteLegacy.objects.filter(email__istartswith=f"{raw}@").order_by("id").first()
    if legacy_user is None:
        messages.error(request, f"Utente '{raw}' non trovato (prova con l'email o l'ID legacy).")
        return
    _membership, created = AccessGroupMembership.objects.get_or_create(
        group=group, legacy_user_id=int(legacy_user.id)
    )
    if created:
        messages.success(request, f"{legacy_user.nome or legacy_user.email} aggiunto al gruppo.")
    else:
        messages.info(request, "Era gia' nel gruppo.")


def _accessi_member_remove(request) -> None:
    membership = AccessGroupMembership.objects.filter(
        pk=_helpers._int_or_none(request.POST.get("membership_id"))
    ).first()
    if membership is None:
        messages.error(request, "Appartenenza non trovata.")
        return
    membership.delete()
    messages.success(request, "Persona rimossa dal gruppo.")


def _accessi_save_grants(request, *, kind: str, subject_id: int | None) -> None:
    """Scrive i grant canonici del soggetto. Nessun layer legacy, mai."""
    if not kind or not subject_id:
        messages.error(request, "Seleziona prima un gruppo o un ruolo.")
        return

    # I selezionati arrivano in UN solo campo JSON, non un campo per permesso:
    # con oltre mille permessi in catalogo un hidden per riga sfonda
    # DATA_UPLOAD_MAX_NUMBER_FIELDS (1000) e Django risponde 400 prima ancora di
    # entrare nella view. Il ramo a campi separati resta per il caso senza JS.
    raw_selection = request.POST.get("granted_json")
    if raw_selection:
        try:
            selection = json.loads(raw_selection)
        except ValueError:
            messages.error(request, "Selezione non leggibile: riprova.")
            return
        checked = {str(code).strip() for code in selection if str(code).strip()}
        rendered = [
            str(code)
            for code in PermissionDefinition.objects.filter(is_active=True)
            .order_by("module", "code")
            .values_list("code", flat=True)
        ]
    else:
        rendered = [str(code).strip() for code in request.POST.getlist("all_codes") if str(code).strip()]
        checked = {str(code).strip() for code in request.POST.getlist("granted") if str(code).strip()}
    if not rendered:
        messages.warning(request, "Nessun dato ricevuto.")
        return

    changed = 0
    with transaction.atomic():
        if kind == SUBJECT_GROUP:
            # Un gruppo concede: le righe non spuntate si cancellano invece di
            # diventare un diniego esplicito, altrimenti un gruppo con priorita'
            # alta toglierebbe ai suoi membri cio' che il ruolo gia' concede.
            existing = {
                str(row.permission_id): row
                for row in GroupPermissionGrant.objects.filter(group_id=subject_id)
            }
            for code in rendered:
                row = existing.get(code)
                if code in checked:
                    if row is None:
                        GroupPermissionGrant.objects.create(
                            group_id=subject_id, permission_id=code, enabled=True
                        )
                        changed += 1
                    elif not row.enabled:
                        row.enabled = True
                        row.save(update_fields=["enabled"])
                        changed += 1
                elif row is not None:
                    row.delete()
                    changed += 1
        else:
            for code in rendered:
                enabled = code in checked
                row, created = RolePermissionGrant.objects.get_or_create(
                    legacy_role_id=subject_id,
                    permission_id=code,
                    defaults={"enabled": enabled},
                )
                if created:
                    if enabled:
                        changed += 1
                elif bool(row.enabled) != enabled:
                    row.enabled = enabled
                    row.save(update_fields=["enabled"])
                    changed += 1

    transaction.on_commit(bump_navigation_registry_version)
    messages.success(request, f"Salvato. Permessi aggiornati: {changed}.")
