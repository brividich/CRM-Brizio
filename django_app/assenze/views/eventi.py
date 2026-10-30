"""Viste del modulo Assenze — Calendario ed eventi: menu, calendario, API eventi/colori, conflitti con i corsi, capo predefinito (`calendario` è già la view).

Spacchettamento di ``assenze/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods



from .. import hr as calcoli_hr  # noqa: E402
from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


_COLOR_CACHE_KEY_GLOBAL = "assenze:colors:global:v1"
_COLOR_CACHE_KEY_USER_PREFIX = "assenze:colors:user:v1:"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DEFAULT_COLORS = {
    "tipo_ferie": "#10b981",
    "tipo_permesso": "#3b82f6",
    "tipo_malattia": "#ef4444",
    "tipo_infortunio": "#f97316",
    "tipo_certifica_presenza": "#14b8a6",
    "tipo_altro": "#8b5cf6",
    "stato_in_attesa": "#60a5fa",
    "stato_rifiutato": "#94a3b8",
    "stato_approvato": "#34d399",
}
_COLOR_KEYS = set(_DEFAULT_COLORS.keys())


def _moderation_label(value) -> str:
    parsed = _helpers._as_int(value)
    if parsed is None:
        return "N/D"
    return _helpers._MOD_TO_CONSENSO.get(str(parsed), "N/D")


def _events_manager_scope(request) -> dict | None:
    """Perimetro da passare a `_load_events` per la richiesta corrente.

    `None` = nessun filtro (tutta l'azienda), per chi ha `view_all_assenze`.
    Un dict = solo i dipendenti di cui l'utente e' capo assegnato.
    """
    perms = _helpers._assenze_permissions(request)
    if perms.get("view_scope") == "all":
        return None
    if perms.get("view_scope_source") == "ruoli":
        # Ruoli del portale: perimetro per persone (sé stessi + team d'organigramma).
        ids = set(perms.get("team_utenti_ids") or ()) if perms.get("view_scope") == "reparto" else set()
        if perms.get("legacy_user_id") and perms.get("view_scope") != "none":
            ids.add(int(perms["legacy_user_id"]))
        return {"utenti_ids": sorted(ids)}
    return {
        "legacy_user_id": perms.get("legacy_user_id"),
        "manager_name": perms.get("manager_name") or "",
        "manager_email": perms.get("manager_email") or "",
    }


def _ensure_colors_table() -> None:
    try:
        with _helpers.connections["default"].cursor() as cursor:
            if _helpers._db_vendor() == "sqlite":
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_assenze_colors (
                        color_key TEXT PRIMARY KEY,
                        color_value TEXT NOT NULL,
                        updated_at TEXT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ui_assenze_colors_user (
                        user_key TEXT NOT NULL,
                        color_key TEXT NOT NULL,
                        color_value TEXT NOT NULL,
                        updated_at TEXT NULL,
                        PRIMARY KEY (user_key, color_key)
                    )
                    """
                )
            else:
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_assenze_colors', 'U') IS NULL
                    CREATE TABLE ui_assenze_colors (
                        color_key NVARCHAR(64) NOT NULL PRIMARY KEY,
                        color_value NVARCHAR(7) NOT NULL,
                        updated_at DATETIME2 NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    IF OBJECT_ID('ui_assenze_colors_user', 'U') IS NULL
                    CREATE TABLE ui_assenze_colors_user (
                        user_key NVARCHAR(128) NOT NULL,
                        color_key NVARCHAR(64) NOT NULL,
                        color_value NVARCHAR(7) NOT NULL,
                        updated_at DATETIME2 NULL,
                        CONSTRAINT PK_ui_assenze_colors_user PRIMARY KEY (user_key, color_key)
                    )
                    """
                )
    except Exception:
        return


def _color_cache_ttl() -> int:
    ttl = int(getattr(settings, "ASSENZE_CALENDAR_COLORS_CACHE_TTL", 300) or 300)
    return max(60, ttl)


def _user_color_key(request) -> str:
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return "anon"
    user_id = getattr(request.user, "id", None)
    if user_id is not None:
        return f"id:{user_id}"
    username = str(request.user.get_username() or "").strip().lower()
    return f"user:{username}" if username else "anon"


def _load_global_color_overrides() -> dict[str, str]:
    cached = cache.get(_COLOR_CACHE_KEY_GLOBAL)
    if isinstance(cached, dict):
        return {k: v for k, v in cached.items() if k in _COLOR_KEYS and _COLOR_RE.match(str(v or ""))}

    _ensure_colors_table()
    overrides: dict[str, str] = {}
    try:
        with _helpers.connections["default"].cursor() as cursor:
            cursor.execute("SELECT color_key, color_value FROM ui_assenze_colors")
            for key, value in cursor.fetchall():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k in _COLOR_KEYS and _COLOR_RE.match(v):
                    overrides[k] = v
    except Exception:
        pass

    cache.set(_COLOR_CACHE_KEY_GLOBAL, overrides, timeout=_color_cache_ttl())
    return overrides


def _load_user_color_overrides(user_key: str) -> dict[str, str]:
    cache_key = f"{_COLOR_CACHE_KEY_USER_PREFIX}{user_key}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return {k: v for k, v in cached.items() if k in _COLOR_KEYS and _COLOR_RE.match(str(v or ""))}

    _ensure_colors_table()
    overrides: dict[str, str] = {}
    try:
        with _helpers.connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT color_key, color_value FROM ui_assenze_colors_user WHERE user_key = %s",
                [user_key],
            )
            for key, value in cursor.fetchall():
                k = str(key or "").strip()
                v = str(value or "").strip()
                if k in _COLOR_KEYS and _COLOR_RE.match(v):
                    overrides[k] = v
    except Exception:
        pass

    cache.set(cache_key, overrides, timeout=_color_cache_ttl())
    return overrides


def _load_colors(user_key: str | None = None) -> dict[str, str]:
    colors = dict(_DEFAULT_COLORS)
    colors.update(_load_global_color_overrides())
    if user_key:
        colors.update(_load_user_color_overrides(user_key))
    return colors


def _save_colors(data: dict[str, str], user_key: str | None = None) -> dict[str, str]:
    _ensure_colors_table()
    clean: dict[str, str] = {}
    for key, value in data.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k in _COLOR_KEYS and _COLOR_RE.match(v):
            clean[k] = v

    with transaction.atomic():
        with _helpers.connections["default"].cursor() as cursor:
            for key, value in clean.items():
                if _helpers._db_vendor() == "sqlite":
                    if user_key:
                        cursor.execute(
                            """
                            INSERT INTO ui_assenze_colors_user (user_key, color_key, color_value, updated_at)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_key, color_key) DO UPDATE SET
                                color_value = excluded.color_value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            [user_key, key, value],
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO ui_assenze_colors (color_key, color_value, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT(color_key) DO UPDATE SET
                                color_value = excluded.color_value,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            [key, value],
                        )
                else:
                    if user_key:
                        cursor.execute(
                            """
                            MERGE ui_assenze_colors_user AS target
                            USING (SELECT %s AS user_key, %s AS color_key) AS src
                            ON target.user_key = src.user_key AND target.color_key = src.color_key
                            WHEN MATCHED THEN UPDATE SET
                                color_value = %s,
                                updated_at = SYSUTCDATETIME()
                            WHEN NOT MATCHED THEN
                                INSERT (user_key, color_key, color_value, updated_at)
                                VALUES (%s, %s, %s, SYSUTCDATETIME());
                            """,
                            [user_key, key, value, user_key, key, value],
                        )
                    else:
                        cursor.execute(
                            """
                            MERGE ui_assenze_colors AS target
                            USING (SELECT %s AS color_key) AS src
                            ON target.color_key = src.color_key
                            WHEN MATCHED THEN UPDATE SET
                                color_value = %s,
                                updated_at = SYSUTCDATETIME()
                            WHEN NOT MATCHED THEN
                                INSERT (color_key, color_value, updated_at)
                                VALUES (%s, %s, SYSUTCDATETIME());
                            """,
                            [key, value, key, value],
                        )

    if user_key:
        cache.delete(f"{_COLOR_CACHE_KEY_USER_PREFIX}{user_key}")
    else:
        cache.delete(_COLOR_CACHE_KEY_GLOBAL)
    return _load_colors(user_key=user_key)

