from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from core.acl import user_can_modulo_action
from core.legacy_models import Permesso, Pulsante
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns

MAX_LAYOUT_MODULES = 300
ALLOWED_STATS_KEYS = {"total", "approved", "rejected", "pending"}


@dataclass
class RichiestaRow:
    tipo: str
    motivazione: str
    inizio: str
    fine: str
    stato: str
    creata: str


def _format_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _normalize_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if "approv" in text or "approved" in text:
        return "Approvato"
    if "rifiut" in text or "reject" in text:
        return "Rifiutato"
    return "In attesa"


def _normalize_int_list(value: Any, *, max_items: int) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for raw in value:
        try:
            num = int(raw)
        except (TypeError, ValueError):
            continue
        if num in seen:
            continue
        seen.add(num)
        out.append(num)
        if len(out) >= max_items:
            break
    return out


def _normalize_stats_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        key = str(raw or "").strip().lower()
        if not key or key in seen or key not in ALLOWED_STATS_KEYS:
            continue
        seen.add(key)
        out.append(key)
    return out


def _sanitize_dashboard_layout(value: Any) -> dict[str, list]:
    payload = value if isinstance(value, dict) else {}
    return {
        "module_order": _normalize_int_list(payload.get("module_order"), max_items=MAX_LAYOUT_MODULES),
        "stats_order": _normalize_stats_order(payload.get("stats_order")),
    }


def _layout_is_empty(layout: dict[str, list]) -> bool:
    return not layout.get("module_order") and not layout.get("stats_order")


def _load_user_dashboard_layout(legacy_user_id: int | None) -> dict[str, list]:
    if not legacy_user_id:
        return {"module_order": [], "stats_order": []}
    try:
        from core.models import UserDashboardLayout

        row = UserDashboardLayout.objects.filter(legacy_user_id=legacy_user_id).first()
    except Exception:
        return {"module_order": [], "stats_order": []}
    if not row:
        return {"module_order": [], "stats_order": []}
    return _sanitize_dashboard_layout(getattr(row, "layout", {}))


def _card_image_public_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return raw
    if raw.startswith("/"):
        return raw
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not media_url.endswith("/"):
        media_url += "/"
    return media_url + raw.lstrip("/")


def _map_legacy_url(url_value: str) -> str:
    raw = (url_value or "").strip() or "/"
    path = raw.lower()
    if path in {"/", "/dashboard"}:
        return reverse("dashboard_home")
    if path.startswith("/assenze"):
        return reverse("coming_assenze")
    if "anom" in path:
        return reverse("anomalie_menu")
    if path.startswith("/admin"):
        return reverse("admin_portale:index")
    return reverse("coming_admin")


def _visible_pulsanti_for_request(request) -> list[Pulsante]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user or not legacy_user.ruolo_id:
        return []
    try:
        is_admin = is_legacy_admin(legacy_user)
        if is_admin:
            return list(Pulsante.objects.all().order_by("modulo", "id"))

        perms = Permesso.objects.filter(ruolo_id=legacy_user.ruolo_id)
        perm_map = {
            ((p.modulo or "").strip().lower(), (p.azione or "").strip().lower()): (
                bool(p.can_view) or bool(p.consentito)
            )
            for p in perms
        }
        visible = []
        for puls in Pulsante.objects.all().order_by("modulo", "id"):
            key = ((puls.modulo or "").strip().lower(), (puls.codice or "").strip().lower())
            if perm_map.get(key):
                visible.append(puls)
        return visible
    except DatabaseError:
        return []


def _ensure_is_padre_column() -> None:
    """Aggiunge is_padre a ui_pulsanti_meta se non esiste ancora."""
    try:
        vendor = connections["default"].vendor
        with connections["default"].cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute("PRAGMA table_info(ui_pulsanti_meta)")
                cols = {str(row[1]).strip().lower() for row in cursor.fetchall() if len(row) > 1}
                if "is_padre" not in cols:
                    cursor.execute("ALTER TABLE ui_pulsanti_meta ADD COLUMN is_padre INTEGER NOT NULL DEFAULT 0")
            else:
                cursor.execute("SELECT COL_LENGTH('ui_pulsanti_meta', 'is_padre')")
                row = cursor.fetchone()
                if not row or row[0] is None:
                    cursor.execute("ALTER TABLE ui_pulsanti_meta ADD is_padre BIT NOT NULL DEFAULT 0")
    except Exception:
        pass


def _pulsanti_ui_meta_map() -> dict[int, dict[str, Any]]:
    """Restituisce i metadati UI necessari alla dashboard da ui_pulsanti_meta."""
    _ensure_is_padre_column()
    result: dict[int, dict[str, Any]] = {}
    try:
        with connections["default"].cursor() as cursor:
            try:
                cursor.execute("SELECT pulsante_id, enabled, ui_order, card_image, is_padre FROM ui_pulsanti_meta")
                rows = cursor.fetchall()
            except Exception:
                try:
                    cursor.execute("SELECT pulsante_id, enabled, ui_order, card_image FROM ui_pulsanti_meta")
                    rows = [(*r, 0) for r in cursor.fetchall()]
                except Exception:
                    cursor.execute("SELECT pulsante_id, enabled, ui_order FROM ui_pulsanti_meta")
                    rows = [(*r, "", 0) for r in cursor.fetchall()]
    except Exception:
        return result

    for row in rows:
        try:
            pid = int(row[0])
        except Exception:
            continue
        enabled_raw = row[1] if len(row) > 1 else True
        enabled = bool(enabled_raw) if enabled_raw is not None else True
        try:
            ui_order = int(row[2]) if row[2] is not None else None
        except Exception:
            ui_order = None
        card_image = str(row[3] or "").strip() if len(row) > 3 else ""
        is_padre_raw = row[4] if len(row) > 4 else False
        is_padre = bool(is_padre_raw) if is_padre_raw is not None else False
        result[pid] = {
            "enabled": enabled,
            "ui_order": ui_order,
            "card_image": card_image,
            "is_padre": is_padre,
        }
    return result


