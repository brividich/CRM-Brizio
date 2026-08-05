from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from core.acl import user_can_modulo_action
from core.legacy_models import Permesso, Pulsante
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns

logger = logging.getLogger(__name__)

MAX_LAYOUT_MODULES = 300
ALLOWED_STATS_KEYS = {"total", "approved", "rejected", "pending"}

_MODULE_ICON_STATIC_PREFIX = "core/img/module-icons/"
_MODULE_ICON_DEFAULTS = (
    (("ticket", "tickets", "assistenza"), "tickets.svg"),
    (("asset", "assets", "inventario", "macchinari", "attrezzature"), "assets.svg"),
    (("dpi", "dispositivi-protezione"), "dpi.svg"),
    (("notizie", "notizia", "news", "comunicazioni", "bacheca"), "notizie.svg"),
    (("timbri", "timbro", "timbrature", "presenze"), "timbri.svg"),
    (("anagrafica", "dipendenti", "dipendente", "fornitori"), "anagrafica.svg"),
    (("diario-preposto", "diario-preposti", "diario-preposto-sicurezza"), "diario-preposto.svg"),
    (("rilevazione-incidenti", "segnalazione-incidenti", "incidenti", "unsafe-condition"), "segnalazione-incidenti.svg"),
    (("procedure-refresh", "refresh-procedure", "procedure", "presa-visione"), "refresh-procedure.svg"),
    (("gestione-anomalie", "anomalie", "anomalia"), "gestione-anomalie.svg"),
    (("assenze", "assenza", "ferie", "permessi"), "assenze.svg"),
    (("vrf-kickoff", "kickoff", "tasks", "task"), "vrf-kickoff.svg"),
)


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
        return value.strftime("%d-%m-%Y")
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
    if lower.startswith("static:"):
        return static(raw.split(":", 1)[1].lstrip("/"))
    if lower.startswith("media:"):
        media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
        if not media_url.endswith("/"):
            media_url += "/"
        return media_url + raw.split(":", 1)[1].lstrip("/")
    if raw.startswith("/"):
        return raw
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not media_url.endswith("/"):
        media_url += "/"
    return media_url + raw.lstrip("/")


def _normalize_card_icon_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _default_module_card_image(*values: Any) -> str:
    tokens = [_normalize_card_icon_text(value) for value in values if value]
    haystack = " ".join(token for token in tokens if token)
    if not haystack:
        return ""
    for aliases, filename in _MODULE_ICON_DEFAULTS:
        if any(alias in tokens or alias in haystack for alias in aliases):
            return f"static:{_MODULE_ICON_STATIC_PREFIX}{filename}"
    return ""


def _module_icon_url(filename: str) -> str:
    return _card_image_public_url(f"static:{_MODULE_ICON_STATIC_PREFIX}{filename}")


def _module_card_image_lookup(
    ui_meta_map: dict[int, dict[str, Any]] | None = None,
    pulsanti: list[Any] | None = None,
) -> dict[str, str]:
    """Mappa alias modulo/codice/label -> URL immagine caricata manualmente."""
    if ui_meta_map is None:
        ui_meta_map = _pulsanti_ui_meta_map()
    if pulsanti is None:
        try:
            pulsanti = list(Pulsante.objects.all().order_by("modulo", "id"))
        except DatabaseError:
            return {}

    lookup: dict[str, str] = {}
    for pulsante in pulsanti:
        try:
            meta = ui_meta_map.get(int(getattr(pulsante, "id", 0) or 0), {})
        except Exception:
            meta = {}
        image_url = _card_image_public_url(meta.get("card_image") if isinstance(meta, dict) else "")
        if not image_url:
            continue
        keys = {
            _normalize_card_icon_text(getattr(pulsante, attr, ""))
            for attr in ("modulo", "codice", "label", "nome_visibile", "url")
        }
        keys.discard("")
        for key in keys:
            lookup.setdefault(key, image_url)
    return lookup


def _module_image_url_for(
    lookup: dict[str, str] | None,
    *aliases: Any,
    fallback_filename: str = "",
) -> str:
    lookup = lookup or {}
    for alias in aliases:
        key = _normalize_card_icon_text(alias)
        if key and lookup.get(key):
            return lookup[key]
    return _module_icon_url(fallback_filename) if fallback_filename else ""


def _map_legacy_url(url_value: str) -> str:
    raw = (url_value or "").strip() or "/"
    path = raw.lower()
    if path in {"/", "/dashboard"}:
        return reverse("dashboard_home")
    if path.startswith("/assenze"):
        return reverse("assenze_menu")
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
    # Auto-riparazione dello schema legacy: se fallisce, falliranno anche le query
    # che contano su quella colonna — meglio saperlo qui che a valle.
    except Exception:
        logger.exception("Dashboard: colonna ui_pulsanti_meta.is_padre non verificabile/creabile")


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
                "image_url": _card_image_public_url(
                    meta.get("card_image")
                    or _default_module_card_image(modulo_display, puls.codice, puls.label, puls.url)
                ),
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
                "image_url": _card_image_public_url(
                    meta.get("card_image")
                    or _default_module_card_image(p.modulo, p.codice, p.label, p.url)
                ),
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
                    "image_url": _card_image_public_url(
                        meta.get("card_image")
                        or _default_module_card_image(p.modulo, p.codice, p.label, p.url)
                    ),
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
        logger.exception("Dashboard: widget richieste assenze non costruito")

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
    return redirect("home_portale:index")