def _event_color(tipo: str, consenso: str, colors: dict[str, str], moderation_status: int | None = None) -> str:
    if moderation_status is not None:
        stato = _helpers._MOD_TO_CONSENSO.get(str(moderation_status), _helpers._norm_consenso(consenso))
    else:
        stato = _helpers._norm_consenso(consenso)
    if stato == "Rifiutato":
        return colors.get("stato_rifiutato", _DEFAULT_COLORS["stato_rifiutato"])
    if stato in {"Bozza", "Programmato"}:
        return colors.get("stato_in_attesa", _DEFAULT_COLORS["stato_in_attesa"])
    tipo_key = {
        "Ferie": "tipo_ferie",
        "Permesso": "tipo_permesso",
        "Malattia": "tipo_malattia",
        "Flessibilità": "tipo_infortunio",
        "Certifica presenza": "tipo_certifica_presenza",
        "Altro": "tipo_altro",
    }.get(_helpers._norm_tipo(tipo), "stato_approvato")
    return colors.get(tipo_key, _DEFAULT_COLORS["stato_approvato"])


def _load_events(
    limit: int = 4000,
    start: datetime | None = None,
    end: datetime | None = None,
    colors: dict[str, str] | None = None,
    include_sensitive: bool = False,
    manager_scope: dict | None = None,
) -> list[dict]:
    # SEC/GDPR: `motivazione` e `certificato_medico` (dato sanitario, categoria
    # speciale) sono inclusi negli eventi del calendario SOLO per chi gestisce a
    # livello aziendale (AMMINISTRAZIONE). Per i caporeparto/altri il calendario
    # resta visibile ma senza questi campi (default: esclusi).
    if not _helpers._table_exists("assenze"):
        return []

    # Il JOIN richiede sia la tabella di destinazione sia la colonna FK lato `assenze`:
    # in alcuni ambienti legacy (es. prod) `assenze.dipendente_id` puo' non esistere e
    # referenziarla manda in errore l'intera query (42S22). Vedi guard analogo nel pull.
    has_dip = _helpers._table_exists("dipendenti") and _helpers._has_assenze_column("dipendente_id")
    has_capi = _helpers._table_exists("capi_reparto") and _helpers._has_assenze_column("capo_reparto_id")
    joins = ""
    dip_expr = "a.copia_nome"
    capo_expr = "''"
    if has_dip:
        joins += " LEFT JOIN dipendenti d ON d.id = a.dipendente_id "
        dip_expr = "COALESCE(d.title, a.copia_nome)"
    if has_capi:
        joins += " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id "
        capo_expr = "COALESCE(cr.title, '')"

    where_clauses = ["a.data_inizio IS NOT NULL", "a.data_fine IS NOT NULL"]
    params: list = []

    # SEC: perimetro di visibilita'. `manager_scope` assente = nessun filtro, cioe'
    # tutta l'azienda: e' la vista di chi ha `view_all_assenze`. Con il perimetro di
    # reparto si vedono SOLO i dipendenti di cui si e' capo assegnato — lo stesso
    # insieme che si puo' approvare, calcolato dalla stessa clausola.
    if manager_scope is not None and "utenti_ids" in manager_scope:
        # Perimetro dei ruoli del portale: elenco esplicito di persone. Vuoto o
        # colonna assente = fail-closed.
        ids = [int(i) for i in manager_scope.get("utenti_ids") or []]
        if not ids or not _helpers._has_assenze_column("utente_id"):
            return []
        where_clauses.append(f"a.utente_id IN ({', '.join(['%s'] * len(ids))})")
        params.extend(ids)
    elif manager_scope is not None:
        scope_where, scope_params, use_legacy_join = _helpers._combined_manager_assignment_where_clause(
            legacy_user_id=manager_scope.get("legacy_user_id"),
            manager_name=str(manager_scope.get("manager_name") or ""),
            manager_email=str(manager_scope.get("manager_email") or ""),
            assenze_alias="a",
            capi_alias="cr",
        )
        if not scope_where:
            # Nessun criterio di assegnazione: fail-closed, niente assenze altrui.
            return []
        if use_legacy_join and not has_capi:
            joins += " LEFT JOIN capi_reparto cr ON cr.id = a.capo_reparto_id "
        where_clauses.append(scope_where)
        params.extend(scope_params)
    if start is not None:
        where_clauses.append("a.data_fine >= %s")
        params.append(start)
    if end is not None:
        where_clauses.append("a.data_inizio <= %s")
        params.append(end)

    _cert_col = ", a.certificato_medico" if _helpers._has_assenze_column("certificato_medico") else ""
    base_sql = f"""
        SELECT
            a.id,
            {dip_expr} AS dipendente,
            a.tipo_assenza,
            a.data_inizio,
            a.data_fine,
            a.consenso,
            a.moderation_status,
            a.motivazione_richiesta{_cert_col}{_helpers._col_utente_id()},
            {capo_expr} AS capo
        FROM assenze a
        {joins}
        WHERE {' AND '.join(where_clauses)}
    """
    sql = _helpers._select_limited(base_sql, "ORDER BY a.data_inizio DESC, a.id DESC", limit)
    rows = _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, params))
    resolved_colors = colors or _load_colors()

    events: list[dict] = []
    for row in rows:
        tipo = _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
        moderation_status = _helpers._as_int(row.get("moderation_status"))
        moderation_label = _moderation_label(moderation_status)
        consenso = moderation_label if moderation_label != "N/D" else _helpers._norm_consenso(row.get("consenso"))
        props = {
            "tipo": tipo,
            "consenso": consenso,
            "moderation_status": moderation_status,
            "capo": str(row.get("capo") or ""),
        }
        if include_sensitive:
            props["motivazione"] = _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta"))
            props["certificato_medico"] = str(row.get("certificato_medico") or "")
        events.append(
            {
                "id": row.get("id"),
                "title": str(row.get("dipendente") or "N/D"),
                "start": _helpers._to_isoz(row.get("data_inizio")),
                "end": _helpers._to_isoz(row.get("data_fine")),
                "color": _event_color(tipo, consenso, resolved_colors, moderation_status=moderation_status),
                "extendedProps": props,
            }
        )
    managed = _helpers._sharepoint_managed_ids(e.get("id") for e in events)
    for event in events:
        event["extendedProps"]["gestita_sp"] = _helpers._as_int(event.get("id")) in managed
    return events