def _user_dashboard_hidden_ids(legacy_user_id: int | None) -> set[int]:
    """Restituisce i pulsante_id nascosti per questo utente tramite UserDashboardConfig."""
    if not legacy_user_id:
        return set()
    try:
        from core.models import UserDashboardConfig

        return {
            row.pulsante_id
            for row in UserDashboardConfig.objects.filter(legacy_user_id=legacy_user_id, visible=False)
        }
    except Exception:
        return set()


def _user_hidden_modules(legacy_user_id: int | None) -> set[str]:
    """Restituisce i moduli (lowercase) nascosti per questo utente tramite UserModuleVisibility."""
    if not legacy_user_id:
        return set()
    try:
        from core.models import UserModuleVisibility

        return {
            row.modulo.lower()
            for row in UserModuleVisibility.objects.filter(legacy_user_id=legacy_user_id, visible=False)
        }
    except Exception:
        return set()


def _order_cards_by_user_layout(cards: list[dict], ordered_ids: list[int]) -> list[dict]:
    if not ordered_ids:
        return cards

    by_id = {int(c.get("pulsante_id")): c for c in cards}
    used: set[int] = set()
    out: list[dict] = []

    for pid in ordered_ids:
        row = by_id.get(pid)
        if not row:
            continue
        out.append(row)
        used.add(pid)

    for card in cards:
        pid = int(card.get("pulsante_id") or 0)
        if pid in used:
            continue
        out.append(card)
    return out


def _module_cards(
    pulsanti: list[Pulsante],
    ui_meta_map: dict[int, dict[str, Any]] | None = None,
    legacy_user_id: int | None = None,
    saved_module_ids: list[int] | None = None,
) -> list[dict]:
    ui_meta_map = ui_meta_map or {}
    hidden_ids = _user_dashboard_hidden_ids(legacy_user_id)
    hidden_modules = _user_hidden_modules(legacy_user_id)
    # IDs che l'utente ha esplicitamente aggiunto alla sua dashboard (anche se non padre)
    forced_ids: set[int] = set(saved_module_ids or [])
    cards: list[dict] = []
    seen: set[str] = set()

    for puls in pulsanti:
        key = (puls.codice or puls.label or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)

        pid = int(puls.id)
        modulo_display = (puls.modulo or "Generale").strip() or "Generale"
        modulo_norm = modulo_display.lower()

        meta = ui_meta_map.get(pid, {})
        if not meta.get("enabled", True):
            continue
        if modulo_norm in hidden_modules:
            continue

        # Mostra solo moduli padre, a meno che l'utente non li abbia esplicitamente
        # aggiunti alla propria dashboard (saved_module_ids)
        is_padre = meta.get("is_padre", False)
        if not is_padre and pid not in forced_ids:
            continue

        # hidden_ids (UserDashboardConfig visible=False) si applica solo ai moduli
        # aggiunti manualmente dall'utente (non-padre); i moduli padre sono sempre visibili
        if not is_padre and pid in hidden_ids:
            continue

        cards.append(
            {
                "pulsante_id": pid,
                "name": puls.label,
                "module": modulo_display,
                "href": _map_legacy_url(puls.url or "/"),
                "legacy_url": (puls.url or "").strip() or "/",
                "global_order": meta.get("ui_order"),
                "image_url": _card_image_public_url(meta.get("card_image") or ""),
            }
        )

    cards.sort(
        key=lambda c: (
            c.get("global_order") is None,
            c.get("global_order") if c.get("global_order") is not None else 999999,
            str(c.get("module") or "").lower(),
            str(c.get("name") or "").lower(),
            int(c.get("pulsante_id") or 0),
        )
    )
    return cards


def _load_richieste_from_local_db(request) -> list[RichiestaRow]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return []

    try:
        cols = legacy_table_columns("assenze")
        if not cols:
            return []

        required = {"copia_nome", "tipo_assenza", "data_inizio", "data_fine", "consenso", "created_datetime"}
        if not required.issubset(cols):
            return []

        where_sql = "UPPER(COALESCE(copia_nome, '')) = UPPER(%s)"
        params: list[Any] = [legacy_user.nome or ""]
        if "email_esterna" in cols and legacy_user.email:
            where_sql = f"({where_sql} OR UPPER(COALESCE(email_esterna, '')) = UPPER(%s))"
            params.append(legacy_user.email)

        sql = f"""
            SELECT
                tipo_assenza,
                motivazione_richiesta,
                data_inizio,
                data_fine,
                consenso,
                created_datetime
            FROM assenze
            WHERE {where_sql}
            ORDER BY created_datetime DESC
        """
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        result: list[RichiestaRow] = []
        for row in rows:
            result.append(
                RichiestaRow(
                    tipo=str(row[0] or ""),
                    motivazione=str(row[1] or ""),
                    inizio=_format_dt(row[2]),
                    fine=_format_dt(row[3]),
                    stato=_normalize_status(row[4]),
                    creata=_format_dt(row[5]),
                )
            )
        return result
    except DatabaseError:
        return []


def _all_permitted_pulsanti_for_request(request, ui_meta_map: dict[int, dict[str, Any]]) -> list[dict]:
    """Tutti i pulsanti visibili per ruolo, inclusi quelli nascosti dal singolo utente."""
    pulsanti = _visible_pulsanti_for_request(request)
    seen: set[str] = set()
    result = []

    for p in pulsanti:
        key = (p.codice or p.label or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)

        pid = int(p.id)
        meta = ui_meta_map.get(pid, {})
        if not meta.get("enabled", True):
            continue
        # Nel pannello "aggiungi/riabilita" mostra solo i moduli padre
        if not meta.get("is_padre", False):
            continue

        result.append(
            {
                "pulsante_id": pid,
                "name": p.label,
                "module": (p.modulo or "Generale").strip() or "Generale",
                "href": _map_legacy_url(p.url or "/"),
                "image_url": _card_image_public_url(meta.get("card_image") or ""),
                "global_order": meta.get("ui_order"),
            }
        )

    result.sort(
        key=lambda c: (
            c.get("global_order") is None,
            c.get("global_order") if c.get("global_order") is not None else 999999,
            str(c.get("module") or "").lower(),
            str(c.get("name") or "").lower(),
        )
    )
    return result