@login_required
def richieste(request):
    return redirect("assenze_gestione")


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
    from anomalie.views import _load_anomalie_menu_logo
    access_flags = _anomalie_access_flags(request)
    context = {
        "user": request.user,
        "menu_logo_url": _load_anomalie_menu_logo(),
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
        "icon": "static:core/img/module-icons/anagrafica.svg",
        "description": "Informazioni anagrafiche del dipendente",
        "default_params": {"show_reparto": True, "show_mansione": True, "show_contatti": True},
    },
    {
        "id": "panoramica_moduli",
        "title": "Panoramica KPI",
        "icon": "static:core/img/module-icons/diario-preposto.svg",
        "description": "Contatori rapidi cross-modulo: task, assenze, ticket, asset, procedure",
        "default_params": {"show_secondary": True},
    },
    {
        "id": "tasks_stats",
        "title": "Riepilogo Task",
        "icon": "static:core/img/module-icons/diario-preposto.svg",
        "description": "Contatori rapidi: todo, in corso, completati, scaduti",
        "default_params": {"show_overdue": True, "show_done": True},
    },
    {
        "id": "tasks_assegnati",
        "title": "Task Assegnati",
        "icon": "static:core/img/module-icons/vrf-kickoff.svg",
        "description": "Lista task aperti assegnati all'utente",
        "default_params": {"max_items": 10, "show_priority": True, "show_project": True, "filter_status": "open"},
    },
    {
        "id": "assenze_future",
        "title": "Assenze Programmate",
        "icon": "static:core/img/module-icons/assenze.svg",
        "description": "Assenze future approvate/programmate",
        "default_params": {"max_items": 8, "show_tipo": True, "show_motivazione": False},
    },
    {
        "id": "tickets_miei",
        "title": "Ticket Personali",
        "icon": "static:core/img/module-icons/tickets.svg",
        "description": "I ticket aperti o presi in carico che ti coinvolgono",
        "default_params": {"max_items": 6, "show_closed": False},
    },
    {
        "id": "assets_dotazione",
        "title": "Asset in Dotazione",
        "icon": "static:core/img/module-icons/assets.svg",
        "description": "Asset assegnati al dipendente con scadenze amministrative in evidenza",
        "default_params": {"max_items": 6, "show_deadlines": True},
    },
    {
        "id": "procedure_da_leggere",
        "title": "Procedure da Leggere",
        "icon": "static:core/img/module-icons/refresh-procedure.svg",
        "description": "Campagne e prese visione ancora aperte",
        "default_params": {"max_items": 6, "show_confirmed": False},
    },
    {
        "id": "assenze_da_approvare",
        "title": "Assenze da Approvare",
        "icon": "static:core/img/module-icons/assenze.svg",
        "description": "Assenze in attesa di approvazione (solo CAR/admin)",
        "default_params": {"max_items": 8},
        "role_required": ["car", "capo reparto", "amministrazione", "admin"],
    },
    {
        "id": "progetti_capo",
        "title": "Progetti (come Capo Commessa)",
        "icon": "static:core/img/module-icons/vrf-kickoff.svg",
        "description": "Progetti dove sei capo commessa",
        "default_params": {"max_items": 8, "show_manager": True},
        "role_required": ["capo commessa", "capo_commessa", "admin"],
    },
    {
        "id": "anomalie_gestione",
        "title": "Anomalie da Gestire",
        "icon": "static:core/img/module-icons/gestione-anomalie.svg",
        "description": "Anomalie aperte (visibili a capo commessa e CAR/admin)",
        "default_params": {"max_items": 8, "solo_aperte": True},
        "role_required": ["capo commessa", "capo_commessa", "car", "capo reparto", "amministrazione", "admin"],
    },
    {
        "id": "notifiche",
        "title": "Notifiche",
        "icon": "static:core/img/module-icons/notizie.svg",
        "description": "Ultime notifiche non lette",
        "default_params": {"max_items": 6, "solo_non_lette": False},
    },
]

_EMPLOYEE_WIDGET_MODULE_ICON_ALIASES = {
    "profilo": ("anagrafica",),
    "panoramica_moduli": ("diario-preposto", "dashboard"),
    "tasks_stats": ("tasks", "task", "vrf-kickoff", "kickoff"),
    "tasks_assegnati": ("tasks", "task", "vrf-kickoff", "kickoff"),
    "assenze_future": ("assenze", "assenza"),
    "tickets_miei": ("tickets", "ticket"),
    "assets_dotazione": ("assets", "asset"),
    "procedure_da_leggere": ("procedure-refresh", "refresh-procedure", "procedure"),
    "assenze_da_approvare": ("assenze", "assenza"),
    "progetti_capo": ("tasks", "task", "vrf-kickoff", "kickoff"),
    "anomalie_gestione": ("gestione-anomalie", "anomalie", "anomalia"),
    "notifiche": ("notizie", "notizia", "news"),
}

EMPLOYEE_BOARD_DEFAULT_LAYOUT = [
    "profilo",
    "panoramica_moduli",
    "tasks_stats",
    "assenze_future",
    "tickets_miei",
    "assets_dotazione",
    "procedure_da_leggere",
    "tasks_assegnati",
    "assenze_da_approvare",
    "anomalie_gestione",
    "progetti_capo",
    "notifiche",
]

_ALLOWED_WIDGET_IDS = {w["id"] for w in EMPLOYEE_BOARD_WIDGETS}
MAX_BOARD_WIDGET_ITEMS = 50
EMPLOYEE_BOARD_TEMPLATE_KEY = "default"


def _widget_def_map() -> dict[str, dict]:
    return {widget["id"]: widget for widget in EMPLOYEE_BOARD_WIDGETS}