@login_required
@require_http_methods(["GET"])
def api_dipendente_default_capo(request):
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_insert_for_others"):
        return _helpers._json_error("Permessi insufficienti.", status=403)
    dipendente_id = _helpers._as_int(request.GET.get("dipendente_id"))
    if not dipendente_id:
        return JsonResponse({"ok": True, "capo_value": ""})
    if not _helpers._can_insert_for_dipendente(request, dipendente_id):
        return _helpers._json_error("Dipendente fuori dal tuo reparto.", status=403)
    identity = _helpers._resolve_employee_identity_from_anagrafica(dipendente_id)
    if not identity:
        return JsonResponse({"ok": False, "capo_value": "", "error": "Dipendente non trovato"})
    emp_name, emp_email, emp_legacy_user_id = identity
    capi = _helpers._load_capi_options()
    capo_value = _helpers._resolve_default_capo_for_user(
        name=emp_name,
        email=emp_email,
        username="",
        capi=capi,
        legacy_user_id=emp_legacy_user_id,
    )
    return JsonResponse({"ok": True, "capo_value": capo_value})


@login_required
def menu(request):
    name, email, legacy_id = _helpers._legacy_identity(request)
    recenti = _helpers._load_personal(name, email, limit=8)
    perms = _helpers._assenze_permissions(request)
    pending_count = 0
    if perms.get("view_scope") in {"all", "reparto"}:
        # Stesso perimetro della dashboard segnalazioni, che apre sempre in scope
        # "mine": contare tutte le pendenti globali mostrerebbe un badge che non
        # corrisponde a nulla di visibile nella pagina di destinazione.
        pending_count = len(
            _helpers._load_pending_for_manager(
                legacy_id,
                limit=200,
                manager_name=name,
                manager_email=email,
            )
        )
    return _helpers.render(
        request,
        "assenze/pages/menu.html",
        {
            "recenti": recenti,
            "car_pending_count": pending_count,
            **_helpers._template_perm_context(request),
        },
    )