def _ordered_stats_cards(counts: Counter, user_layout: dict[str, list]) -> list[dict[str, Any]]:
    cards = [
        {"key": "total", "icon": "#", "icon_class": "blue", "value": counts.get("_total", 0), "label": "Richieste totali"},
        {"key": "approved", "icon": "OK", "icon_class": "green", "value": counts.get("Approvato", 0), "label": "Approvate"},
        {"key": "rejected", "icon": "X", "icon_class": "red", "value": counts.get("Rifiutato", 0), "label": "Rifiutate"},
        {"key": "pending", "icon": "...", "icon_class": "yellow", "value": counts.get("In attesa", 0), "label": "In attesa"},
    ]

    order = user_layout.get("stats_order") or []
    if not order:
        return cards

    by_key = {c["key"]: c for c in cards}
    out = []
    used: set[str] = set()
    for key in order:
        card = by_key.get(key)
        if not card:
            continue
        out.append(card)
        used.add(key)
    for card in cards:
        if card["key"] in used:
            continue
        out.append(card)
    return out


def _base_dashboard_context(request) -> dict[str, Any]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = request.user.get_full_name() or getattr(legacy_user, "nome", "") or request.user.get_username()
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)

    legacy_user_id = int(legacy_user.id) if legacy_user else None
    user_layout = _load_user_dashboard_layout(legacy_user_id)

    pulsanti = _visible_pulsanti_for_request(request)
    ui_meta_map = _pulsanti_ui_meta_map()
    saved_module_ids = user_layout.get("module_order") or []
    module_cards = _module_cards(pulsanti, ui_meta_map, legacy_user_id=legacy_user_id, saved_module_ids=saved_module_ids)
    module_cards = _order_cards_by_user_layout(module_cards, saved_module_ids)

    richieste = _load_richieste_from_local_db(request)
    counts = Counter(r.stato for r in richieste)
    counts["_total"] = len(richieste)

    admin_all_modules: list[dict] = []
    if is_admin:
        try:
            all_pulsanti = list(Pulsante.objects.all().order_by("modulo", "id"))
        except Exception:
            all_pulsanti = []
        seen: set[str] = set()
        for p in all_pulsanti:
            key = (p.codice or p.label or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            pid = int(p.id)
            meta = ui_meta_map.get(pid, {})
            admin_all_modules.append(
                {
                    "pulsante_id": pid,
                    "name": p.label,
                    "module": (p.modulo or "Generale").strip() or "Generale",
                    "href": _map_legacy_url(p.url or "/"),
                    "enabled": meta.get("enabled", True),
                    "global_order": meta.get("ui_order"),
                    "image_url": _card_image_public_url(meta.get("card_image") or ""),
                }
            )
        admin_all_modules.sort(
            key=lambda c: (
                c.get("global_order") is None,
                c.get("global_order") if c.get("global_order") is not None else 999999,
                str(c.get("module") or "").lower(),
                str(c.get("name") or "").lower(),
            )
        )

    ctx_widget: dict = {"tipo": "operaio"}
    try:
        ruolo = (getattr(legacy_user, "ruolo", "") or "").strip().upper()
        if ruolo in ("CAR", "CAPO REPARTO") and legacy_user_id:
            from assenze.views import _load_pending_for_manager

            pending = _load_pending_for_manager(legacy_user_id)
            ctx_widget = {"tipo": "car", "pending_list": pending[:5], "pending_count": len(pending)}
        elif ruolo in ("AMMINISTRAZIONE", "ADMIN") or is_admin:
            from assenze.views import _load_all_pending

            pending = _load_all_pending(limit=5)
            ctx_widget = {"tipo": "admin", "pending_list": pending, "pending_count": len(pending)}
        else:
            from assenze.views import _load_personal

            nome = getattr(legacy_user, "nome", "") or ""
            email = getattr(legacy_user, "email", "") or ""
            personale = _load_personal(nome, email, limit=1)
            ultima = personale[0] if personale else None
            ctx_widget = {"tipo": "operaio", "ultima_richiesta": ultima}
    except Exception:
        pass

    return {
        "page_title": "Dashboard",
        "display_name": display_name,
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "module_cards": module_cards,
        "stats_cards": _ordered_stats_cards(counts, user_layout),
        "all_my_pulsanti": _all_permitted_pulsanti_for_request(request, ui_meta_map),
        "admin_all_modules": admin_all_modules,
        "richieste_total": len(richieste),
        "richieste_approvate": counts.get("Approvato", 0),
        "richieste_rifiutate": counts.get("Rifiutato", 0),
        "richieste_attesa": counts.get("In attesa", 0),
        "richieste_recenti": richieste[:5],
        "ctx_widget": ctx_widget,
        "dashboard_layout": user_layout,
    }


@login_required
def dashboard_home(request):
    context = _base_dashboard_context(request)
    return render(request, "dashboard/pages/dashboard.html", context)


@login_required
def richieste(request):
    context = _base_dashboard_context(request)
    context["page_title"] = "Richieste"
    context["richieste_list"] = _load_richieste_from_local_db(request)
    return render(request, "dashboard/pages/richieste.html", context)


def _anomalie_access_flags(request) -> dict[str, bool]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return {
        "can_view_anomalie_list": bool(user_can_modulo_action(request, "anomalie", "anomalie_aperte")),
        "can_create_anomalie": bool(user_can_modulo_action(request, "anomalie", "inserimento_anomalie")),
        "can_manage_anomalie_config": bool(
            request.user.is_superuser or (legacy_user and is_legacy_admin(legacy_user))
        ),
    }


@login_required
def anomalie_menu(request):
    access_flags = _anomalie_access_flags(request)
    context = {
        "user": request.user,
        "sp_folder_url": settings.ANOMALIE_SP_FOLDER_URL,
        **access_flags,
    }
    return render(request, "dashboard/pages/anomalie_menu.html", context)


@login_required
@csrf_protect
@require_POST
def api_my_dashboard_toggle(request):
    """Imposta visibilita di un pulsante nella dashboard dell'utente corrente."""
    from core.models import UserDashboardConfig

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=400)

    try:
        payload = json.loads(request.body)
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Payload non valido."}, status=400)

    pid_raw = payload.get("pulsante_id")
    visible_raw = payload.get("visible")
    if pid_raw is None or visible_raw is None:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    try:
        pulsante_id = int(pid_raw)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "pulsante_id non valido."}, status=400)

    bool_visible = bool(visible_raw)
    try:
        if bool_visible:
            UserDashboardConfig.objects.filter(
                legacy_user_id=int(legacy_user.id), pulsante_id=pulsante_id
            ).delete()
        else:
            UserDashboardConfig.objects.update_or_create(
                legacy_user_id=int(legacy_user.id),
                pulsante_id=pulsante_id,
                defaults={"visible": False},
            )
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@csrf_protect
@require_POST
def api_my_dashboard_layout(request):
    """Salva ordine moduli/statistiche della dashboard utente."""
    from core.models import UserDashboardLayout

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=400)

    try:
        payload = json.loads(request.body or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Payload non valido."}, status=400)

    has_module_order = "module_order" in payload
    has_stats_order = "stats_order" in payload
    if not has_module_order and not has_stats_order:
        return JsonResponse({"ok": False, "error": "Nessun campo layout da salvare."}, status=400)

    user_id = int(legacy_user.id)
    current = _load_user_dashboard_layout(user_id)
    updated = {
        "module_order": list(current.get("module_order") or []),
        "stats_order": list(current.get("stats_order") or []),
    }

    if has_module_order:
        updated["module_order"] = _normalize_int_list(payload.get("module_order"), max_items=MAX_LAYOUT_MODULES)
    if has_stats_order:
        updated["stats_order"] = _normalize_stats_order(payload.get("stats_order"))

    try:
        if _layout_is_empty(updated):
            UserDashboardLayout.objects.filter(legacy_user_id=user_id).delete()
            return JsonResponse({"ok": True, "layout": {"module_order": [], "stats_order": []}})

        UserDashboardLayout.objects.update_or_create(
            legacy_user_id=user_id,
            defaults={"layout": updated},
        )
        return JsonResponse({"ok": True, "layout": updated})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ── Employee Board ─────────────────────────────────────────────────────────────

EMPLOYEE_BOARD_WIDGETS = [
    {
        "id": "profilo",
        "title": "Profilo",
        "icon": "👤",
        "description": "Informazioni anagrafiche del dipendente",
        "default_params": {"show_reparto": True, "show_mansione": True, "show_contatti": True},
    },
    {
        "id": "tasks_stats",
        "title": "Riepilogo Task",
        "icon": "📊",
        "description": "Contatori rapidi: todo, in corso, completati, scaduti",
        "default_params": {"show_overdue": True, "show_done": True},
    },
    {
        "id": "tasks_assegnati",
        "title": "Task Assegnati",
        "icon": "✅",
        "description": "Lista task aperti assegnati all'utente",
        "default_params": {"max_items": 10, "show_priority": True, "show_project": True, "filter_status": "open"},
    },
    {
        "id": "assenze_future",
        "title": "Assenze Programmate",
        "icon": "📅",
        "description": "Assenze future approvate/programmate",
        "default_params": {"max_items": 8, "show_tipo": True, "show_motivazione": False},
    },
    {
        "id": "assenze_da_approvare",
        "title": "Assenze da Approvare",
        "icon": "🔔",
        "description": "Assenze in attesa di approvazione (solo CAR/admin)",
        "default_params": {"max_items": 8},
        "role_required": ["car", "capo reparto", "amministrazione", "admin"],
    },
    {
        "id": "progetti_capo",
        "title": "Progetti (come Capo Commessa)",
        "icon": "🏗️",
        "description": "Progetti dove sei capo commessa",
        "default_params": {"max_items": 8, "show_manager": True},
        "role_required": ["capo commessa", "capo_commessa", "admin"],
    },
    {
        "id": "anomalie_gestione",
        "title": "Anomalie da Gestire",
        "icon": "⚠️",
        "description": "Anomalie aperte (visibili a capo commessa e CAR/admin)",
        "default_params": {"max_items": 8, "solo_aperte": True},
        "role_required": ["capo commessa", "capo_commessa", "car", "capo reparto", "amministrazione", "admin"],
    },
    {
        "id": "notifiche",
        "title": "Notifiche",
        "icon": "🔔",
        "description": "Ultime notifiche non lette",
        "default_params": {"max_items": 6, "solo_non_lette": False},
    },
]

EMPLOYEE_BOARD_DEFAULT_LAYOUT = [
    "profilo", "tasks_stats", "tasks_assegnati", "assenze_future",
    "assenze_da_approvare", "anomalie_gestione", "progetti_capo", "notifiche",
]

_ALLOWED_WIDGET_IDS = {w["id"] for w in EMPLOYEE_BOARD_WIDGETS}
MAX_BOARD_WIDGET_ITEMS = 50


def _load_employee_board_config(legacy_user_id: int | None) -> dict:
    if not legacy_user_id:
        return {"layout": [], "widget_configs": {}}
    try:
        from core.models import EmployeeBoardConfig
        row = EmployeeBoardConfig.objects.filter(legacy_user_id=legacy_user_id).first()
        if not row:
            return {"layout": [], "widget_configs": {}}
        layout = row.layout if isinstance(row.layout, list) else []
        wc = row.widget_configs if isinstance(row.widget_configs, dict) else {}
        return {"layout": layout, "widget_configs": wc}
    except Exception:
        return {"layout": [], "widget_configs": {}}


def _board_ordered_widgets(
    user_layout: list,
    legacy_user: Any,
    is_admin: bool,
    widget_visibility: dict[str, bool] | None = None,
) -> list[dict]:
    ruolo = str(getattr(legacy_user, "ruolo", "") or "").strip().lower() if legacy_user else ""
    widget_visibility = widget_visibility or {}
    visible_ids: list[str] = []
    if user_layout:
        seen: set[str] = set()
        for wid in user_layout:
            s = str(wid or "").strip()
            if s in _ALLOWED_WIDGET_IDS and s not in seen:
                visible_ids.append(s)
                seen.add(s)
        # aggiungi quelli non ancora salvati in fondo
        for w in EMPLOYEE_BOARD_WIDGETS:
            if w["id"] not in seen:
                visible_ids.append(w["id"])
    else:
        visible_ids = list(EMPLOYEE_BOARD_DEFAULT_LAYOUT)

    result = []
    widget_map = {w["id"]: w for w in EMPLOYEE_BOARD_WIDGETS}
    for wid in visible_ids:
        w = widget_map.get(wid)
        if not w:
            continue
        if not widget_visibility.get(wid, True):
            continue
        roles_req = w.get("role_required")
        if roles_req and not is_admin:
            if not any(r in ruolo for r in roles_req):
                continue
        result.append(w)
    return result


def _board_data_tasks(legacy_user_id: int | None, params: dict) -> dict:
    if not legacy_user_id:
        return {"items": [], "stats": {}}
    try:
        from core.models import Profile
        from tasks.models import Task, TaskStatus

        profile = Profile.objects.filter(legacy_user_id=legacy_user_id).select_related("user").first()
        if not profile:
            return {"items": [], "stats": {}}
        user = profile.user
        qs = Task.objects.filter(assigned_to=user).select_related("project")
        filter_status = str(params.get("filter_status") or "open").lower()
        if filter_status == "open":
            qs = qs.filter(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS])
        elif filter_status == "todo":
            qs = qs.filter(status=TaskStatus.TODO)
        elif filter_status == "in_progress":
            qs = qs.filter(status=TaskStatus.IN_PROGRESS)
        max_items = min(int(params.get("max_items") or 10), MAX_BOARD_WIDGET_ITEMS)
        items = []
        for t in qs[:max_items]:
            items.append({
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "status_label": t.get_status_display(),
                "priority": t.priority,
                "priority_label": t.get_priority_display(),
                "due_date": t.due_date.strftime("%d/%m/%Y") if t.due_date else "",
                "is_overdue": t.is_overdue,
                "project": str(t.project) if t.project else "",
                "next_step": t.next_step_text or "",
            })
        # stats
        all_qs = Task.objects.filter(assigned_to=user)
        stats = {
            "todo": all_qs.filter(status=TaskStatus.TODO).count(),
            "in_progress": all_qs.filter(status=TaskStatus.IN_PROGRESS).count(),
            "done": all_qs.filter(status=TaskStatus.DONE).count(),
            "overdue": sum(1 for t in all_qs.filter(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS]) if t.is_overdue),
        }
        return {"items": items, "stats": stats}
    except Exception:
        return {"items": [], "stats": {}}