def _sanitize_board_layout(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    layout: list[str] = []
    seen: set[str] = set()
    for raw in value:
        wid = str(raw or "").strip()
        if wid not in _ALLOWED_WIDGET_IDS or wid in seen:
            continue
        seen.add(wid)
        layout.append(wid)
    return layout


def _sanitize_widget_params(widget_def: dict, raw_params: Any, *, include_defaults: bool) -> dict[str, Any]:
    defaults = widget_def.get("default_params", {}) or {}
    raw_params = raw_params if isinstance(raw_params, dict) else {}
    sanitized: dict[str, Any] = {}
    for key, default_val in defaults.items():
        if key not in raw_params:
            continue
        raw_value = raw_params.get(key)
        if isinstance(default_val, bool):
            sanitized[key] = bool(raw_value)
        elif isinstance(default_val, int):
            try:
                sanitized[key] = max(1, min(MAX_BOARD_WIDGET_ITEMS, int(raw_value)))
            except (TypeError, ValueError):
                continue
        elif isinstance(default_val, str):
            sanitized[key] = str(raw_value or "")[:100]
    return {**defaults, **sanitized} if include_defaults else sanitized


def _sanitize_widget_configs(raw_configs: Any, *, include_defaults: bool) -> dict[str, dict]:
    widget_map = _widget_def_map()
    if not isinstance(raw_configs, dict):
        return {}
    result: dict[str, dict] = {}
    for raw_widget_id, raw_params in raw_configs.items():
        wid = str(raw_widget_id or "").strip()
        widget_def = widget_map.get(wid)
        if not widget_def:
            continue
        result[wid] = _sanitize_widget_params(widget_def, raw_params, include_defaults=include_defaults)
    return result


def _default_employee_board_template() -> dict[str, Any]:
    return {
        "layout": list(EMPLOYEE_BOARD_DEFAULT_LAYOUT),
        "widget_configs": {},
        "template_name": "Predefinito sistema",
        "template_source": "system",
        "template_updated_at": None,
    }


def _load_employee_board_template() -> dict[str, Any]:
    fallback = _default_employee_board_template()
    try:
        from core.models import EmployeeBoardTemplate

        row = EmployeeBoardTemplate.objects.select_related("updated_by").filter(key=EMPLOYEE_BOARD_TEMPLATE_KEY).first()
    except Exception:
        row = None
    if not row:
        return fallback
    layout = _sanitize_board_layout(row.layout) or list(EMPLOYEE_BOARD_DEFAULT_LAYOUT)
    widget_configs = _sanitize_widget_configs(row.widget_configs, include_defaults=True)
    return {
        "layout": layout,
        "widget_configs": widget_configs,
        "template_name": str(row.name or "Template iniziale admin"),
        "template_source": "admin",
        "template_updated_at": row.updated_at,
    }


def _load_employee_board_config(legacy_user_id: int | None) -> dict:
    template_cfg = _load_employee_board_template()
    if not legacy_user_id:
        return {
            "layout": list(template_cfg["layout"]),
            "widget_configs": dict(template_cfg["widget_configs"]),
            "has_user_config": False,
            "template_name": template_cfg["template_name"],
            "template_source": template_cfg["template_source"],
            "template_updated_at": template_cfg["template_updated_at"],
        }
    try:
        from core.models import EmployeeBoardConfig

        row = EmployeeBoardConfig.objects.filter(legacy_user_id=legacy_user_id).first()
    except Exception:
        row = None
    if not row:
        return {
            "layout": list(template_cfg["layout"]),
            "widget_configs": dict(template_cfg["widget_configs"]),
            "has_user_config": False,
            "template_name": template_cfg["template_name"],
            "template_source": template_cfg["template_source"],
            "template_updated_at": template_cfg["template_updated_at"],
        }

    user_layout = _sanitize_board_layout(row.layout)
    user_widget_configs = _sanitize_widget_configs(row.widget_configs, include_defaults=True)
    has_user_config = bool(user_layout or user_widget_configs)
    if not has_user_config:
        return {
            "layout": list(template_cfg["layout"]),
            "widget_configs": dict(template_cfg["widget_configs"]),
            "has_user_config": False,
            "template_name": template_cfg["template_name"],
            "template_source": template_cfg["template_source"],
            "template_updated_at": template_cfg["template_updated_at"],
        }

    return {
        "layout": user_layout or list(template_cfg["layout"]),
        "widget_configs": {**template_cfg["widget_configs"], **user_widget_configs},
        "has_user_config": True,
        "template_name": template_cfg["template_name"],
        "template_source": template_cfg["template_source"],
        "template_updated_at": template_cfg["template_updated_at"],
    }


def _board_ordered_widgets(
    user_layout: list,
    legacy_user: Any,
    is_admin: bool,
    widget_visibility: dict[str, bool] | None = None,
) -> list[dict]:
    ruolo = str(getattr(legacy_user, "ruolo", "") or "").strip().lower() if legacy_user else ""
    widget_visibility = widget_visibility or {}
    visible_ids = _sanitize_board_layout(user_layout) or list(EMPLOYEE_BOARD_DEFAULT_LAYOUT)

    result = []
    widget_map = _widget_def_map()
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


def _decorate_board_widgets_with_module_images(
    widgets: list[dict],
    icon_lookup: dict[str, str] | None,
) -> list[dict]:
    decorated = []
    for widget in widgets:
        item = dict(widget)
        aliases = _EMPLOYEE_WIDGET_MODULE_ICON_ALIASES.get(str(item.get("id") or ""), ())
        manual_icon = _module_image_url_for(icon_lookup, *aliases)
        if manual_icon:
            item["icon"] = manual_icon
        decorated.append(item)
    return decorated


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
                "due_date": t.due_date.strftime("%d-%m-%Y") if t.due_date else "",
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
        today_str = timezone.localdate().isoformat()
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

        from assenze.views import _dt_label, _status_from_moderation, _strip_tipo_metadata_from_motivazione, _tipo_for_display
        out = []
        for row in rows:
            _, label = _status_from_moderation(row.get("moderation_status"), default_pending=True)
            out.append({
                "tipo": _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
                "inizio": _dt_label(row.get("data_inizio")),
                "fine": _dt_label(row.get("data_fine")),
                "stato": label,
                "motivazione": _strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
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
                "data": n.created_at.strftime("%d-%m-%Y %H:%M"),
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
        logger.exception("Dashboard: dati anagrafici dell'utente non recuperati")
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
        logger.exception("Dashboard: UserExtraInfo dell'utente non recuperata")
    return data


def _board_identity_candidates(request_user: Any, legacy_user: Any, legacy_user_id: int | None) -> dict[str, Any]:
    names: set[str] = set()
    emails: set[str] = set()
    for raw_name in [
        request_user.get_full_name() if request_user else "",
        request_user.get_username() if request_user else "",
        getattr(legacy_user, "nome", "") if legacy_user else "",
    ]:
        value = str(raw_name or "").strip()
        if value:
            names.add(value)
    for raw_email in [
        getattr(request_user, "email", "") if request_user else "",
        getattr(legacy_user, "email", "") if legacy_user else "",
    ]:
        value = str(raw_email or "").strip()
        if value:
            emails.add(value)
    return {
        "legacy_user_id": legacy_user_id,
        "names": sorted(names),
        "emails": sorted(emails),
    }


def _board_related_tickets_queryset(request_user: Any, legacy_user: Any, legacy_user_id: int | None):
    from tickets.models import Ticket

    identity = _board_identity_candidates(request_user, legacy_user, legacy_user_id)
    filters = Q()
    if identity["legacy_user_id"]:
        filters |= Q(richiedente_legacy_user_id=identity["legacy_user_id"])
    for name in identity["names"]:
        filters |= Q(richiedente_nome__iexact=name)
        filters |= Q(assegnato_a__iexact=name)
    for email in identity["emails"]:
        filters |= Q(richiedente_email__iexact=email)
        filters |= Q(assegnato_email__iexact=email)
    if not filters:
        return Ticket.objects.none()
    return Ticket.objects.filter(filters).distinct()


def _board_data_tickets(request_user: Any, legacy_user: Any, legacy_user_id: int | None, params: dict) -> dict:
    try:
        from tickets.models import PrioritaTicket, StatoTicket

        qs = _board_related_tickets_queryset(request_user, legacy_user, legacy_user_id)
        max_items = min(int(params.get("max_items") or 6), MAX_BOARD_WIDGET_ITEMS)
        show_closed = bool(params.get("show_closed", False))
        list_qs = qs if show_closed else qs.exclude(
            stato__in=[StatoTicket.RISOLTO, StatoTicket.CHIUSO, StatoTicket.ANNULLATO]
        )
        items = []
        for ticket in list_qs.order_by("-updated_at", "-created_at")[:max_items]:
            items.append(
                {
                    "id": ticket.id,
                    "numero_ticket": ticket.numero_ticket,
                    "titolo": ticket.titolo,
                    "tipo": ticket.tipo,
                    "stato": ticket.stato,
                    "stato_label": ticket.get_stato_display(),
                    "priorita": ticket.priorita,
                    "priorita_label": ticket.get_priorita_display(),
                    "asset": str(ticket.asset) if ticket.asset_id and ticket.asset else str(ticket.asset_descrizione_libera or ""),
                    "updated_at": timezone.localtime(ticket.updated_at).strftime("%d-%m-%Y %H:%M"),
                }
            )
        stats = {
            "open": qs.filter(stato=StatoTicket.APERTA).count(),
            "in_charge": qs.filter(stato=StatoTicket.IN_CARICO).count(),
            "waiting": qs.filter(stato=StatoTicket.IN_ATTESA).count(),
            "urgent": qs.filter(
                priorita=PrioritaTicket.URGENTE,
                stato__in=[StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA],
            ).count(),
        }
        return {"items": items, "stats": stats}
    except Exception:
        return {"items": [], "stats": {"open": 0, "in_charge": 0, "waiting": 0, "urgent": 0}}


def _board_data_assets(legacy_user_id: int | None, params: dict) -> dict:
    if not legacy_user_id:
        return {"items": [], "stats": {"assigned": 0, "in_use": 0, "in_repair": 0, "deadlines": 0}}
    try:
        from assets.models import Asset, AssetAdministrativeDeadline

        max_items = min(int(params.get("max_items") or 6), MAX_BOARD_WIDGET_ITEMS)
        show_deadlines = bool(params.get("show_deadlines", True))
        today = timezone.localdate()
        assigned_qs = Asset.objects.filter(assigned_legacy_user_id=legacy_user_id).order_by("name", "asset_tag", "id")
        assets = list(assigned_qs[:max_items])
        deadline_map: dict[int, Any] = {}
        if show_deadlines and assets:
            asset_ids = [asset.id for asset in assets]
            for deadline in (
                AssetAdministrativeDeadline.objects.filter(asset_id__in=asset_ids, is_active=True)
                .select_related("asset")
                .order_by("asset_id", "due_date", "id")
            ):
                deadline_map.setdefault(deadline.asset_id, deadline)
        items = []
        for asset in assets:
            deadline = deadline_map.get(asset.id)
            days_until_due = deadline.days_until_due(today) if deadline else None
            items.append(
                {
                    "id": asset.id,
                    "asset_tag": asset.asset_tag,
                    "name": asset.name,
                    "status": asset.status,
                    "status_label": asset.get_status_display(),
                    "location": asset.assignment_location or asset.assignment_reparto or asset.reparto or "",
                    "deadline_title": deadline.title if deadline else "",
                    "deadline_due_date": deadline.due_date.strftime("%d-%m-%Y") if deadline and deadline.due_date else "",
                    "deadline_state": (
                        "overdue"
                        if deadline and days_until_due is not None and days_until_due < 0
                        else "warning"
                        if deadline and days_until_due is not None and days_until_due <= int(deadline.warning_days or 0)
                        else "ok"
                    ),
                }
            )
        stats = {
            "assigned": assigned_qs.count(),
            "in_use": assigned_qs.filter(status=Asset.STATUS_IN_USE).count(),
            "in_repair": assigned_qs.filter(status=Asset.STATUS_IN_REPAIR).count(),
            "deadlines": AssetAdministrativeDeadline.objects.filter(
                asset__assigned_legacy_user_id=legacy_user_id,
                is_active=True,
                due_date__lte=today + timedelta(days=30),
            ).count(),
        }
        return {"items": items, "stats": stats}
    except Exception:
        return {"items": [], "stats": {"assigned": 0, "in_use": 0, "in_repair": 0, "deadlines": 0}}


def _board_data_procedure_refresh(request_user: Any, params: dict) -> dict:
    try:
        from procedure_refresh.models import AssignmentStatus, ProcedureAssignment

        max_items = min(int(params.get("max_items") or 6), MAX_BOARD_WIDGET_ITEMS)
        show_confirmed = bool(params.get("show_confirmed", False))
        qs = (
            ProcedureAssignment.objects.filter(user=request_user)
            .select_related("campaign", "revision__document")
            .order_by("due_date", "-assigned_at")
        )
        list_qs = qs if show_confirmed else qs.filter(
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE]
        )
        items = []
        for assignment in list_qs[:max_items]:
            document = getattr(assignment.revision, "document", None)
            items.append(
                {
                    "id": assignment.id,
                    "campaign": assignment.campaign.name,
                    "document_code": getattr(document, "code", ""),
                    "document_title": getattr(document, "title", ""),
                    "status": assignment.status,
                    "status_label": assignment.get_status_display(),
                    "due_date": assignment.due_date.strftime("%d-%m-%Y") if assignment.due_date else "",
                }
            )
        stats = {
            "pending": qs.filter(status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]).count(),
            "overdue": qs.filter(status=AssignmentStatus.OVERDUE).count(),
            "confirmed": qs.filter(status=AssignmentStatus.READ_CONFIRMED).count(),
        }
        return {"items": items, "stats": stats}
    except Exception:
        return {"items": [], "stats": {"pending": 0, "overdue": 0, "confirmed": 0}}


def _board_data_module_overview(
    request_user: Any,
    legacy_user: Any,
    legacy_user_id: int | None,
    params: dict,
    icon_lookup: dict[str, str] | None = None,
) -> dict:
    task_data = _board_data_tasks(legacy_user_id, {"max_items": 1, "filter_status": "open"})
    ticket_data = _board_data_tickets(request_user, legacy_user, legacy_user_id, {"max_items": 1, "show_closed": False})
    asset_data = _board_data_assets(legacy_user_id, {"max_items": 1, "show_deadlines": True})
    procedure_data = _board_data_procedure_refresh(request_user, {"max_items": 1, "show_confirmed": False})
    assenze_programmate = _board_data_assenze_future(legacy_user, {"max_items": MAX_BOARD_WIDGET_ITEMS})
    show_secondary = bool(params.get("show_secondary", True))
    cards = [
        {
            "label": "Task aperti",
            "value": int(task_data.get("stats", {}).get("todo", 0)) + int(task_data.get("stats", {}).get("in_progress", 0)),
            "meta": f"{int(task_data.get('stats', {}).get('overdue', 0))} scaduti",
            "tone": "blue",
            "url": reverse("tasks:list"),
            "icon_url": _module_image_url_for(
                icon_lookup, "tasks", "task", "vrf-kickoff", "kickoff", fallback_filename="vrf-kickoff.svg"
            ),
        },
        {
            "label": "Assenze programmate",
            "value": len(assenze_programmate),
            "meta": "viste dal modulo assenze",
            "tone": "green",
            "url": reverse("assenze_menu"),
            "icon_url": _module_image_url_for(icon_lookup, "assenze", "assenza", fallback_filename="assenze.svg"),
        },
        {
            "label": "Ticket attivi",
            "value": int(ticket_data.get("stats", {}).get("open", 0))
            + int(ticket_data.get("stats", {}).get("in_charge", 0))
            + int(ticket_data.get("stats", {}).get("waiting", 0)),
            "meta": f"{int(ticket_data.get('stats', {}).get('urgent', 0))} urgenti",
            "tone": "red",
            "url": reverse("tickets:dashboard"),
            "icon_url": _module_image_url_for(icon_lookup, "tickets", "ticket", fallback_filename="tickets.svg"),
        },
        {
            "label": "Asset assegnati",
            "value": int(asset_data.get("stats", {}).get("assigned", 0)),
            "meta": f"{int(asset_data.get('stats', {}).get('deadlines', 0))} scadenze nei prossimi 30 gg",
            "tone": "purple",
            "url": reverse("assets:asset_list"),
            "icon_url": _module_image_url_for(icon_lookup, "assets", "asset", fallback_filename="assets.svg"),
        },
        {
            "label": "Procedure aperte",
            "value": int(procedure_data.get("stats", {}).get("pending", 0))
            + int(procedure_data.get("stats", {}).get("overdue", 0)),
            "meta": f"{int(procedure_data.get('stats', {}).get('confirmed', 0))} confermate",
            "tone": "yellow",
            "url": reverse("procedure_refresh:my_assignments"),
            "icon_url": _module_image_url_for(
                icon_lookup,
                "procedure-refresh",
                "refresh-procedure",
                "procedure",
                fallback_filename="refresh-procedure.svg",
            ),
        },
    ]
    if not show_secondary:
        cards = cards[:4]
    return {"cards": cards}


def _available_board_widgets(
    legacy_user: Any,
    is_admin: bool,
    widget_visibility: dict[str, bool] | None = None,
) -> list[dict]:
    return _board_ordered_widgets(
        [widget["id"] for widget in EMPLOYEE_BOARD_WIDGETS],
        legacy_user,
        is_admin,
        widget_visibility=widget_visibility,
    )


def _get_employee_board_widget_data(
    widget_id: str,
    *,
    request_user: Any,
    legacy_user: Any,
    legacy_user_id: int | None,
    is_admin: bool,
    params: dict,
    icon_lookup: dict[str, str] | None = None,
) -> Any:
    if widget_id == "profilo":
        return _board_data_profilo(legacy_user, legacy_user_id)
    if widget_id == "panoramica_moduli":
        return _board_data_module_overview(request_user, legacy_user, legacy_user_id, params, icon_lookup=icon_lookup)
    if widget_id in ("tasks_stats", "tasks_assegnati"):
        return _board_data_tasks(legacy_user_id, params)
    if widget_id == "assenze_future":
        return _board_data_assenze_future(legacy_user, params)
    if widget_id == "tickets_miei":
        return _board_data_tickets(request_user, legacy_user, legacy_user_id, params)
    if widget_id == "assets_dotazione":
        return _board_data_assets(legacy_user_id, params)
    if widget_id == "procedure_da_leggere":
        return _board_data_procedure_refresh(request_user, params)
    if widget_id == "assenze_da_approvare":
        return _board_data_assenze_da_approvare(legacy_user, is_admin, params)
    if widget_id == "progetti_capo":
        return _board_data_progetti(legacy_user_id, params)
    if widget_id == "anomalie_gestione":
        return _board_data_anomalie(legacy_user, is_admin, params)
    if widget_id == "notifiche":
        return _board_data_notifiche(legacy_user_id, params)
    return None


def _build_employee_board_context(request, *, primary_dashboard: bool) -> dict[str, Any]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    display_name = request.user.get_full_name() or getattr(legacy_user, "nome", "") or request.user.get_username()
    anomalie_access = _anomalie_access_flags(request)
    widget_visibility = {"anomalie_gestione": anomalie_access["can_view_anomalie_list"]}

    board_cfg = _load_employee_board_config(legacy_user_id)
    widget_configs = board_cfg.get("widget_configs") or {}
    module_icon_lookup = _module_card_image_lookup()

    ordered_widgets = _board_ordered_widgets(
        board_cfg.get("layout") or [],
        legacy_user,
        is_admin,
        widget_visibility=widget_visibility,
    )
    available_widgets = _available_board_widgets(legacy_user, is_admin, widget_visibility=widget_visibility)
    ordered_widgets = _decorate_board_widgets_with_module_images(ordered_widgets, module_icon_lookup)
    available_widgets = _decorate_board_widgets_with_module_images(available_widgets, module_icon_lookup)

    widget_data: dict[str, Any] = {}
    for w in ordered_widgets:
        wid = w["id"]
        params = {**w.get("default_params", {}), **widget_configs.get(wid, {})}
        widget_data[wid] = _get_employee_board_widget_data(
            wid,
            request_user=request.user,
            legacy_user=legacy_user,
            legacy_user_id=legacy_user_id,
            is_admin=is_admin,
            params=params,
            icon_lookup=module_icon_lookup,
        )

    merged_params: dict[str, dict] = {}
    for w in available_widgets:
        wid = w["id"]
        merged_params[wid] = {**w.get("default_params", {}), **widget_configs.get(wid, {})}

    context = {
        "page_title": f"Dashboard — {display_name}" if primary_dashboard else f"Scheda Dipendente — {display_name}",
        "display_name": display_name,
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "ordered_widgets": ordered_widgets,
        "all_widgets": available_widgets,
        "widget_data": widget_data,
        "widget_params": merged_params,
        "board_cfg": board_cfg,
        "primary_dashboard": primary_dashboard,
    }
    return context


@login_required
def employee_board(request):
    return redirect("dashboard_home")


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

    layout = _sanitize_board_layout(raw_layout)

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

    widget_def = _widget_def_map().get(widget_id)
    if not widget_def:
        return JsonResponse({"ok": False, "error": "Widget non trovato."}, status=400)
    sanitized = _sanitize_widget_params(widget_def, raw_params, include_defaults=True)

    user_id = int(legacy_user.id)
    try:
        obj, _ = EmployeeBoardConfig.objects.get_or_create(legacy_user_id=user_id, defaults={"layout": [], "widget_configs": {}})
        current = _sanitize_widget_configs(obj.widget_configs, include_defaults=True)
        current[widget_id] = sanitized
        obj.widget_configs = current
        obj.save(update_fields=["widget_configs", "updated_at"])
        return JsonResponse({"ok": True, "widget_id": widget_id, "params": current[widget_id]})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@csrf_protect
@require_POST
def api_employee_board_reset(request):
    """Ripristina la scheda dipendente al template iniziale definito dagli admin."""
    from core.models import EmployeeBoardConfig

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=400)

    try:
        EmployeeBoardConfig.objects.filter(legacy_user_id=int(legacy_user.id)).delete()
        template_cfg = _load_employee_board_template()
        return JsonResponse(
            {
                "ok": True,
                "layout": template_cfg["layout"],
                "template_name": template_cfg["template_name"],
            }
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@csrf_protect
@require_POST
def api_employee_board_admin_template(request):
    """Salva il template iniziale globale della scheda dipendente."""
    from core.models import EmployeeBoardTemplate

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    if not is_admin:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    try:
        payload = json.loads(request.body or "{}")
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "Payload non valido."}, status=400)

    layout = _sanitize_board_layout(payload.get("layout"))
    if not layout:
        layout = list(EMPLOYEE_BOARD_DEFAULT_LAYOUT)
    widget_configs = _sanitize_widget_configs(payload.get("widget_configs"), include_defaults=True)
    template_name = str(payload.get("name") or "Template iniziale admin").strip()[:100] or "Template iniziale admin"

    try:
        EmployeeBoardTemplate.objects.update_or_create(
            key=EMPLOYEE_BOARD_TEMPLATE_KEY,
            defaults={
                "name": template_name,
                "layout": layout,
                "widget_configs": widget_configs,
                "updated_by": request.user,
            },
        )
        return JsonResponse({"ok": True, "layout": layout, "template_name": template_name})
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
    widget_def = _widget_def_map().get(widget_id)
    if not widget_def:
        return JsonResponse({"ok": False, "error": "Widget non trovato."}, status=400)

    params = {**widget_def.get("default_params", {}), **board_cfg.get("widget_configs", {}).get(widget_id, {})}
    data = _get_employee_board_widget_data(
        widget_id,
        request_user=request.user,
        legacy_user=legacy_user,
        legacy_user_id=legacy_user_id,
        is_admin=is_admin,
        params=params,
    )
    return JsonResponse({"ok": True, "data": data, "params": params})