@login_required
@ensure_csrf_cookie
def calendario(request):
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_view_calendar"):
        return HttpResponseForbidden("Permessi insufficienti: il tuo gruppo non può visualizzare il calendario assenze.")
    user_key = _user_color_key(request)
    user_colors = _load_colors(user_key=user_key)
    eventi_preview = []
    for event in _load_events(limit=50, colors=user_colors, manager_scope=_events_manager_scope(request)):
        eventi_preview.append(
            {
                "dipendente": event.get("title"),
                "tipo": event.get("extendedProps", {}).get("tipo"),
                "consenso": event.get("extendedProps", {}).get("consenso"),
                "inizio_label": _helpers._dt_label(event.get("start")),
                "fine_label": _helpers._dt_label(event.get("end")),
            }
        )
    from ..htmx_views import _month_nav_ctx, _parse_mese
    mese_date = _parse_mese(request.GET.get("mese", timezone.localdate().strftime("%Y-%m")))
    oggi = timezone.localdate()
    try:
        giorni_non_lavorativi = calcoli_hr.eventi_calendario(oggi - timedelta(days=400), oggi + timedelta(days=400))
    except Exception:
        _helpers.logger.warning("calendario: festività e chiusure non calcolate", exc_info=True)
        giorni_non_lavorativi = []
    return _helpers.render(request, "assenze/pages/calendario.html", {
        "eventi_preview": eventi_preview,
        "giorni_non_lavorativi": giorni_non_lavorativi,
        **_month_nav_ctx(mese_date),
        **_helpers._template_perm_context(request),
    })