def _board_data_assenze_future(legacy_user: Any, params: dict) -> list[dict]:
    if not legacy_user:
        return []
    try:
        from datetime import date
        from django.db import connections
        from core.legacy_utils import legacy_table_columns

        cols = legacy_table_columns("assenze")
        if not cols:
            return []
        nome = getattr(legacy_user, "nome", "") or ""
        email = getattr(legacy_user, "email", "") or ""
        if not nome and not email:
            return []
        today_str = date.today().isoformat()
        clauses = []
        params_sql: list = []
        if nome:
            clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
            params_sql.append(nome)
        if email:
            clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
            params_sql.append(email)
        where = " OR ".join(clauses)
        vendor = connections["default"].vendor
        limit = min(int(params.get("max_items") or 8), MAX_BOARD_WIDGET_ITEMS)
        if vendor == "sqlite":
            sql = f"""
                SELECT tipo_assenza, data_inizio, data_fine, consenso, moderation_status, motivazione_richiesta
                FROM assenze
                WHERE ({where})
                  AND COALESCE(data_fine, data_inizio) >= '{today_str}'
                  AND COALESCE(moderation_status, 2) != 1
                ORDER BY data_inizio
                LIMIT {limit}
            """
        else:
            sql = f"""
                SELECT TOP {limit} tipo_assenza, data_inizio, data_fine, consenso, moderation_status, motivazione_richiesta
                FROM assenze
                WHERE ({where})
                  AND COALESCE(data_fine, data_inizio) >= '{today_str}'
                  AND COALESCE(moderation_status, 2) != 1
                ORDER BY data_inizio
            """
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, params_sql)
            cols_desc = [c[0] for c in cursor.description]
            rows = [dict(zip(cols_desc, r)) for r in cursor.fetchall()]

        from assenze.views import _norm_tipo, _status_from_moderation, _dt_label
        out = []
        for row in rows:
            _, label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
            out.append({
                "tipo": _norm_tipo(row.get("tipo_assenza")),
                "inizio": _dt_label(row.get("data_inizio")),
                "fine": _dt_label(row.get("data_fine")),
                "stato": label,
                "motivazione": str(row.get("motivazione_richiesta") or ""),
            })
        return out
    except Exception:
        return []