@login_required
def employee_board_pdf(request):
    """Versione stampabile/PDF della scheda dipendente (no JS, layout print-ready)."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None
    display_name = request.user.get_full_name() or getattr(legacy_user, "nome", "") or request.user.get_username()
    anomalie_access = _anomalie_access_flags(request)
    widget_visibility = {"anomalie_gestione": anomalie_access["can_view_anomalie_list"]}

    board_cfg = _load_employee_board_config(legacy_user_id)
    widget_configs = board_cfg.get("widget_configs") or {}

    ordered_widgets = _board_ordered_widgets(
        board_cfg.get("layout") or [],
        legacy_user,
        is_admin,
        widget_visibility=widget_visibility,
    )

    widget_data: dict[str, Any] = {}
    for w in ordered_widgets:
        wid = w["id"]
        params = {**w.get("default_params", {}), **widget_configs.get(wid, {})}
        widget_data[wid] = _get_employee_board_widget_data(
            wid,
            request_user=request.user,
            legacy_user=legacy_user,
            legacy_user_id=legacy_user_id,
            is_admin=is_admin,
            params=params,
        )

    context = {
        "page_title": f"Dashboard {display_name}",
        "display_name": display_name,
        "legacy_user": legacy_user,
        "is_admin": is_admin,
        "ordered_widgets": ordered_widgets,
        "widget_data": widget_data,
        "now": timezone.localtime(timezone.now()).strftime("%d-%m-%Y %H:%M"),
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


# ── Hub Preview ────────────────────────────────────────────────────────────────

_HUB_DAY_IT = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica",
]
_HUB_MONTH_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _hub_kpi_cards(ctx: dict, request=None) -> list[dict]:
    """Raccoglie KPI cross-modulo per la hub preview. Ogni modulo è opzionale."""
    from django.utils import timezone as tz
    kpis: list[dict] = []
    today = tz.localdate()

    # ── Assenze ──
    kpis.append({
        "kpi_key": "assenze",
        "label": "Richieste in attesa",
        "value": ctx.get("richieste_attesa", 0),
        "sub": f"{ctx.get('richieste_total', 0)} totali",
        "icon": "ASS",
        "icon_class": "yellow",
    })

    # ── Anomalie (tabella legacy, raw SQL) ──
    try:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM anomalie WHERE COALESCE(chiudere, 0) = 0")
            row = cur.fetchone()
        kpis.append({
            "kpi_key": "anomalie",
            "label": "Anomalie aperte",
            "value": int(row[0]) if row else 0,
            "sub": "in produzione",
            "icon": "ANO",
            "icon_class": "red",
        })
    # Stessa regola dei riquadri della home: la tessera puo' mancare, ma non in
    # silenzio — un KPI assente si legge come "zero", che e' l'errore peggiore.
    except Exception:
        logger.exception("Dashboard: KPI «anomalie» non calcolato")

    # ── Ticket ──
    try:
        from tickets.models import Ticket, StatoTicket
        aperta = Ticket.objects.filter(stato=StatoTicket.APERTA).count()
        in_carico = Ticket.objects.filter(stato=StatoTicket.IN_CARICO).count()
        kpis.append({
            "kpi_key": "ticket",
            "label": "Ticket aperti",
            "value": aperta,
            "sub": f"{in_carico} in lavorazione",
            "icon": "TKT",
            "icon_class": "blue",
        })
    except Exception:
        logger.exception("Dashboard: KPI «ticket» non calcolato")

    # ── Asset ──
    try:
        from assets.models import Asset
        in_uso = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
        totale = Asset.objects.count()
        kpis.append({
            "kpi_key": "asset",
            "label": "Asset monitorati",
            "value": totale,
            "sub": f"{in_uso} in uso",
            "icon": "AST",
            "icon_class": "green",
        })
    except Exception:
        logger.exception("Dashboard: KPI «asset» non calcolato")

    # ── Task / KICK-OFF ──
    try:
        from tasks.models import Task, TaskStatus
        attivi = Task.objects.filter(
            status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS]
        ).count()
        kpis.append({
            "kpi_key": "task",
            "label": "Task attivi",
            "value": attivi,
            "sub": "kick-off",
            "icon": "TSK",
            "icon_class": "blue",
        })
    except Exception:
        logger.exception("Dashboard: KPI «task» non calcolato")

    # ── DPI richieste in attesa ──
    try:
        from dpi.models import RichiestaDPI
        dpi_attesa = RichiestaDPI.objects.filter(stato="INVIATA").count()
        if dpi_attesa:
            kpis.append({
                "kpi_key": "dpi",
                "label": "DPI in attesa",
                "value": dpi_attesa,
                "sub": "richieste",
                "icon": "DPI",
                "icon_class": "yellow",
            })
    except Exception:
        logger.exception("Dashboard: KPI «dpi» non calcolato")

    # ── Scadenze imminenti asset ──
    try:
        from assets.models import AssetAdministrativeDeadline, PeriodicVerification
        import datetime
        horizon = today + datetime.timedelta(days=30)
        scad_amm = AssetAdministrativeDeadline.objects.filter(
            is_active=True, due_date__lte=horizon
        ).count()
        scad_man = PeriodicVerification.objects.filter(
            is_active=True, next_verification_date__lte=horizon
        ).count()
        totale_scad = scad_amm + scad_man
        kpis.append({
            "kpi_key": "scadenze",
            "label": "Scadenze imminenti",
            "value": totale_scad,
            "sub": f"{scad_amm} amm. · {scad_man} manut.",
            "icon": "SCA",
            "icon_class": "red" if totale_scad else "green",
        })
    except Exception:
        logger.exception("Dashboard: KPI «scadenze» non calcolato")

    # ── Diario preposto ──
    try:
        from diario_preposto.models import SegnalazionePreposto
        anno = today.year
        n_segnalazioni = SegnalazionePreposto.objects.filter(
            data_segnalazione__year=anno
        ).count()
        kpis.append({
            "kpi_key": "diario",
            "label": "Diario preposto",
            "value": n_segnalazioni,
            "sub": f"segnalazioni {anno}",
            "icon": "DRP",
            "icon_class": "blue",
        })
    except Exception:
        logger.exception("Dashboard: KPI «diario preposto» non calcolato")

    # ── Rilevazione incidenti ──
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente
        anno = today.year
        n_incidenti = RilevazioneIncidente.objects.filter(
            data_segnalazione__year=anno
        ).count()
        kpis.append({
            "kpi_key": "incidenti",
            "label": "Incidenti rilevati",
            "value": n_incidenti,
            "sub": f"anno {anno}",
            "icon": "INC",
            "icon_class": "red" if n_incidenti else "green",
        })
    except Exception:
        logger.exception("Dashboard: KPI «incidenti» non calcolato")

    # ── Notizie da leggere ──
    try:
        from django.db.models import Exists, OuterRef
        from notizie.models import Notizia, NotiziaLettura
        from notizie.models import STATO_PUBBLICATA
        legacy_user = ctx.get("legacy_user")
        if legacy_user:
            confermata = NotiziaLettura.objects.filter(
                notizia=OuterRef("pk"),
                legacy_user_id=legacy_user.pk,
                versione_letta=OuterRef("versione"),
                ack_at__isnull=False,
            )
            da_leggere = (
                Notizia.objects.filter(stato=STATO_PUBBLICATA)
                .exclude(Exists(confermata))
                .count()
            )
            kpis.append({
                "kpi_key": "notizie",
                "label": "Notizie da leggere",
                "value": da_leggere,
                "sub": "bacheca comunicazioni",
                "icon": "NOT",
                "icon_class": "yellow" if da_leggere else "green",
            })
    except Exception:
        logger.exception("Dashboard: KPI «notizie» non calcolato")

    # ── Procedure refresh da confermare ──
    try:
        from procedure_refresh.models import ProcedureAssignment, AssignmentStatus
        user = request.user if request else None
        if user and user.is_authenticated:
            da_confermare = ProcedureAssignment.objects.filter(
                user=user,
                status=AssignmentStatus.ASSIGNED,
            ).count()
            kpis.append({
                "kpi_key": "procedure",
                "label": "Procedure da confermare",
                "value": da_confermare,
                "sub": "presa visione",
                "icon": "PRF",
                "icon_class": "yellow" if da_confermare else "green",
            })
    except Exception:
        logger.exception("Dashboard: KPI «procedure» non calcolato")

    # ── Applica overrides da SiteConfig ──
    try:
        from core.models import SiteConfig
        cfg = {
            row["key"]: row["value"]
            for row in SiteConfig.objects.filter(key__startswith="hub_kpi_").values("key", "value")
        }
        filtered = []
        for kpi in kpis:
            key = kpi.get("kpi_key", "")
            if cfg.get(f"hub_kpi_{key}_disabled") == "1":
                continue
            label_ov = cfg.get(f"hub_kpi_{key}_label", "")
            icon_ov  = cfg.get(f"hub_kpi_{key}_icon", "")
            bg_ov    = cfg.get(f"hub_kpi_{key}_bg_color", "")
            fg_ov    = cfg.get(f"hub_kpi_{key}_fg_color", "")
            if label_ov:
                kpi["label"] = label_ov
            if icon_ov:
                kpi["icon"] = icon_ov
            if bg_ov:
                kpi["custom_bg"] = bg_ov
                kpi["custom_fg"] = fg_ov or "#ffffff"
            filtered.append(kpi)
        kpis = filtered
    except Exception:
        logger.exception("Dashboard: personalizzazioni dei KPI non applicate")

    return kpis


@login_required
def dashboard_hub_preview(request):
    ctx = _base_dashboard_context(request)
    now = timezone.localtime(timezone.now())
    date_label = (
        f"{_HUB_DAY_IT[now.weekday()]} {now.day} "
        f"{_HUB_MONTH_IT[now.month - 1]} {now.year} · Hub Aziendale Novicrom"
    )
    display_name = ctx.get("display_name") or request.user.get_full_name() or request.user.get_username()

    hub_branding = {}
    try:
        from core.models import SiteConfig
        branding_keys = {
            "hub_hero_title", "hub_hero_sub", "hub_bg_color",
            "hub_hero_color_1", "hub_hero_color_2", "hub_logo_url",
        }
        for row in SiteConfig.objects.filter(key__in=branding_keys).values("key", "value"):
            hub_branding[row["key"]] = row["value"] or ""
    except Exception:
        logger.exception("Hub preview: branding non caricato")

    maintenance_by_family: list = []
    try:
        from assets.services.dashboard_kpi import get_maintenance_status_by_family
        maintenance_by_family = get_maintenance_status_by_family()
    except Exception:
        logger.exception("Hub preview: stato manutenzioni per famiglia non caricato")

    safety_kpis = {}
    try:
        from rilevazione_incidenti.services import get_safety_kpis
        safety_kpis = get_safety_kpis()
    except Exception:
        logger.exception("Hub preview: KPI sicurezza non caricati")

    ctx.update({
        "page_title": "Hub Preview",
        "greeting_name": display_name,
        "date_label": date_label,
        "hub_kpis": _hub_kpi_cards(ctx, request),
        "modules": ctx.get("module_cards", []),
        "activities": list(ctx.get("richieste_recenti", []))[:5],
        "pending_approvals": ctx.get("ctx_widget", {}),
        "hub_branding": hub_branding,
        "hub_is_staff": request.user.is_staff,
        "maintenance_by_family": maintenance_by_family,
        "safety_kpis": safety_kpis,
    })
    return render(request, "core/pages/dashboard_hub_preview.html", ctx)