@login_required
@require_http_methods(["GET"])
def api_eventi(request):
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_view_calendar"):
        return _helpers._json_error("Permessi insufficienti: calendario non disponibile per il tuo gruppo.", status=403)
    try:
        user_key = _user_color_key(request)
        user_colors = _load_colors(user_key=user_key)
        start = _helpers._parse_input_dt(request.GET.get("start"))
        end = _helpers._parse_input_dt(request.GET.get("end"))
        raw_limit = request.GET.get("limit", getattr(settings, "ASSENZE_CALENDAR_MAX_EVENTS", 1500))
        try:
            limit = int(raw_limit or 1500)
        except (TypeError, ValueError):
            limit = 1500
        limit = max(100, min(limit, 8000))
        return JsonResponse(
            _load_events(
                limit=limit, start=start, end=end, colors=user_colors,
                include_sensitive=bool(perms.get("can_update_any")),
                manager_scope=_events_manager_scope(request),
            ),
            safe=False,
        )
    except Exception as exc:
        return _helpers._json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def api_eventi_colors(request):
    if not _helpers._assenze_permissions(request).get("can_view_calendar"):
        return _helpers._json_error("Permessi insufficienti: colori calendario non disponibili per il tuo gruppo.", status=403)
    user_key = _user_color_key(request)
    if request.method == "GET":
        colors = _load_colors(user_key=user_key)
        return JsonResponse({"ok": True, "scope": "user", "colors": colors, "defaults": dict(_DEFAULT_COLORS)})

    payload = _helpers._request_json(request)
    color_map = payload.get("colors") if isinstance(payload, dict) else None
    if not isinstance(color_map, dict):
        return _helpers._json_error("Body JSON non valido: campo 'colors' mancante", status=400)

    for key, value in color_map.items():
        key_txt = str(key or "").strip()
        value_txt = str(value or "").strip()
        if key_txt in _COLOR_KEYS and not _COLOR_RE.match(value_txt):
            return _helpers._json_error(f"Formato colore non valido per '{key_txt}'", status=400)

    colors = _save_colors(color_map, user_key=user_key)
    return JsonResponse({"ok": True, "scope": "user", "colors": colors, "defaults": dict(_DEFAULT_COLORS)})