def _board_data_assenze_da_approvare(legacy_user: Any, is_admin: bool, params: dict) -> list[dict]:
    if not legacy_user:
        return []
    try:
        ruolo = str(getattr(legacy_user, "ruolo", "") or "").strip().upper()
        limit = min(int(params.get("max_items") or 8), MAX_BOARD_WIDGET_ITEMS)
        if is_admin or ruolo in ("AMMINISTRAZIONE", "ADMIN"):
            from assenze.views import _load_all_pending
            return _load_all_pending(limit=limit)
        else:
            from assenze.views import _load_pending_for_manager
            legacy_user_id = int(legacy_user.id)
            return _load_pending_for_manager(legacy_user_id, limit=limit)
    except Exception:
        return []


def _board_data_progetti(legacy_user_id: int | None, params: dict) -> list[dict]:
    if not legacy_user_id:
        return []
    try:
        from core.models import Profile
        from tasks.models import Project

        profile = Profile.objects.filter(legacy_user_id=legacy_user_id).select_related("user").first()
        if not profile:
            return []
        user = profile.user
        max_items = min(int(params.get("max_items") or 8), MAX_BOARD_WIDGET_ITEMS)
        qs = Project.objects.filter(capo_commessa=user).select_related("project_manager")[:max_items]
        out = []
        for p in qs:
            pm = p.project_manager
            out.append({
                "id": p.id,
                "name": p.name,
                "client": p.client_name or "",
                "manager": pm.get_full_name() if pm else "",
                "part_number": p.part_number or "",
            })
        return out
    except Exception:
        return []


