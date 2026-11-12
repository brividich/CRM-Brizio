"""Viste del Pannello di amministrazione — Navigazione: builder menu, pulsanti, wizard pulsante, topbar, schema dati.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.files.storage import default_storage
from django.db import DatabaseError, connections, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.acl_v2 import (
    normalize_permission_code,
    resolve_canonical_target,
    validate_permission_code,
)
from core.legacy_models import AnagraficaDipendente, Permesso, Pulsante, Ruolo, UtenteLegacy
from core.navigation_registry import (
    PERMESSO_ASSENTE,
    PERMESSO_ESPLICITO_E_PAGINA,
    PERMESSO_ESPLICITO_IGNORATO,
    bump_navigation_registry_version,
    describe_navigation_items_permission,
    export_navigation_state,
    is_external_navigation_item,
    publish_navigation_snapshot,
    restore_navigation_snapshot,
)
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from core.models import (
    LegacyRedirect,
    NavigationItem,
    NavigationRoleAccess,
    NavigationSnapshot,
    Profile,
)

from ..decorators import legacy_admin_required
from core import naming

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)

NAV_ICON_STORAGE_DIR = "navigation/icons"
# Immagini raster accettate negli upload serviti da /media/ (audit A9: niente SVG/HTML).
_RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_RASTER_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
NAV_ICON_ALLOWED_EXTENSIONS = {".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}  # niente SVG (audit A9)


def _is_allowed_nav_icon_extension(ext: str) -> bool:
    return str(ext or "").strip().lower() in NAV_ICON_ALLOWED_EXTENSIONS


def _navigation_icon_library_items() -> list[dict[str, str]]:
    try:
        _, files = default_storage.listdir(NAV_ICON_STORAGE_DIR)
    except Exception:
        return []

    items: list[dict[str, str]] = []
    for filename in sorted(files, key=str.lower):
        ext = Path(str(filename or "")).suffix.lower()
        if not _is_allowed_nav_icon_extension(ext):
            continue
        stored_value = f"{NAV_ICON_STORAGE_DIR}/{str(filename).strip().lstrip('/')}".replace("\\", "/")
        items.append(
            {
                "name": Path(filename).name,
                "label": Path(filename).stem,
                "value": stored_value,
                "url": _helpers._card_image_public_url(stored_value),
            }
        )
    return items


def _save_navigation_icon_upload(upload) -> tuple[str, str]:
    filename = str(getattr(upload, "name", "") or "icon").strip() or "icon"
    base_name, ext = os.path.splitext(filename)
    ext = ext.lower()
    if not _is_allowed_nav_icon_extension(ext):
        raise ValidationError("Formato file non valido: usa .ico, .png o un formato immagine supportato.")
    try:
        # SEC (audit A9): contenuto reale verificato, niente SVG/HTML rinominati.
        validate_extension_and_mime(
            upload,
            allowed_extensions=NAV_ICON_ALLOWED_EXTENSIONS,
            allowed_mimes=_RASTER_IMAGE_MIMES | {
                "image/x-icon", "image/vnd.microsoft.icon", "image/bmp", "image/x-ms-bmp", "image/avif",
            },
            label="Icona",
        )
    except UploadMimeValidationError as exc:
        raise ValidationError(str(exc)) from exc

    safe_name = slugify(base_name) or "nav-icon"
    unique_suffix = timezone.now().strftime("%Y%m%d%H%M%S%f")
    target_path = f"{NAV_ICON_STORAGE_DIR}/{safe_name}-{unique_suffix}{ext}"
    saved_path = default_storage.save(target_path, upload).replace("\\", "/")
    return saved_path, _helpers._card_image_public_url(saved_path)


def _count_ui_pulsanti_meta_rows() -> int | None:
    _helpers._ensure_pulsanti_ui_meta_table()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ui_pulsanti_meta")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return None


@legacy_admin_required
@require_GET
def schema_dati(request):
    tables = []
    try:
        auth_user_count = get_user_model().objects.count()
    except Exception:
        auth_user_count = None
    try:
        profile_count = Profile.objects.count()
    except Exception:
        profile_count = None
    try:
        legacy_utenti_count = UtenteLegacy.objects.count()
    except DatabaseError:
        legacy_utenti_count = None
    try:
        legacy_ruoli_count = Ruolo.objects.count()
    except DatabaseError:
        legacy_ruoli_count = None
    try:
        legacy_permessi_count = Permesso.objects.count()
    except DatabaseError:
        legacy_permessi_count = None
    try:
        legacy_pulsanti_count = Pulsante.objects.count()
    except DatabaseError:
        legacy_pulsanti_count = None
    ui_meta_count = _count_ui_pulsanti_meta_rows()

    tables.extend(
        [
            {
                "name": "utenti",
                "layer": "SQL Server (legacy)",
                "used_for": "Anagrafica utenti del portale legacy + utenti auto-creati da login LDAP.",
                "managed_from": "Admin Portale -> Utenti",
                "notes": "Campi chiave: nome, email, ruolo, ruolo_id, attivo, password (*AD_MANAGED* per utenti LDAP).",
                "count": legacy_utenti_count,
            },
            {
                "name": "ruoli",
                "layer": "SQL Server (legacy)",
                "used_for": "Ruoli applicativi (es. admin, utente) usati da ACL e gestione utenti.",
                "managed_from": "DB legacy / (parziale) Admin Portale",
                "notes": "Il ruolo assegnato all'utente determina i permessi effettivi.",
                "count": legacy_ruoli_count,
            },
            {
                "name": "permessi",
                "layer": "SQL Server (legacy)",
                "used_for": "Matrice ACL per ruolo + modulo + azione (can_view/can_edit/...).",
                "managed_from": "Admin Portale -> Permessi",
                "notes": "Serve per autorizzare pagine/menu; se mancante o can_view=0 genera 403.",
                "count": legacy_permessi_count,
            },
            {
                "name": "pulsanti",
                "layer": "SQL Server (legacy)",
                "used_for": "Definizione menu/pulsanti (codice, label, modulo, url, icona).",
                "managed_from": "Admin Portale -> Pulsanti",
                "notes": "Usata sia per topbar dinamica sia per mappare ACL (modulo+azione). Supporta url `route:...`.",
                "count": legacy_pulsanti_count,
            },
            {
                "name": "ui_pulsanti_meta",
                "layer": "SQL Server (nuova tabella supporto Django)",
                "used_for": "Metadati UI dei pulsanti: slot, sezione, ordine UI, topbar, attivo.",
                "managed_from": "Admin Portale -> Pulsanti",
                "notes": "Tabella creata dal portale per gestire posizione/contesto senza hardcode.",
                "count": ui_meta_count,
            },
            {
                "name": "core_profile",
                "layer": "DB Django",
                "used_for": "Collegamento tra utente Django e utente legacy (legacy_user_id, ruolo snapshot).",
                "managed_from": "Automatico (login/sync)",
                "notes": "Ãˆ il ponte tra autenticazione Django e tabelle legacy.",
                "count": profile_count,
            },
            {
                "name": "auth_user",
                "layer": "DB Django",
                "used_for": "Utenti Django per sessione/login e integrazione con middleware Django.",
                "managed_from": "Automatico (sync da legacy / LDAP)",
                "notes": "Non sostituisce `utenti`: viene sincronizzata per usare auth/sessioni Django.",
                "count": auth_user_count,
            },
        ]
    )

    return render(
        request,
        "admin_portale/pages/schema_dati.html",
        {
            "tables": tables,
        },
    )


@legacy_admin_required
@require_GET
def topbar_live(request):
    q_filter = (request.GET.get("q") or "").strip()
    section_filter = (request.GET.get("section") or "").strip()
    view_mode = (request.GET.get("view") or "topbar").strip().lower()
    if view_mode not in {"topbar", "all"}:
        view_mode = "topbar"

    try:
        pulsanti_list = list(Pulsante.objects.all())
    except DatabaseError as exc:
        pulsanti_list = []
        messages.error(request, f"Errore lettura pulsanti: {exc}")

    ui_meta_map = _helpers._pulsanti_ui_meta_map()
    order_map = _helpers._pulsanti_order_map()

    section_options = {
        "toolbar",
        "dashboard",
        "gestione_assenze",
        "calendario_assenze",
        "richiesta_assenza",
        "richieste",
        "gestione_anomalie",
        "admin",
    }
    slot_options = {"topbar", "toolbar", "sidebar", "page", "widget", "hidden"}

    for p in pulsanti_list:
        pid = int(getattr(p, "id", 0) or 0)
        meta = ui_meta_map.get(pid, {})
        ui_slot = (meta.get("ui_slot", "") or "").strip()
        ui_section = (meta.get("ui_section", "") or "").strip()
        visible_topbar = bool(meta.get("visible_topbar", True))
        enabled = bool(meta.get("enabled", True))

        setattr(p, "ui_slot", ui_slot)
        setattr(p, "ui_section", ui_section)
        setattr(p, "ui_order_meta", meta.get("ui_order"))
        setattr(p, "visible_topbar", visible_topbar)
        setattr(p, "ui_enabled", enabled)
        setattr(p, "is_padre", bool(meta.get("is_padre", False)))
        setattr(p, "ordine_value", order_map.get(pid))
        setattr(
            p,
            "display_label",
            (p.nome_visibile or getattr(p, "label", "") or p.codice or f"Pulsante #{pid}"),
        )

        ui_slot_norm = ui_slot.lower()
        is_topbar_slot = ui_slot_norm in {"", "topbar", "toolbar"}
        setattr(p, "is_topbar_candidate", bool(visible_topbar and is_topbar_slot))
        setattr(p, "is_topbar_active", bool(visible_topbar and enabled and is_topbar_slot))

        if ui_section:
            section_options.add(ui_section)
        if ui_slot:
            slot_options.add(ui_slot)

    if view_mode == "topbar":
        pulsanti_list = [p for p in pulsanti_list if getattr(p, "is_topbar_candidate", False)]

    if section_filter:
        section_filter_l = section_filter.lower()
        pulsanti_list = [
            p for p in pulsanti_list if (getattr(p, "ui_section", "") or "").lower() == section_filter_l
        ]

    if q_filter:
        q_lower = q_filter.lower()
        pulsanti_list = [
            p
            for p in pulsanti_list
            if q_lower in (p.codice or "").lower()
            or q_lower in (p.nome_visibile or "").lower()
            or q_lower in (p.modulo or "").lower()
            or q_lower in (p.url or "").lower()
            or q_lower in (getattr(p, "ui_section", "") or "").lower()
            or q_lower in (getattr(p, "ui_slot", "") or "").lower()
        ]

    pulsanti_list.sort(
        key=lambda p: (
            getattr(p, "ui_order_meta", 999999) if getattr(p, "ui_order_meta", None) is not None else 999999,
            getattr(p, "ordine_value", 999999) if getattr(p, "ordine_value", None) is not None else 999999,
            (p.display_label or "").lower(),
            int(p.id),
        )
    )

    return render(
        request,
        "admin_portale/pages/topbar_live.html",
        {
            "pulsanti_list": pulsanti_list,
            "section_options": sorted(section_options, key=str.lower),
            "slot_options": sorted(slot_options, key=str.lower),
            "filters": {"q": q_filter, "section": section_filter, "view": view_mode},
            "route_catalog": _helpers._route_catalog(),
        },
    )


def _parse_role_ids(value) -> list[int]:
    if isinstance(value, list):
        raw_tokens = value
    else:
        raw_tokens = str(value or "").replace(";", ",").split(",")
    result: list[int] = []
    seen = set()
    for token in raw_tokens:
        try:
            role_id = int(str(token).strip())
        except Exception:
            continue
        if role_id <= 0 or role_id in seen:
            continue
        seen.add(role_id)
        result.append(role_id)
    return result


def _normalize_nav_url_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "/")):
        return raw
    return "/" + raw


def _normalize_legacy_path_input(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw != "/":
        raw = raw.rstrip("/")
    return raw.lower()


def _apply_navigation_role_access(item: NavigationItem, role_ids: list[int]) -> None:
    NavigationRoleAccess.objects.filter(item=item).delete()
    if not role_ids:
        return
    rows = [
        NavigationRoleAccess(item=item, legacy_role_id=int(role_id), can_view=True)
        for role_id in role_ids
    ]
    NavigationRoleAccess.objects.bulk_create(rows)


def _explicit_code_to_store(code: str, *, route_name: str, url_path: str) -> str:
    """Il permission code da salvare sulla voce.

    Vuoto o uguale a quello della pagina -> si salva vuoto: la voce segue il
    permesso della pagina anche quando la rotta viene rilegata (es. le
    impostazioni dei moduli separate da «gestire»). Copiarlo qui lo
    congelerebbe e il menu tornerebbe a dire una cosa diversa dalla pagina.
    """
    if not code:
        return ""
    target = resolve_canonical_target(path=url_path or None, route_name=route_name or None)
    binding = target.get("binding") or {}
    if normalize_permission_code(str(binding.get("permission_code") or "")) == code:
        return ""
    return code


def _navigation_item_payload(
    item: NavigationItem,
    role_ids_map: dict[int, list[int]],
    perm_info_map: dict[int, dict] | None = None,
) -> dict:
    role_ids = role_ids_map.get(int(item.id), [])
    required_permission_code = _helpers._navigation_item_permission_code(item)
    perm_info = (perm_info_map or {}).get(int(item.id)) or {}
    return {
        "id": int(item.id),
        "code": item.code,
        "label": item.label,
        "section": item.section,
        "parent_code": item.parent_code or "",
        "route_name": item.route_name,
        "url_path": item.url_path,
        "required_permission_code": required_permission_code,
        "order": int(item.order),
        "is_visible": bool(item.is_visible),
        "is_enabled": bool(item.is_enabled),
        "open_in_new_tab": bool(item.open_in_new_tab),
        "icon": item.icon or "",
        "group": item.group or "",
        "active_patterns": item.active_patterns or "",
        "description": item.description or "",
        "role_ids": role_ids,
        "role_ids_csv": ",".join(str(v) for v in role_ids),
        # Cosa decide davvero la voce (badge del builder).
        "perm_explicit": perm_info.get("explicit", ""),
        "perm_target": perm_info.get("target", ""),
        "perm_stato": perm_info.get("stato", ""),
        # Link esterno senza permesso: lo vedono tutti (navigation_registry).
        "esterno": is_external_navigation_item(item),
    }


def _nav_preview_rows(nav_override_user, items, user_grants: dict[int, bool], perm_info_map: dict[int, dict]) -> list[dict]:
    """Per ogni voce: la vede l'utente? Con lo stesso risolutore delle pagine.

    Prima si guardava solo il ruolo legacy (``utenti.ruolo_id``): con i ruoli
    del portale, l'organigramma e il ruolo base l'anteprima mentiva.
    """
    from core.acl_resolver import resolve_permission_decision
    from core.legacy_utils import is_legacy_admin
    from core.permessi.motore import sistema_ruoli_attivo

    ruoli_attivi = sistema_ruoli_attivo()
    is_admin = bool(is_legacy_admin(nav_override_user))
    role_id = _helpers._int_or_none(getattr(nav_override_user, "ruolo_id", None))
    legacy_access: dict[int, set[int]] = {}
    for row in NavigationRoleAccess.objects.filter(item_id__in=[int(i.id) for i in items], can_view=True):
        legacy_access.setdefault(int(row.item_id), set()).add(int(row.legacy_role_id))
    decisions: dict[str, tuple[bool, str]] = {}

    def _decide(code: str) -> tuple[bool, str]:
        if code not in decisions:
            decision = resolve_permission_decision(permission_code=code, legacy_user=nav_override_user)
            decisions[code] = (bool(decision.allowed), str(decision.reason or ""))
        return decisions[code]

    rows: list[dict] = []
    for ni in items:
        iid = int(ni.id)
        info = perm_info_map.get(iid) or {}
        if ruoli_attivi:
            codes = list(info.get("codes") or [])
        else:
            code = info.get("explicit") or info.get("target") or ""
            codes = [code] if code else []
        if is_admin:
            role_allowed, reason = True, "Amministratore: vede tutto il menu."
        elif codes:
            esiti = [_decide(code) for code in codes]
            role_allowed = all(ok for ok, _r in esiti)
            reason = next((r for ok, r in esiti if not ok), esiti[0][1])
        elif ruoli_attivi and is_external_navigation_item(ni):
            role_allowed, reason = True, "Link esterno: lo vedono tutti."
        elif ruoli_attivi:
            role_allowed, reason = False, "Voce senza permesso: con i ruoli del portale la vedono solo gli amministratori."
        else:
            role_allowed = bool(role_id is not None and role_id in legacy_access.get(iid, set()))
            reason = "Ruoli abilitati della voce (regole storiche)."
        override = user_grants.get(iid)
        if override is False:
            state = "ov-hide"
        elif role_allowed:
            state = "role-show"
        else:
            state = "role-hide"
        rows.append({
            "item_id": iid,
            "item_code": ni.code,
            "item_label": ni.label,
            "item_section": ni.section,
            "item_icon": ni.icon or "",
            "required_permission_code": info.get("effective", "") if ruoli_attivi else (codes[0] if codes else ""),
            "role_allowed": role_allowed,
            "reason": reason,
            "override": False if override is False else None,
            "state": state,
        })
    return rows


def _normalize_navigation_icon(value) -> str:
    return str(value or "").strip()[:500]


def _unique_nav_code(base_code: str, used: set[str]) -> str:
    base = slugify(base_code or "")[:72] or "item"
    candidate = base
    idx = 2
    while candidate in used:
        suffix = f"-{idx}"
        candidate = (base[: max(1, 80 - len(suffix))] + suffix)[:80]
        idx += 1
    used.add(candidate)
    return candidate


@legacy_admin_required
@require_GET
def navigation_builder(request):
    q_filter = (request.GET.get("q") or "").strip()
    section_filter = (request.GET.get("section") or "all").strip().lower()
    advanced_mode = _helpers._bool_from_any(request.GET.get("advanced"))
    if section_filter not in {"topbar", "subnav", "sidebar", "page", "admin_subnav", "all"}:
        section_filter = "all"

    items_all = list(NavigationItem.objects.all().order_by("section", "order", "label", "id"))
    if q_filter:
        q_lower = q_filter.lower()
        items_all = [
            item
            for item in items_all
            if q_lower in (item.code or "").lower()
            or q_lower in (item.label or "").lower()
            or q_lower in (item.route_name or "").lower()
            or q_lower in (item.url_path or "").lower()
            or q_lower in _helpers._navigation_item_permission_code(item).lower()
            or q_lower in (item.section or "").lower()
        ]
    if section_filter == "all":
        items = list(items_all)
    else:
        items = [item for item in items_all if str(item.section or "").strip().lower() == section_filter]

    access_rows = NavigationRoleAccess.objects.filter(item_id__in=[int(i.id) for i in items_all]).order_by("legacy_role_id")
    role_ids_map: dict[int, list[int]] = {}
    for row in access_rows:
        role_ids_map.setdefault(int(row.item_id), []).append(int(row.legacy_role_id))

    perm_info_map = describe_navigation_items_permission(items_all)
    item_rows_all = [_navigation_item_payload(item, role_ids_map, perm_info_map) for item in items_all]
    item_rows = [_navigation_item_payload(item, role_ids_map, perm_info_map) for item in items]

    from core.permessi.motore import sistema_ruoli_attivo

    ruoli_attivi = sistema_ruoli_attivo()
    try:
        ruoli = list(Ruolo.objects.all().order_by("nome").values("id", "nome"))
    except DatabaseError:
        ruoli = []
    perm_ignorati = sum(1 for r in item_rows_all if r["perm_stato"] == PERMESSO_ESPLICITO_IGNORATO)
    perm_doppi = sum(1 for r in item_rows_all if r["perm_stato"] == PERMESSO_ESPLICITO_E_PAGINA)
    perm_assenti = sum(
        1 for r in item_rows_all
        if r["perm_stato"] == PERMESSO_ASSENTE and r["section"] != "admin_subnav" and r["is_visible"] and not r["esterno"]
    )

    snapshots = list(NavigationSnapshot.objects.all().order_by("-version", "-id")[:20])
    redirects = list(LegacyRedirect.objects.all().order_by("legacy_path", "id")[:200])

    # Override navigazione utente
    from core.models import UserNavigationOverride
    nav_override_user_id = _helpers._int_or_none(request.GET.get("nav_override_user_id"))
    nav_override_user = None
    nav_override_user_label = ""
    nav_override_rows: list[dict] = []
    nav_items_for_override: list[dict] = []
    if nav_override_user_id:
        try:
            nav_override_user = UtenteLegacy.objects.get(id=nav_override_user_id)
        except UtenteLegacy.DoesNotExist:
            nav_override_user_id = None
        if nav_override_user:
            try:
                ana = AnagraficaDipendente.objects.filter(utente_id=nav_override_user_id).first()
                cognome = str(getattr(ana, "cognome", "") or "").strip()
                nome = str(getattr(nav_override_user, "nome", "") or "").strip()
                nav_override_user_label = (naming.nome_completo(ana.nome, ana.cognome) if ana else "") or nome or nav_override_user.email or str(nav_override_user_id)
            except Exception:
                nav_override_user_label = str(getattr(nav_override_user, "nome", "") or nav_override_user_id)
            user_grants = {
                int(ov.item_id): bool(ov.enabled)
                for ov in UserNavigationOverride.objects.filter(legacy_user_id=nav_override_user_id)
            }
            nav_visible_items = list(NavigationItem.objects.filter(
                is_visible=True, is_enabled=True,
                section__in=["topbar", "subnav", "sidebar", "page"],
            ).order_by("section", "order", "label"))
            nav_override_rows = _nav_preview_rows(
                nav_override_user,
                nav_visible_items,
                user_grants,
                describe_navigation_items_permission(nav_visible_items),
            )
            # Raggruppamento per section
            nav_sections_order = ["topbar", "subnav", "sidebar", "page"]
            nav_override_by_section: dict[str, list] = {s: [] for s in nav_sections_order}
            for row in nav_override_rows:
                s = row["item_section"]
                if s in nav_override_by_section:
                    nav_override_by_section[s].append(row)
    visual_lane_defs = [
        ("topbar", "Main Nav (Topbar/Sidebar)", "Navigazione principale: in UI side viene resa nella sidebar."),
        ("subnav", "Subnav", "Secondo livello contestuale per modulo"),
        ("admin_subnav", "Admin Subnav", "Menu interno admin portale"),
        ("sidebar", "Sidebar Dedicated", "Slot dedicato menu laterale (se usato esplicitamente)."),
        ("page", "Page", "Azioni locali dentro una pagina"),
    ]
    visual_rows_by_section: dict[str, list[dict]] = {key: [] for key, _label, _hint in visual_lane_defs}
    for row in item_rows_all:
        section_key = str(row.get("section") or "").strip().lower()
        if section_key not in visual_rows_by_section:
            continue
        visual_rows_by_section[section_key].append(row)
    visual_sections = [
        {
            "key": key,
            "label": label,
            "hint": hint,
            "items": visual_rows_by_section.get(key, []),
        }
        for key, label, hint in visual_lane_defs
    ]

    # Moduli topbar disponibili come "Modulo padre" per le voci subnav (3° livello sidebar).
    # Query dedicata (non filtrata da q_filter) così il menù è sempre completo.
    topbar_modules = [
        {"code": it.code, "label": it.label}
        for it in NavigationItem.objects.filter(section="topbar", is_visible=True).order_by("label", "code")
    ]
    topbar_module_codes = [m["code"] for m in topbar_modules]

    return render(
        request,
        "admin_portale/pages/navigation_builder.html",
        {
            "item_rows": item_rows,
            "route_catalog": _helpers._route_catalog(),
            "ruoli": ruoli,
            "ruoli_attivi": ruoli_attivi,
            "perm_ignorati": perm_ignorati,
            "perm_doppi": perm_doppi,
            "perm_assenti": perm_assenti,
            "snapshots": snapshots,
            "redirects": redirects,
            "icon_library": _navigation_icon_library_items(),
            "topbar_modules": topbar_modules,
            "topbar_module_codes": topbar_module_codes,
            "filters": {"q": q_filter, "section": section_filter, "advanced": "1" if advanced_mode else "0"},
            "state_preview_json": json.dumps(export_navigation_state(), ensure_ascii=False, indent=2),
            "visual_sections": visual_sections,
            "advanced_mode": bool(advanced_mode),
            # Override navigazione per-utente
            "nav_override_user_id": nav_override_user_id,
            "nav_override_user": nav_override_user,
            "nav_override_user_label": nav_override_user_label,
            "nav_override_rows": nav_override_rows,
            "nav_override_by_section": nav_override_by_section if nav_override_user_id else {},
        },
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_create(request):
    payload = _helpers._post_or_json_payload(request)
    label = str(payload.get("label") or "").strip()
    if not label:
        return _helpers._json_error("Label obbligatoria.")

    code_raw = str(payload.get("code") or "").strip() or label
    code = slugify(code_raw)[:80]
    if not code:
        return _helpers._json_error("Codice non valido.")
    if NavigationItem.objects.filter(code=code).exists():
        return _helpers._json_error("Codice gia' presente. Scegli un codice diverso.")

    route_name = str(payload.get("route_name") or "").strip()
    url_path = _normalize_nav_url_path(payload.get("url_path") or "")
    if not route_name and not url_path:
        return _helpers._json_error("Serve almeno route_name o url_path.")
    required_permission_code = normalize_permission_code(str(payload.get("required_permission_code") or ""))
    if required_permission_code:
        is_valid_code, validation_error = validate_permission_code(required_permission_code)
        if not is_valid_code:
            return _helpers._json_error(validation_error or "Permission code non valido.")
    required_permission_code = _explicit_code_to_store(required_permission_code, route_name=route_name, url_path=url_path)

    section = str(payload.get("section") or "topbar").strip().lower() or "topbar"
    parent_code = str(payload.get("parent_code") or "").strip().lower()
    icon = _normalize_navigation_icon(payload.get("icon"))
    order_value = _helpers._int_or_none(payload.get("order"))
    role_ids = _parse_role_ids(payload.get("role_ids") or payload.get("role_ids_csv"))

    try:
        with transaction.atomic():
            item = NavigationItem.objects.create(
                code=code,
                label=label,
                section=section,
                parent_code=parent_code,
                route_name=route_name,
                url_path=url_path,
                required_permission_code=required_permission_code,
                order=(order_value if order_value is not None else 100),
                is_visible=_helpers._bool_from_any(payload.get("is_visible")) if "is_visible" in payload else True,
                is_enabled=_helpers._bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else True,
                open_in_new_tab=_helpers._bool_from_any(payload.get("open_in_new_tab")) if "open_in_new_tab" in payload else False,
                icon=icon,
                description=str(payload.get("description") or "").strip(),
                created_by=request.user,
                updated_by=request.user,
            )
            _apply_navigation_role_access(item, role_ids)
            transaction.on_commit(bump_navigation_registry_version)
    except Exception as exc:
        return _helpers._json_error(f"Errore salvataggio: {exc}", status=500)

    return JsonResponse({"ok": True, "id": int(item.id), "code": item.code})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_update(request):
    payload = _helpers._post_or_json_payload(request)
    item_id = _helpers._int_or_none(payload.get("id"))
    if not item_id:
        return _helpers._json_error("ID voce mancante.")
    item = get_object_or_404(NavigationItem, id=item_id)

    label = str(payload.get("label") or "").strip()
    if not label:
        return _helpers._json_error("Label obbligatoria.")

    code_raw = str(payload.get("code") or "").strip() or item.code
    code = slugify(code_raw)[:80]
    if not code:
        return _helpers._json_error("Codice non valido.")
    if NavigationItem.objects.filter(code=code).exclude(id=item.id).exists():
        return _helpers._json_error("Codice gia' presente su un'altra voce.")

    route_name = str(payload.get("route_name") or "").strip()
    url_path = _normalize_nav_url_path(payload.get("url_path") or "")
    if not route_name and not url_path:
        return _helpers._json_error("Serve almeno route_name o url_path.")
    required_permission_code = normalize_permission_code(str(payload.get("required_permission_code") or ""))
    if required_permission_code:
        is_valid_code, validation_error = validate_permission_code(required_permission_code)
        if not is_valid_code:
            return _helpers._json_error(validation_error or "Permission code non valido.")
    required_permission_code = _explicit_code_to_store(required_permission_code, route_name=route_name, url_path=url_path)

    section = str(payload.get("section") or "topbar").strip().lower() or "topbar"
    parent_code = str(payload.get("parent_code") or "").strip().lower()
    icon = _normalize_navigation_icon(payload.get("icon"))
    order_value = _helpers._int_or_none(payload.get("order"))
    role_ids = _parse_role_ids(payload.get("role_ids") or payload.get("role_ids_csv"))

    try:
        with transaction.atomic():
            item.code = code
            item.label = label
            item.section = section
            item.parent_code = parent_code
            item.route_name = route_name
            item.url_path = url_path
            item.required_permission_code = required_permission_code
            item.order = order_value if order_value is not None else 100
            item.is_visible = _helpers._bool_from_any(payload.get("is_visible")) if "is_visible" in payload else item.is_visible
            item.is_enabled = _helpers._bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else item.is_enabled
            item.open_in_new_tab = (
                _helpers._bool_from_any(payload.get("open_in_new_tab")) if "open_in_new_tab" in payload else item.open_in_new_tab
            )
            item.icon = icon
            item.description = str(payload.get("description") or "").strip()
            item.updated_by = request.user
            item.save()
            _apply_navigation_role_access(item, role_ids)
            transaction.on_commit(bump_navigation_registry_version)
    except Exception as exc:
        return _helpers._json_error(f"Errore aggiornamento: {exc}", status=500)

    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_item_delete(request):
    payload = _helpers._post_or_json_payload(request)
    item_id = _helpers._int_or_none(payload.get("id"))
    if not item_id:
        return _helpers._json_error("ID voce mancante.")
    deleted, _ = NavigationItem.objects.filter(id=item_id).delete()
    if not deleted:
        return _helpers._json_error("Voce non trovata.", status=404)
    transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_reorder(request):
    """Aggiorna ordine (e opzionalmente sezione) delle voci di navigazione."""
    payload = _helpers._post_or_json_payload(request)
    section_orders = payload.get("section_orders")
    if isinstance(section_orders, dict):
        allowed_sections = {"topbar", "subnav", "admin_subnav", "sidebar", "page"}
        cleaned: dict[str, list[int]] = {}
        seen_item_ids: set[int] = set()
        for section_key, raw_ids in section_orders.items():
            section = str(section_key or "").strip().lower()
            if section not in allowed_sections:
                return _helpers._json_error(f"Sezione non valida: {section_key}")
            if not isinstance(raw_ids, list):
                return _helpers._json_error(f"section_orders[{section}] deve essere una lista di ID interi.")
            try:
                item_ids = [int(value) for value in raw_ids]
            except (TypeError, ValueError):
                return _helpers._json_error(f"section_orders[{section}] contiene valori non interi.")
            for item_id in item_ids:
                if item_id in seen_item_ids:
                    return _helpers._json_error(f"ID duplicato nel drag&drop visuale: {item_id}")
                seen_item_ids.add(item_id)
            cleaned[section] = item_ids
        with transaction.atomic():
            for section, item_ids in cleaned.items():
                for idx, item_id in enumerate(item_ids):
                    NavigationItem.objects.filter(id=item_id).update(
                        section=section,
                        order=(idx + 1) * 10,
                    )
        transaction.on_commit(bump_navigation_registry_version)
        return JsonResponse({"ok": True, "mode": "section_orders", "updated": len(seen_item_ids)})

    ordered_ids = payload.get("ordered_ids")
    if not isinstance(ordered_ids, list):
        return _helpers._json_error("ordered_ids deve essere una lista di ID interi.")
    try:
        ordered_ids = [int(x) for x in ordered_ids]
    except (TypeError, ValueError):
        return _helpers._json_error("ordered_ids contiene valori non interi.")
    with transaction.atomic():
        for idx, item_id in enumerate(ordered_ids):
            NavigationItem.objects.filter(id=item_id).update(order=(idx + 1) * 10)
    transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_bootstrap_from_legacy(request):
    payload = _helpers._post_or_json_payload(request)
    force = _helpers._bool_from_any(payload.get("force")) if "force" in payload else False
    if NavigationItem.objects.exists() and not force:
        return _helpers._json_error("NavigationItem gia' popolata. Usa force=1 per sovrascrivere.", status=409)

    ui_meta_map = _helpers._pulsanti_ui_meta_map()
    order_map = _helpers._pulsanti_order_map()
    _helpers.pulsanti = list(Pulsante.objects.all().order_by("id"))
    used_codes = {str(v).strip().lower() for v in NavigationItem.objects.values_list("code", flat=True)}

    created = 0
    updated = 0
    with transaction.atomic():
        if force:
            NavigationRoleAccess.objects.all().delete()
            NavigationItem.objects.all().delete()
            used_codes = set()

        for puls in _helpers.pulsanti:
            pid = int(getattr(puls, "id", 0) or 0)
            meta = ui_meta_map.get(pid, {})
            if meta and not bool(meta.get("enabled", True)):
                continue
            if meta and not bool(meta.get("visible_topbar", True)):
                continue
            ui_slot = str(meta.get("ui_slot") or "").strip().lower() if isinstance(meta, dict) else ""
            if ui_slot and ui_slot not in {"topbar", "toolbar"}:
                continue

            raw_url = str(puls.url or "").strip()
            route_name = ""
            url_path = ""
            lower = raw_url.lower()
            if lower.startswith("route:") or lower.startswith("django:"):
                route_name = raw_url.split(":", 1)[1].strip()
            else:
                url_path = _normalize_nav_url_path(raw_url)
            required_permission_code = normalize_permission_code(
                str(resolve_canonical_target(path=url_path or None, route_name=route_name or None).get("binding", {}).get("permission_code") or "")
            )

            order_hint = meta.get("ui_order") if isinstance(meta, dict) else None
            if order_hint is None:
                order_hint = order_map.get(pid)
            if order_hint is None:
                order_hint = 1000 + pid

            base_code = str(puls.codice or puls.nome_visibile or f"legacy-{pid}")
            code = _unique_nav_code(base_code, used_codes)
            label = str(puls.nome_visibile or puls.label or puls.codice or f"Voce {pid}")

            item = NavigationItem.objects.filter(code=code).first()
            is_created = item is None
            if is_created:
                item = NavigationItem(
                    code=code,
                    created_by=request.user,
                )
            item.label = label
            item.section = "topbar"
            item.route_name = route_name
            item.url_path = url_path
            item.required_permission_code = required_permission_code
            item.order = int(order_hint)
            item.is_visible = True
            item.is_enabled = True
            item.icon = _normalize_navigation_icon(getattr(puls, "icona", ""))
            item.description = f"Importata da pulsanti.id={pid}"
            item.updated_by = request.user
            item.save()
            if is_created:
                created += 1
            else:
                updated += 1

        transaction.on_commit(bump_navigation_registry_version)

    return JsonResponse({"ok": True, "created": created, "updated": updated})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_publish(request):
    payload = _helpers._post_or_json_payload(request)
    note = str(payload.get("note") or "").strip()
    snap = publish_navigation_snapshot(created_by=request.user, note=note)
    return JsonResponse({"ok": True, "snapshot_id": int(snap.id), "version": int(snap.version)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_restore(request):
    payload = _helpers._post_or_json_payload(request)
    snapshot_id = _helpers._int_or_none(payload.get("snapshot_id") or payload.get("id"))
    if not snapshot_id:
        return _helpers._json_error("snapshot_id mancante.")
    snapshot = get_object_or_404(NavigationSnapshot, id=snapshot_id)
    try:
        restore_navigation_snapshot(snapshot)
    except Exception as exc:
        return _helpers._json_error(f"Errore restore snapshot: {exc}", status=500)
    return JsonResponse({"ok": True, "restored_version": int(snapshot.version)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_navigation_icon_upload(request):
    upload = request.FILES.get("icon") or request.FILES.get("image")
    if upload is None:
        return _helpers._json_error("File icona mancante.")

    content_type = str(getattr(upload, "content_type", "") or "").strip().lower()
    ext = Path(str(getattr(upload, "name", "") or "")).suffix.lower()
    if content_type and not content_type.startswith("image/") and not _is_allowed_nav_icon_extension(ext):
        return _helpers._json_error("Formato file non valido: serve una immagine.")

    try:
        saved_path, public_url = _save_navigation_icon_upload(upload)
    except ValidationError as exc:
        return _helpers._json_error("; ".join(exc.messages) or "Formato file non valido.")
    except Exception as exc:
        return _helpers._json_error(f"Errore salvataggio icona: {exc}")

    return JsonResponse(
        {
            "ok": True,
            "icon": {
                "name": Path(saved_path).name,
                "label": Path(saved_path).stem,
                "value": saved_path,
                "url": public_url,
            },
        }
    )


@legacy_admin_required
@csrf_protect
@require_POST
def api_legacy_redirect_upsert(request):
    payload = _helpers._post_or_json_payload(request)
    row_id = _helpers._int_or_none(payload.get("id"))
    legacy_path = _normalize_legacy_path_input(payload.get("legacy_path"))
    if not legacy_path:
        return _helpers._json_error("legacy_path obbligatorio.")

    target_route = str(payload.get("target_route_name") or "").strip()
    target_path = _normalize_nav_url_path(payload.get("target_url_path") or "")
    if not target_route and not target_path:
        return _helpers._json_error("Serve target_route_name o target_url_path.")

    defaults = {
        "target_route_name": target_route,
        "target_url_path": target_path,
        "is_enabled": _helpers._bool_from_any(payload.get("is_enabled")) if "is_enabled" in payload else True,
        "note": str(payload.get("note") or "").strip(),
    }
    try:
        if row_id:
            row = get_object_or_404(LegacyRedirect, id=row_id)
            for key, value in defaults.items():
                setattr(row, key, value)
            row.legacy_path = legacy_path
            row.save()
        else:
            row, created = LegacyRedirect.objects.update_or_create(
                legacy_path=legacy_path,
                defaults=defaults,
            )
            _ = created
    except Exception as exc:
        return _helpers._json_error(f"Errore redirect: {exc}", status=500)

    return JsonResponse({"ok": True, "id": int(row.id)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_legacy_redirect_delete(request):
    payload = _helpers._post_or_json_payload(request)
    row_id = _helpers._int_or_none(payload.get("id"))
    if not row_id:
        return _helpers._json_error("ID redirect mancante.")
    deleted, _ = LegacyRedirect.objects.filter(id=row_id).delete()
    if not deleted:
        return _helpers._json_error("Redirect non trovato.", status=404)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_nav_user_override_toggle(request, legacy_user_id: int):
    """Imposta o rimuove un override hide-only per una voce di navigazione."""
    from core.models import UserNavigationOverride
    payload = _helpers._post_or_json_payload(request)
    item_id = _helpers._int_or_none(payload.get("item_id"))
    state = str(payload.get("state") or "").strip().lower()
    if not item_id or state not in {"hide", "inherit"}:
        return _helpers._json_error("Payload incompleto o stato non valido.")
    item = get_object_or_404(NavigationItem, pk=item_id)
    if state == "inherit":
        UserNavigationOverride.objects.filter(legacy_user_id=legacy_user_id, item=item).delete()
        bump_navigation_registry_version()
        return JsonResponse({"ok": True, "state": "inherit"})
    UserNavigationOverride.objects.update_or_create(
        legacy_user_id=legacy_user_id,
        item=item,
        defaults={"enabled": False},
    )
    bump_navigation_registry_version()
    return JsonResponse({"ok": True, "state": state})


@legacy_admin_required
@csrf_protect
@require_POST
def api_nav_user_override_clear(request, legacy_user_id: int):
    """Azzera tutti gli override navigazione per un utente."""
    from core.models import UserNavigationOverride
    deleted, _ = UserNavigationOverride.objects.filter(legacy_user_id=legacy_user_id).delete()
    bump_navigation_registry_version()
    return JsonResponse({"ok": True, "deleted": deleted})


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_card_image(request):
    """Imposta immagine card modulo globale (URL o upload file)."""
    if request.FILES:
        pid = _helpers._int_or_none(request.POST.get("pulsante_id") or request.POST.get("id"))
        upload = request.FILES.get("image")
        if not pid:
            return _helpers._json_error("ID pulsante mancante.")
        if not Pulsante.objects.filter(id=pid).exists():
            return _helpers._json_error("Pulsante non trovato.", status=404)
        if upload is None:
            return _helpers._json_error("File immagine mancante.")
        try:
            # SEC (audit A9): estensione + MIME reale (magic), niente SVG/HTML su /media/.
            validate_extension_and_mime(
                upload,
                allowed_extensions=_RASTER_IMAGE_EXTENSIONS,
                allowed_mimes=_RASTER_IMAGE_MIMES,
                label="Immagine",
            )
        except UploadMimeValidationError as exc:
            return _helpers._json_error(str(exc))

        base_name, ext = os.path.splitext(str(getattr(upload, "name", "") or "module"))
        if not ext:
            ext = ".png"
        safe_name = slugify(base_name) or f"module-{pid}"
        target_path = f"dashboard/modules/{safe_name}-{pid}{ext.lower()}"
        old_value = _helpers._card_image_raw_value(pid)

        try:
            with transaction.atomic():
                saved_path = default_storage.save(target_path, upload).replace("\\", "/")
                _helpers._save_pulsante_ui_meta(pid, {"card_image": saved_path})
                if old_value and _helpers._normalize_media_storage_path(old_value) != _helpers._normalize_media_storage_path(saved_path):
                    _helpers._delete_card_image_file(old_value)
        except Exception as exc:
            return _helpers._json_error(f"Errore salvataggio immagine: {exc}")

        return JsonResponse({
            "ok": True,
            "pulsante_id": pid,
            "card_image": saved_path,
            "card_image_url": _helpers._card_image_public_url(saved_path),
        })

    payload = _helpers._post_or_json_payload(request)
    pid = _helpers._int_or_none(payload.get("pulsante_id") or payload.get("id"))
    if not pid:
        return _helpers._json_error("ID pulsante mancante.")
    if not Pulsante.objects.filter(id=pid).exists():
        return _helpers._json_error("Pulsante non trovato.", status=404)

    remove = _helpers._bool_from_any(payload.get("remove"))
    old_value = _helpers._card_image_raw_value(pid)
    new_value = None if remove else _helpers._clean_card_image_value(payload.get("card_image"))
    try:
        with transaction.atomic():
            _helpers._save_pulsante_ui_meta(pid, {"card_image": new_value})
            if remove and old_value:
                _helpers._delete_card_image_file(old_value)
    except Exception as exc:
        return _helpers._json_error(f"Errore aggiornamento immagine: {exc}")

    return JsonResponse({
        "ok": True,
        "pulsante_id": pid,
        "card_image": new_value or "",
        "card_image_url": _helpers._card_image_public_url(new_value),
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_module_card_image(request):
    """Applica un logo/immagine dashboard a tutti i pulsanti di uno stesso modulo."""
    if request.FILES:
        modulo = str(request.POST.get("module") or request.POST.get("modulo") or "").strip()
        upload = request.FILES.get("image")
        if not modulo:
            return _helpers._json_error("Modulo mancante.")
        if upload is None:
            return _helpers._json_error("File immagine mancante.")
        try:
            # SEC (audit A9): estensione + MIME reale (magic), niente SVG/HTML su /media/.
            validate_extension_and_mime(
                upload,
                allowed_extensions=_RASTER_IMAGE_EXTENSIONS,
                allowed_mimes=_RASTER_IMAGE_MIMES,
                label="Immagine",
            )
        except UploadMimeValidationError as exc:
            return _helpers._json_error(str(exc))

        _helpers.pulsanti = list(Pulsante.objects.filter(modulo__iexact=modulo).order_by("id"))
        if not _helpers.pulsanti:
            return _helpers._json_error("Nessun pulsante trovato per il modulo indicato.", status=404)

        base_name, ext = os.path.splitext(str(getattr(upload, "name", "") or modulo))
        if not ext:
            ext = ".png"
        safe_module = slugify(modulo) or "modulo"
        safe_name = slugify(base_name) or safe_module
        unique_suffix = timezone.now().strftime("%Y%m%d%H%M%S%f")
        target_path = f"dashboard/modules/{safe_module}/{safe_name}-{unique_suffix}{ext.lower()}"

        try:
            with transaction.atomic():
                saved_path = default_storage.save(target_path, upload).replace("\\", "/")
                for pulsante in _helpers.pulsanti:
                    _helpers._save_pulsante_ui_meta(int(pulsante.id), {"card_image": saved_path})
                _helpers._audit_safe(
                    request,
                    "module_logo_upload",
                    "admin_portale",
                    {"modulo": modulo, "updated": len(_helpers.pulsanti), "card_image": saved_path},
                )
        except Exception as exc:
            return _helpers._json_error(f"Errore salvataggio immagine modulo: {exc}")

        return JsonResponse({
            "ok": True,
            "module": modulo,
            "updated": len(_helpers.pulsanti),
            "card_image": saved_path,
            "card_image_url": _helpers._card_image_public_url(saved_path),
        })

    payload = _helpers._post_or_json_payload(request)
    modulo = str(payload.get("module") or payload.get("modulo") or "").strip()
    if not modulo:
        return _helpers._json_error("Modulo mancante.")
    remove = _helpers._bool_from_any(payload.get("remove"))
    if not remove:
        return _helpers._json_error("Operazione non valida.")

    _helpers.pulsanti = list(Pulsante.objects.filter(modulo__iexact=modulo).order_by("id"))
    if not _helpers.pulsanti:
        return _helpers._json_error("Nessun pulsante trovato per il modulo indicato.", status=404)
    try:
        with transaction.atomic():
            for pulsante in _helpers.pulsanti:
                _helpers._save_pulsante_ui_meta(int(pulsante.id), {"card_image": None})
            _helpers._audit_safe(
                request,
                "module_logo_remove",
                "admin_portale",
                {"modulo": modulo, "updated": len(_helpers.pulsanti)},
            )
    except Exception as exc:
        return _helpers._json_error(f"Errore rimozione immagine modulo: {exc}")

    return JsonResponse({
        "ok": True,
        "module": modulo,
        "updated": len(_helpers.pulsanti),
        "card_image": "",
        "card_image_url": "",
    })


# ---------------------------------------------------------------------------
# CATALOGO MODULI â€” crea tutti i pulsanti di un modulo + auto-permessi
# ---------------------------------------------------------------------------


@legacy_admin_required
@csrf_protect
@require_POST
def api_modulo_crea_da_catalog(request):
    """Crea i pulsanti mancanti per un modulo del catalogo + inizializza permessi per tutti i ruoli.
    Payload: {"modulo_key": "portale_esterno"}
    Risposta: {"ok": true, "modulo": ..., "created_buttons": N, "created_permessi": N}
    """
    payload = _helpers._json_payload(request)
    modulo_key = str(payload.get("modulo_key") or "").strip()
    if not modulo_key or modulo_key not in _helpers.MODULE_CATALOG:
        return _helpers._json_error(f"Modulo '{modulo_key}' non trovato nel catalogo.")

    module_def = _helpers.MODULE_CATALOG[modulo_key]
    try:
        # Controlla per codice globalmente: la UNIQUE KEY DB Ã¨ su 'codice' (non su modulo+codice)
        existing_codici = {
            (p.codice or "").strip().lower()
            for p in Pulsante.objects.all()
        }
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore lettura pulsanti: {exc}")

    created_buttons = 0
    created_permessi = 0
    try:
        with transaction.atomic():
            for btn_def in module_def["buttons"]:
                if btn_def["codice"].lower() in existing_codici:
                    continue
                pulsante = Pulsante.objects.create(
                    codice=btn_def["codice"],
                    nome_visibile=btn_def.get("nome_visibile"),
                    modulo=modulo_key,
                    url=btn_def["url"],
                    icona=btn_def.get("icona"),
                )
                _helpers._save_pulsante_ui_meta(int(pulsante.id), btn_def)
                created_permessi += _helpers._ensure_permessi_for_button(modulo_key, btn_def["codice"])
                created_buttons += 1
            _helpers._schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}")

    return JsonResponse({
        "ok": True,
        "modulo": modulo_key,
        "created_buttons": created_buttons,
        "created_permessi": created_permessi,
    })


# ---------------------------------------------------------------------------
# WIZARD PULSANTE â€” creazione guidata pulsante + UI meta + permessi in un passo
# ---------------------------------------------------------------------------

def _wizard_context() -> dict:
    """Dati di contesto condivisi per la pagina wizard."""
    try:
        ruoli = list(Ruolo.objects.all().order_by("nome").values("id", "nome"))
    except DatabaseError:
        ruoli = []

    try:
        moduli_esistenti = sorted(
            {m for m in Pulsante.objects.values_list("modulo", flat=True) if m},
            key=str.lower,
        )
    except DatabaseError:
        moduli_esistenti = []

    default_slot_options = ["topbar", "toolbar", "sidebar", "page", "widget", "modal", "hidden"]
    default_section_options = [
        "toolbar", "dashboard", "gestione_assenze", "calendario_assenze",
        "richiesta_assenza", "richieste", "gestione_anomalie",
        "admin", "admin_utenti", "admin_permessi", "admin_pulsanti", "admin_automazioni",
    ]
    default_icon_options = [
        "home", "dashboard", "layout-dashboard", "calendar", "calendar-x", "user", "users",
        "id-card", "shield", "shield-check", "lock", "settings", "list", "list-todo",
        "alert", "triangle-alert", "octagon-alert", "newspaper", "scan", "package",
        "ticket", "clipboard-list", "file-check", "file-text", "briefcase", "clock",
        "recycle", "workflow", "wrench", "siren", "key-round",
    ]

    return {
        "ruoli": ruoli,
        "moduli_esistenti": moduli_esistenti,
        "route_catalog": _helpers._route_catalog(),
        "ui_slot_options": default_slot_options,
        "ui_section_options": default_section_options,
        "icon_options": default_icon_options,
    }


@legacy_admin_required
@require_GET
def wizard_pulsante(request):
    """Pagina wizard step-by-step per creare un pulsante con permessi."""
    return render(request, "admin_portale/pages/wizard_pulsante.html", _wizard_context())


@legacy_admin_required
@csrf_protect
@require_POST
def api_wizard_pulsante_submit(request):
    """
    POST JSON:
    {
      "pulsante": {codice, nome_visibile, modulo, url, icona},
      "ui_meta": {ui_slot, ui_section, ui_order, visible_topbar, enabled},
      "permessi": [{ruolo_id, can_view, can_edit, can_delete, can_approve}, ...]
    }
    Risposta: {"ok": True, "pulsante_id": N, "created": bool, "permessi_salvati": K}
    """
    payload = _helpers._json_payload(request)

    # --- Validazione sezione pulsante ---
    p_data = payload.get("pulsante")
    if not isinstance(p_data, dict):
        return _helpers._json_error("Sezione 'pulsante' mancante o non valida.")

    codice = str(p_data.get("codice") or "").strip()
    modulo = str(p_data.get("modulo") or "").strip()
    url_val = str(p_data.get("url") or "").strip()
    nome_visibile = str(p_data.get("nome_visibile") or "").strip() or None
    icona = str(p_data.get("icona") or "").strip() or None

    if not codice:
        return _helpers._json_error("Il campo 'codice' Ã¨ obbligatorio.")
    if len(codice) > 100:
        return _helpers._json_error("'codice' non puÃ² superare 100 caratteri.")
    if not modulo:
        return _helpers._json_error("Il campo 'modulo' (sezione) Ã¨ obbligatorio.")
    if len(modulo) > 100:
        return _helpers._json_error("'modulo' non puÃ² superare 100 caratteri.")
    if not url_val:
        return _helpers._json_error("Il campo 'url' Ã¨ obbligatorio.")
    # Normalizza: se non Ã¨ route:, django:, http:, https: â†’ prefissa con /
    if not (url_val.startswith(("route:", "django:", "http://", "https://", "/"))):
        url_val = "/" + url_val

    # --- Validazione sezione ui_meta ---
    ui_meta = payload.get("ui_meta")
    if not isinstance(ui_meta, dict):
        ui_meta = {}

    # --- Validazione sezione permessi ---
    permessi_raw = payload.get("permessi")
    if not isinstance(permessi_raw, list):
        permessi_raw = []

    ruoli_validi = set()
    try:
        ruoli_validi = {int(r.id) for r in Ruolo.objects.all()}
    except DatabaseError:
        pass

    permessi_clean = []
    for item in permessi_raw:
        if not isinstance(item, dict):
            continue
        ruolo_id = _helpers._int_or_none(item.get("ruolo_id"))
        if ruolo_id is None or ruolo_id not in ruoli_validi:
            continue
        permessi_clean.append({
            "ruolo_id": ruolo_id,
            "can_view": 1 if _helpers._bool_from_any(item.get("can_view")) else 0,
            "can_edit": 1 if _helpers._bool_from_any(item.get("can_edit")) else 0,
            "can_delete": 1 if _helpers._bool_from_any(item.get("can_delete")) else 0,
            "can_approve": 1 if _helpers._bool_from_any(item.get("can_approve")) else 0,
        })

    # --- Salvataggio atomico ---
    try:
        with transaction.atomic():
            pulsante, created = Pulsante.objects.update_or_create(
                codice=codice,
                defaults={
                    "nome_visibile": nome_visibile,
                    "modulo": modulo,
                    "url": url_val,
                    "icona": icona,
                },
            )
            pid = int(pulsante.id)
            _helpers._save_pulsante_ui_meta(pid, ui_meta)

            permessi_salvati = 0
            for perm_data in permessi_clean:
                perm = _helpers._get_or_create_permesso(perm_data["ruolo_id"], modulo, codice)
                perm.can_view = perm_data["can_view"]
                perm.can_edit = perm_data["can_edit"]
                perm.can_delete = perm_data["can_delete"]
                perm.can_approve = perm_data["can_approve"]
                if hasattr(perm, "consentito"):
                    perm.consentito = perm_data["can_view"]
                perm.save()
                permessi_salvati += 1

            # Garantisci records (can_view=0) per i ruoli non specificati nel wizard
            ruoli_nel_wizard = {p["ruolo_id"] for p in permessi_clean}
            for ruolo in Ruolo.objects.all():
                if int(ruolo.id) not in ruoli_nel_wizard:
                    _helpers._get_or_create_permesso(int(ruolo.id), modulo, codice)

            _helpers._schedule_legacy_acl_cache_invalidation()

    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)

    return JsonResponse({
        "ok": True,
        "pulsante_id": pid,
        "created": created,
        "permessi_salvati": permessi_salvati,
    })


# ---------------------------------------------------------------------------
# DASHBOARD â€” toggle visibilitÃ  modulo (enabled in ui_pulsanti_meta)
# ---------------------------------------------------------------------------

def _set_pulsante_meta_enabled(pulsante_id: int, enabled: bool) -> None:
    """Aggiorna solo il flag enabled in ui_pulsanti_meta senza toccare gli altri campi."""
    _helpers._ensure_pulsanti_ui_meta_table()
    val = 1 if enabled else 0
    with connections["default"].cursor() as cursor:
        vendor = connections["default"].vendor
        if vendor == "sqlite":
            cursor.execute(
                """
                INSERT INTO ui_pulsanti_meta (pulsante_id, enabled, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(pulsante_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [pulsante_id, val],
            )
        else:
            cursor.execute(
                """
                MERGE ui_pulsanti_meta AS t
                USING (SELECT %s AS pulsante_id) AS s ON t.pulsante_id = s.pulsante_id
                WHEN MATCHED THEN UPDATE SET enabled = %s, updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (pulsante_id, enabled, updated_at) VALUES (%s, %s, SYSUTCDATETIME());
                """,
                [pulsante_id, val, pulsante_id, val],
            )


@legacy_admin_required
@csrf_protect
@require_POST
def api_pulsanti_set_enabled(request):
    """POST {pulsante_id, enabled} â€” imposta solo il flag enabled nel meta UI."""
    payload = _helpers._post_or_json_payload(request)
    pid = _helpers._int_or_none(payload.get("pulsante_id") or payload.get("id"))
    enabled = _helpers._bool_from_any(payload.get("enabled"))
    if not pid:
        return _helpers._json_error("pulsante_id mancante.")
    if not Pulsante.objects.filter(id=pid).exists():
        return _helpers._json_error("Pulsante non trovato.", status=404)
    try:
        with transaction.atomic():
            _set_pulsante_meta_enabled(pid, enabled)
            _helpers._schedule_legacy_acl_cache_invalidation()
    except DatabaseError as exc:
        return _helpers._json_error(f"Errore DB: {exc}", status=500)
    return JsonResponse({"ok": True, "pulsante_id": pid, "enabled": enabled})