@login_required
@require_http_methods(["POST"])
def api_evento_update(request, item_id: int | None = None):
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_edit_events"):
        return _helpers._json_error("Permessi insufficienti: modifica record non consentita.", status=403)

    payload = _helpers._request_json(request)
    target_id = item_id or _helpers._as_int(payload.get("item_id")) or _helpers._as_int(request.POST.get("item_id"))
    if target_id is None:
        return _helpers._json_error("item_id mancante", status=400)

    current = _helpers._get_assenza(target_id)
    if not current:
        return _helpers._json_error("Record non trovato", status=404)
    if not _helpers._can_manage_record(request, current, require_delete=False):
        return _helpers._json_error("Permessi insufficienti: puoi modificare solo record assegnati a te come capo reparto.", status=403)
    managed_error = _helpers._sharepoint_managed_error(target_id)
    if managed_error:
        return managed_error

    requested_tipo = (
        (payload.get("tipo") if payload else None)
        or request.POST.get("tipo")
        or _helpers._tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta"))
    )
    tipo = _helpers._tipo_for_storage(requested_tipo)
    if perms.get("can_update_any"):
        consenso = _helpers._norm_consenso((payload.get("consenso") if payload else None) or request.POST.get("consenso") or current.get("consenso"))
        moderation_status = _helpers._CONSENSO_TO_MOD.get(consenso, 2)
        if consenso != _helpers._norm_consenso(current.get("consenso")) and _helpers._e_propria_assenza(request, current):
            return _helpers._json_error("Non puoi approvare o rifiutare una tua richiesta: decide un altro responsabile.", status=403)
    else:
        consenso = _helpers._norm_consenso(current.get("consenso"))
        moderation_status = _helpers._as_int(current.get("moderation_status"))
        if moderation_status is None:
            moderation_status = _helpers._CONSENSO_TO_MOD.get(consenso, 2)
    inizio_raw = (payload.get("inizio") if payload else None) or request.POST.get("inizio")
    fine_raw = (payload.get("fine") if payload else None) or request.POST.get("fine")
    motivazione = (payload.get("motivazione") if payload else None)
    if motivazione is None:
        motivazione = request.POST.get("motivazione", current.get("motivazione_richiesta") or "")
    motivazione = _helpers._motivazione_for_storage(requested_tipo, motivazione)
    certificato_medico = payload.get("certificato_medico") if payload and "certificato_medico" in payload else None
    if certificato_medico is None:
        certificato_medico = request.POST.get("certificato_medico", current.get("certificato_medico") or "")
    certificato_medico = _helpers._certificato_medico_for_tipo(tipo, certificato_medico, current.get("certificato_medico"))

    dt_start = _helpers._parse_input_dt(inizio_raw) if inizio_raw else current.get("data_inizio")
    dt_end = _helpers._parse_input_dt(fine_raw) if fine_raw else current.get("data_fine")
    dt_end, auto_fine_msg = _helpers._autocorreggi_fine(dt_start, dt_end)
    err_msg, warn_msg = _helpers._validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=str(current.get("copia_nome") or ""),
        person_email=str(current.get("email_esterna") or ""),
        person_anagrafica_id=_helpers._anagrafica_id_for_assenza_row(current),
        exclude_item_id=target_id,
    )
    if err_msg:
        return _helpers._json_error(err_msg, status=400)

    updates = {
        "tipo_assenza": tipo,
        "consenso": consenso,
        "moderation_status": moderation_status,
        "data_inizio": dt_start,
        "data_fine": dt_end,
        "motivazione_richiesta": motivazione,
        "certificato_medico": certificato_medico,
        "modified_datetime": timezone.now(),
    }
    if perms.get("can_update_any"):
        updates.update(_helpers._approval_timestamp_update(consenso, current))

    # Una richiesta già approvata si cambia solo dicendo perché: il motivo resta
    # nello storico della richiesta, visibile a chi la gestisce.
    modifiche = calcoli_hr.differenze(current, updates)
    motivo = str((payload.get("motivo_modifica") if payload else None) or request.POST.get("motivo_modifica") or "").strip()
    era_approvata = _helpers._effective_status(current.get("consenso"), current.get("moderation_status"))[1] == "Approvato"
    if era_approvata and modifiche and not motivo:
        return _helpers._json_error(
            "La richiesta era già approvata: scrivi il motivo della modifica.", status=400,
        )

    ok = _helpers._update_assenza(target_id, updates)
    if not ok:
        return _helpers._json_error("Aggiornamento non eseguito", status=500)
    if modifiche:
        nuovo_stato = consenso if consenso != _helpers._norm_consenso(current.get("consenso")) else ""
        calcoli_hr.registra(
            target_id,
            {"Approvato": "approvata", "Rifiutato": "rifiutata"}.get(nuovo_stato, "modificata"),
            utente=request.user.get_username(),
            prima=current,
            dopo=updates,
            motivo=motivo,
        )
        _helpers._notify_assenza_modificata(request, current, modifiche, motivo=motivo)

    sync_result = _helpers._sp_enqueue_upsert(target_id)

    return JsonResponse({
        "ok": True,
        "item_id": target_id,
        "sync": sync_result,
        "warning": " ".join(x for x in [auto_fine_msg, warn_msg] if x),
    })