def _board_data_anomalie(legacy_user: Any, is_admin: bool, params: dict) -> list[dict]:
    if not legacy_user:
        return []
    try:
        from core.legacy_utils import legacy_table_columns

        cols = legacy_table_columns("anomalie")
        if not cols:
            return []
        limit = min(int(params.get("max_items") or 8), MAX_BOARD_WIDGET_ITEMS)
        solo_aperte = bool(params.get("solo_aperte", True))
        nome = getattr(legacy_user, "nome", "") or ""
        vendor = connections["default"].vendor
        where_parts = []
        sql_params: list = []
        if solo_aperte:
            where_parts.append("COALESCE(chiudere, 0) = 0")
        if not is_admin and nome:
            where_parts.append("(UPPER(COALESCE(ex_op_nominativo,'')) LIKE UPPER(%s) OR UPPER(COALESCE(capo_commessa,'')) LIKE UPPER(%s))")
            sql_params.extend([f"%{nome}%", f"%{nome}%"])
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        if vendor == "sqlite":
            sql = f"SELECT id, ex_op_nominativo, seriale, avanzamento, chiudere, modified_datetime FROM anomalie {where_sql} ORDER BY id DESC LIMIT {limit}"
        else:
            sql = f"SELECT TOP {limit} id, ex_op_nominativo, seriale, avanzamento, chiudere, modified_datetime FROM anomalie {where_sql} ORDER BY id DESC"
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, sql_params)
            cols_desc = [c[0] for c in cursor.description]
            rows = [dict(zip(cols_desc, r)) for r in cursor.fetchall()]
        out = []
        for row in rows:
            out.append({
                "id": row.get("id"),
                "operatore": str(row.get("ex_op_nominativo") or ""),
                "seriale": str(row.get("seriale") or ""),
                "avanzamento": str(row.get("avanzamento") or "N/D"),
                "chiusa": bool(row.get("chiudere")),
                "modified": str(row.get("modified_datetime") or ""),
            })
        return out
    except Exception:
        return []


def _board_data_notifiche(legacy_user_id: int | None, params: dict) -> list[dict]:
    if not legacy_user_id:
        return []
    try:
        from core.models import Notifica
        max_items = min(int(params.get("max_items") or 6), MAX_BOARD_WIDGET_ITEMS)
        solo_non_lette = bool(params.get("solo_non_lette", False))
        qs = Notifica.objects.filter(legacy_user_id=legacy_user_id)
        if solo_non_lette:
            qs = qs.filter(letta=False)
        qs = qs[:max_items]
        out = []
        for n in qs:
            out.append({
                "id": n.id,
                "tipo": n.tipo,
                "tipo_label": n.get_tipo_display(),
                "messaggio": n.messaggio,
                "url": n.url_azione or "",
                "letta": n.letta,
                "data": n.created_at.strftime("%d/%m/%Y %H:%M"),
            })
        return out
    except Exception:
        return []


def _board_data_profilo(legacy_user: Any, legacy_user_id: int | None) -> dict:
    data: dict[str, Any] = {
        "nome": getattr(legacy_user, "nome", "") or "" if legacy_user else "",
        "ruolo": getattr(legacy_user, "ruolo", "") or "" if legacy_user else "",
        "mansione": "",
        "reparto": "",
        "email_notifica": "",
        "telefono": "",
        "cellulare": "",
        "macchina": "",
    }
    if not legacy_user_id:
        return data
    try:
        from core.legacy_models import AnagraficaDipendente
        ana = AnagraficaDipendente.objects.filter(utente_id=legacy_user_id).first()
        if ana:
            data["mansione"] = str(ana.mansione or "")
            data["reparto"] = str(ana.reparto or "")
            data["email_notifica"] = str(ana.email_notifica or "")
    except Exception:
        pass
    try:
        from core.models import UserExtraInfo
        extra = UserExtraInfo.objects.filter(legacy_user_id=legacy_user_id).first()
        if extra:
            if not data["reparto"]:
                data["reparto"] = str(extra.reparto or "")
            data["telefono"] = str(extra.telefono or "")
            data["cellulare"] = str(extra.cellulare or "")
            data["macchina"] = str(extra.macchina or "")
    except Exception:
        pass
    return data


@login_required
def employee_board(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    display_name = request.user.get_full_name() or getattr(legacy_user, "nome", "") or request.user.get_username()
    anomalie_access = _anomalie_access_flags(request)

    board_cfg = _load_employee_board_config(legacy_user_id)
    user_layout = board_cfg.get("layout") or []
    widget_configs = board_cfg.get("widget_configs") or {}

    ordered_widgets = _board_ordered_widgets(
        user_layout,
        legacy_user,
        is_admin,
        widget_visibility={"anomalie_gestione": anomalie_access["can_view_anomalie_list"]},
    )

    # Raccoglie dati per ogni widget
    widget_data: dict[str, Any] = {}
    for w in ordered_widgets:
        wid = w["id"]
        params = {**w.get("default_params", {}), **widget_configs.get(wid, {})}
        if wid == "profilo":
            widget_data[wid] = _board_data_profilo(legacy_user, legacy_user_id)
        elif wid == "tasks_stats":
            widget_data[wid] = _board_data_tasks(legacy_user_id, params)
        elif wid == "tasks_assegnati":
            widget_data[wid] = _board_data_tasks(legacy_user_id, params)
        elif wid == "assenze_future":
            widget_data[wid] = _board_data_assenze_future(legacy_user, params)
        elif wid == "assenze_da_approvare":
            widget_data[wid] = _board_data_assenze_da_approvare(legacy_user, is_admin, params)
        elif wid == "progetti_capo":
            widget_data[wid] = _board_data_progetti(legacy_user_id, params)
        elif wid == "anomalie_gestione":
            widget_data[wid] = _board_data_anomalie(legacy_user, is_admin, params)
        elif wid == "notifiche":
            widget_data[wid] = _board_data_notifiche(legacy_user_id, params)

    # Widget params effettivi (merge default + user)
    merged_params: dict[str, dict] = {}
    for w in EMPLOYEE_BOARD_WIDGETS:
        wid = w["id"]
        merged_params[wid] = {**w.get("default_params", {}), **widget_configs.get(wid, {})}

    context = {
        "page_title": f"Scheda Infografica — {display_name}",
        "display_name": display_name,
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "ordered_widgets": ordered_widgets,
        "all_widgets": EMPLOYEE_BOARD_WIDGETS,
        "widget_data": widget_data,
        "widget_params": merged_params,
        "board_cfg": board_cfg,
    }
    return render(request, "dashboard/pages/employee_board.html", context)


@login_required
@csrf_protect
@require_POST
def api_employee_board_layout(request):
    """Salva layout (ordine widget) della scheda infografica utente."""
    from core.models import EmployeeBoardConfig

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=400)

    try:
        payload = json.loads(request.body or "{}")
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Payload non valido."}, status=400)

    raw_layout = payload.get("layout")
    if not isinstance(raw_layout, list):
        return JsonResponse({"ok": False, "error": "layout deve essere una lista."}, status=400)

    layout: list[str] = []
    seen: set[str] = set()
    for item in raw_layout:
        wid = str(item or "").strip()
        if wid in _ALLOWED_WIDGET_IDS and wid not in seen:
            layout.append(wid)
            seen.add(wid)

    user_id = int(legacy_user.id)
    try:
        EmployeeBoardConfig.objects.update_or_create(
            legacy_user_id=user_id,
            defaults={"layout": layout},
        )
        return JsonResponse({"ok": True, "layout": layout})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@csrf_protect
@require_POST
def api_employee_board_widget_config(request):
    """Salva configurazione params di un singolo widget."""
    from core.models import EmployeeBoardConfig

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=400)

    try:
        payload = json.loads(request.body or "{}")
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Payload non valido."}, status=400)

    widget_id = str(payload.get("widget_id") or "").strip()
    if widget_id not in _ALLOWED_WIDGET_IDS:
        return JsonResponse({"ok": False, "error": "widget_id non valido."}, status=400)

    raw_params = payload.get("params")
    if not isinstance(raw_params, dict):
        return JsonResponse({"ok": False, "error": "params deve essere un oggetto."}, status=400)

    # Trova defaults per questo widget
    widget_def = next((w for w in EMPLOYEE_BOARD_WIDGETS if w["id"] == widget_id), None)
    if not widget_def:
        return JsonResponse({"ok": False, "error": "Widget non trovato."}, status=400)

    allowed_keys = set(widget_def.get("default_params", {}).keys())
    sanitized: dict[str, Any] = {}
    for k, v in raw_params.items():
        if k not in allowed_keys:
            continue
        default_val = widget_def["default_params"].get(k)
        if isinstance(default_val, bool):
            sanitized[k] = bool(v)
        elif isinstance(default_val, int):
            try:
                sanitized[k] = max(1, min(MAX_BOARD_WIDGET_ITEMS, int(v)))
            except (TypeError, ValueError):
                pass
        elif isinstance(default_val, str):
            sanitized[k] = str(v or "")[:100]

    user_id = int(legacy_user.id)
    try:
        obj, _ = EmployeeBoardConfig.objects.get_or_create(legacy_user_id=user_id, defaults={"layout": [], "widget_configs": {}})
        current = obj.widget_configs if isinstance(obj.widget_configs, dict) else {}
        current[widget_id] = {**widget_def.get("default_params", {}), **sanitized}
        obj.widget_configs = current
        obj.save(update_fields=["widget_configs", "updated_at"])
        return JsonResponse({"ok": True, "widget_id": widget_id, "params": current[widget_id]})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