@login_required
@require_http_methods(["POST"])
def api_evento_delete(request, item_id: int | None = None):
    perms = _helpers._assenze_permissions(request)
    can_delete_any = perms.get("can_delete_any", False)

    payload = _helpers._request_json(request)
    target_id = item_id or _helpers._as_int(payload.get("item_id")) or _helpers._as_int(request.POST.get("item_id"))
    if target_id is None:
        return _helpers._json_error("item_id mancante", status=400)

    current = _helpers._get_assenza(target_id)
    if not current:
        return _helpers._json_error("Record non trovato", status=404)

    if not can_delete_any:
        # Utenti non-admin possono eliminare solo le proprie richieste.
        if not perms.get("can_insert"):
            return _helpers._json_error("Permessi insufficienti: eliminazione record non consentita.", status=403)
        name, email, legacy_user_id = _helpers._legacy_identity(request)
        username = str(request.user.get_username() or "").strip()
        rec_utente_id = _helpers._as_int(current.get("utente_id"))
        rec_username = str(current.get("aliasusername") or "").strip()
        rec_email = str(current.get("email_esterna") or "").strip()
        rec_nome = str(current.get("copia_nome") or "").strip()
        # Proprieta' del record: si privilegiano gli identificatori UNIVOCI
        # (utente_id legacy, poi username, poi email). Il confronto sul nome
        # visualizzato e' solo fallback per i record legacy privi di id/username:
        # da solo non e' affidabile (omonimie) e non deve abilitare la delete
        # quando esiste un identificatore univoco che invece non combacia.
        if legacy_user_id is not None and rec_utente_id is not None:
            is_own = rec_utente_id == legacy_user_id
        elif username and rec_username:
            is_own = rec_username.casefold() == username.casefold()
        elif email and rec_email:
            is_own = rec_email.casefold() == email.casefold()
        else:
            is_own = bool(name) and rec_nome.casefold() == str(name).strip().casefold()
        if not is_own:
            return _helpers._json_error("Permessi insufficienti: puoi eliminare solo le tue richieste.", status=403)
    managed_error = _helpers._sharepoint_managed_error(target_id)
    if managed_error:
        return managed_error

    # Stessa transazione: la coda di eliminazione esiste solo se il record e' davvero cancellato.
    with transaction.atomic():
        _helpers._sp_enqueue_delete(target_id, current.get("sharepoint_item_id"))
        if not _helpers._delete_assenza(target_id):
            transaction.set_rollback(True)
            return _helpers._json_error("Eliminazione non riuscita", status=500)

    calcoli_hr.registra(
        target_id, "eliminata", utente=request.user.get_username(),
        motivo=str((payload.get("motivo_modifica") if payload else None) or "").strip(),
    )

    # Notifica mail SOLO per richieste gia' approvate (moderation_status == 0;
    # default 2 = in attesa). Best-effort: un errore mail non deve ribaltare
    # l'eliminazione gia' avvenuta.
    if _helpers._as_int(current.get("moderation_status")) == 0:
        try:
            _helpers._notify_assenza_deleted(request, current)
        except Exception:
            _helpers.logger.warning(
                "api_evento_delete: notifica eliminazione fallita per id=%s",
                target_id,
                exc_info=True,
            )

    return JsonResponse({"ok": True, "item_id": target_id})


# ─────────────────────────────────────────────────────────────────────────────
# CHECK FORMAZIONE: avviso non bloccante se richiesta assenza copre date di corsi
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def api_check_corsi(request):
    """Ritorna corsi/sessioni del dipendente che intersecano il range
    [date_start, date_end]. Non blocca: serve solo a popolare un avviso UI.

    Query params: date_start (obbl.), date_end (opz., default=date_start),
    legacy_id (opz., default=utente corrente; serve permesso caporeparto/admin se altro).

    Response JSON: { ok, n_conflicts, conflicts: [{date, session_id, code, title, ...}] }
    """
    from datetime import datetime as _dt

    def _parse(s):
        if not s: return None
        try: return _dt.strptime(s.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError): return None

    d_start = _parse(request.GET.get("date_start"))
    d_end   = _parse(request.GET.get("date_end")) or d_start
    if d_start is None:
        return JsonResponse({"ok": False, "error": "date_start mancante o non valida"}, status=400)
    if d_end < d_start:
        d_start, d_end = d_end, d_start

    _name, _email, my_legacy = _helpers._legacy_identity(request)
    raw_legacy = (request.GET.get("legacy_id") or "").strip()
    if raw_legacy:
        try:
            legacy_id = int(raw_legacy)
        except ValueError:
            return JsonResponse({"ok": False, "error": "legacy_id non valido"}, status=400)
        if my_legacy is None or int(my_legacy) != legacy_id:
            # SEC: per controllare un ALTRO dipendente serve lo scope effettivo
            # (AMMINISTRAZIONE = tutti, caporeparto = solo il proprio reparto), come
            # per l'inserimento per altri. Prima bastava essere un caporeparto
            # qualsiasi → enumerazione dei corsi di qualunque dipendente.
            if not _helpers._can_insert_for_dipendente(request, legacy_id):
                return JsonResponse({"ok": False, "error": "Non hai i permessi per controllare questo dipendente"}, status=403)
    else:
        if my_legacy is None:
            return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})
        legacy_id = int(my_legacy)

    try:
        from anagrafica.models_formazione import TrainingEnrollment, TrainingSession
    except Exception:
        return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})

    sess_ids = list(
        TrainingEnrollment.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("sessione_id", flat=True)
    )
    if not sess_ids:
        return JsonResponse({"ok": True, "n_conflicts": 0, "conflicts": []})

    qs = (
        TrainingSession.objects
        .select_related("corso")
        .filter(pk__in=sess_ids, data_inizio__lte=d_end, data_fine__gte=d_start)
        .exclude(stato="ANNULLATA")
        .order_by("data_inizio")
    )

    conflicts = []
    for s in qs:
        first_overlap = max(s.data_inizio, d_start)
        conflicts.append({
            "date":          first_overlap.strftime("%Y-%m-%d"),
            "date_label":    first_overlap.strftime("%d-%m-%Y"),
            "session_id":    s.pk,
            "code":          s.codice_sessione,
            "title":         s.corso.titolo,
            "course_code":   s.corso.codice,
            "data_inizio":   s.data_inizio.strftime("%Y-%m-%d"),
            "data_fine":     s.data_fine.strftime("%Y-%m-%d"),
            "stato":         s.stato,
            "stato_display": s.get_stato_display(),
            "url":           f"/anagrafica/formazione/sessioni/{s.pk}/",
        })

    return JsonResponse({"ok": True, "n_conflicts": len(conflicts), "conflicts": conflicts})