def api_employee_board_data(request):
    """Restituisce i dati aggiornati di un singolo widget (per refresh asincrono)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None

    widget_id = request.GET.get("widget_id", "")
    if widget_id not in _ALLOWED_WIDGET_IDS:
        return JsonResponse({"ok": False, "error": "widget_id non valido."}, status=400)
    if widget_id == "anomalie_gestione" and not _anomalie_access_flags(request)["can_view_anomalie_list"]:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    board_cfg = _load_employee_board_config(legacy_user_id)
    widget_def = next((w for w in EMPLOYEE_BOARD_WIDGETS if w["id"] == widget_id), None)
    if not widget_def:
        return JsonResponse({"ok": False, "error": "Widget non trovato."}, status=400)

    params = {**widget_def.get("default_params", {}), **board_cfg.get("widget_configs", {}).get(widget_id, {})}
    data: Any = None
    if widget_id == "profilo":
        data = _board_data_profilo(legacy_user, legacy_user_id)
    elif widget_id in ("tasks_stats", "tasks_assegnati"):
        data = _board_data_tasks(legacy_user_id, params)
    elif widget_id == "assenze_future":
        data = _board_data_assenze_future(legacy_user, params)
    elif widget_id == "assenze_da_approvare":
        data = _board_data_assenze_da_approvare(legacy_user, is_admin, params)
    elif widget_id == "progetti_capo":
        data = _board_data_progetti(legacy_user_id, params)
    elif widget_id == "anomalie_gestione":
        data = _board_data_anomalie(legacy_user, is_admin, params)
    elif widget_id == "notifiche":
        data = _board_data_notifiche(legacy_user_id, params)
    return JsonResponse({"ok": True, "data": data, "params": params})


@login_required
def employee_board_pdf(request):
    """Versione stampabile/PDF della scheda dipendente (no JS, layout print-ready)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    display_name = request.user.get_full_name() or getattr(legacy_user, "nome", "") or request.user.get_username()
    anomalie_access = _anomalie_access_flags(request)

    board_cfg = _load_employee_board_config(legacy_user_id)
    user_layout = board_cfg.get("layout") or []
    widget_configs = board_cfg.get("widget_configs") or {}

    ordered_widgets = _board_ordered_widgets(
        user_layout,
        legacy_user,
        is_admin,
        widget_visibility={"anomalie_gestione": anomalie_access["can_view_anomalie_list"]},
    )

    widget_data: dict[str, Any] = {}
    for w in ordered_widgets:
        wid = w["id"]
        params = {**w.get("default_params", {}), **widget_configs.get(wid, {})}
        if wid == "profilo":
            widget_data[wid] = _board_data_profilo(legacy_user, legacy_user_id)
        elif wid in ("tasks_stats", "tasks_assegnati"):
            widget_data[wid] = _board_data_tasks(legacy_user_id, params)
        elif wid == "assenze_future":
            widget_data[wid] = _board_data_assenze_future(legacy_user, params)
        elif wid == "assenze_da_approvare":
            widget_data[wid] = _board_data_assenze_da_approvare(legacy_user, is_admin, params)
        elif wid == "progetti_capo":
            widget_data[wid] = _board_data_progetti(legacy_user_id, params)
        elif wid == "anomalie_gestione":
            widget_data[wid] = _board_data_anomalie(legacy_user, is_admin, params)
        elif wid == "notifiche":
            widget_data[wid] = _board_data_notifiche(legacy_user_id, params)

    context = {
        "page_title": f"Scheda {display_name}",
        "display_name": display_name,
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "ordered_widgets": ordered_widgets,
        "widget_data": widget_data,
        "now": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
    }
    return render(request, "dashboard/pages/employee_board_pdf.html", context)


@login_required
def api_debug_ui_meta(request):
    """Endpoint diagnostico temporaneo — solo admin."""
    legacy_user_check = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not request.user.is_superuser and not (legacy_user_check and is_legacy_admin(legacy_user_check)):
        return JsonResponse({"error": "forbidden"}, status=403)
    result: dict[str, Any] = {}
    try:
        vendor = connections["default"].vendor
        result["vendor"] = vendor
        with connections["default"].cursor() as cursor:
            # Verifica esistenza tabella
            if vendor == "sqlite":
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ui_pulsanti_meta'")
                result["table_exists"] = bool(cursor.fetchone())
                if result["table_exists"]:
                    cursor.execute("PRAGMA table_info(ui_pulsanti_meta)")
                    result["columns"] = [r[1] for r in cursor.fetchall()]
            else:
                cursor.execute("SELECT OBJECT_ID('ui_pulsanti_meta', 'U')")
                row = cursor.fetchone()
                result["table_exists"] = bool(row and row[0] is not None)
                if result["table_exists"]:
                    cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='ui_pulsanti_meta' ORDER BY ORDINAL_POSITION")
                    result["columns"] = [r[0] for r in cursor.fetchall()]
            if result.get("table_exists"):
                cursor.execute("SELECT * FROM ui_pulsanti_meta")
                cols = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                result["rows"] = [dict(zip(cols, [str(v) for v in r])) for r in rows]
    except Exception as exc:
        result["error"] = str(exc)
    # Mostra anche cosa restituisce _pulsanti_ui_meta_map
    try:
        meta_map = _pulsanti_ui_meta_map()
        result["meta_map_count"] = len(meta_map)
        result["padre_ids"] = [k for k, v in meta_map.items() if v.get("is_padre")]
    except Exception as exc:
        result["meta_map_error"] = str(exc)
    # Controlla i pulsanti visibili per questo utente
    try:
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        result["legacy_user_id"] = int(legacy_user.id) if legacy_user else None
        result["legacy_ruolo_id"] = legacy_user.ruolo_id if legacy_user else None
        result["is_legacy_admin"] = is_legacy_admin(legacy_user) if legacy_user else False
        uid = int(legacy_user.id) if legacy_user else None
        pulsanti = _visible_pulsanti_for_request(request)
        result["pulsanti_count"] = len(pulsanti)
        # Senza legacy_user_id (come nel debug precedente)
        meta_map = _pulsanti_ui_meta_map()
        module_cards_no_user = _module_cards(pulsanti, meta_map)
        result["module_cards_no_user"] = len(module_cards_no_user)
        # Con legacy_user_id (come nella vera dashboard)
        module_cards_with_user = _module_cards(pulsanti, meta_map, legacy_user_id=uid)
        result["module_cards_with_user"] = len(module_cards_with_user)
        # Mostra hidden_ids e hidden_modules
        result["hidden_pulsante_ids"] = sorted(_user_dashboard_hidden_ids(uid))
        result["hidden_modules"] = sorted(_user_hidden_modules(uid))
    except Exception as exc:
        result["pulsanti_error"] = str(exc)
    return JsonResponse(result)
