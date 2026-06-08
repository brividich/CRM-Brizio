import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.context_processors import (
    _UI_PREFS_DEFAULTS,
    _UI_PREFS_SESSION_KEY,
    compact_sidebar_footer_actions,
    get_default_sidebar_footer_actions,
    get_sidebar_footer_catalog,
    legacy_nav,
    normalize_sidebar_footer_actions,
)
from core.exporting import export_rows_response
from core.impersonation import clear_impersonation_state, display_name_for_user, get_impersonation_state, is_impersonation_stop_path
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns
from core.module_registry import get_registered_modules, resolve_module_label
from core.models import OptioneConfig, UserExtraInfo, UserUiPreference


_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_MODULE_REGISTRY = get_registered_modules()
_NAV_CODE_TO_MODULE_KEY: dict[str, str] = {}
for _module_key, _definition in _MODULE_REGISTRY.items():
    for _nav_code in _definition.navigation_codes:
        _normalized_code = str(_nav_code or "").strip().lower()
        if _normalized_code:
            _NAV_CODE_TO_MODULE_KEY[_normalized_code] = _module_key

_ONBOARDING_NOTIFICATION_SPECS: tuple[dict[str, object], ...] = (
    {
        "key": "assenze",
        "label": "Assenze e presenze",
        "description": "Aggiornamenti sulle tue richieste di assenza, approvazioni e rifiuti.",
        "default": True,
        "module_keys": {"assenze"},
    },
    {
        "key": "comunicazioni",
        "label": "Comunicazioni aziendali",
        "description": "Notizie, avvisi e comunicazioni dalla direzione.",
        "default": True,
        "module_keys": {"notizie"},
    },
    {
        "key": "scadenzari",
        "label": "Scadenzari e manutenzioni",
        "description": "Promemoria per scadenze, DPI, verifiche periodiche e procedure assegnate.",
        "default": True,
        "module_keys": {"assets", "dpi", "procedure_refresh", "rentri"},
    },
    {
        "key": "ticket",
        "label": "Ticket e segnalazioni",
        "description": "Aggiornamenti sui ticket aperti o assegnati a te.",
        "default": False,
        "module_keys": {"tickets"},
    },
)


def _ui_prefs_session_payload(prefs: UserUiPreference) -> dict:
    return {
        "nav_mode": prefs.nav_mode,
        "theme_mode": getattr(prefs, "theme_mode", "light"),
        "font_scale": prefs.font_scale,
        "sidebar_collapsed": prefs.sidebar_collapsed,
        "sidebar_footer_actions": normalize_sidebar_footer_actions(
            prefs.sidebar_footer_actions, fallback_to_default=True
        ),
    }


def _get_current_ui_prefs_for_user(user) -> dict:
    prefs = UserUiPreference.objects.filter(user=user).first()
    if prefs:
        return _ui_prefs_session_payload(prefs)
    return {
        "nav_mode": _UI_PREFS_DEFAULTS["nav_mode"],
        "theme_mode": _UI_PREFS_DEFAULTS["theme_mode"],
        "font_scale": _UI_PREFS_DEFAULTS["font_scale"],
        "sidebar_collapsed": _UI_PREFS_DEFAULTS["sidebar_collapsed"],
        "sidebar_footer_actions": get_default_sidebar_footer_actions(),
    }


def _save_user_ui_preferences(
    request,
    *,
    nav_mode: str = "",
    theme_mode: str = "",
    font_scale: str = "",
    sidebar_collapsed_raw: str | None = None,
    sidebar_footer_actions_raw=None,
) -> tuple[UserUiPreference, dict]:
    prefs, _ = UserUiPreference.objects.get_or_create(
        user=request.user,
        defaults={
            "nav_mode": _UI_PREFS_DEFAULTS["nav_mode"],
            "theme_mode": "light",
            "font_scale": "normal",
            "sidebar_collapsed": False,
            "sidebar_footer_actions": None,
        },
    )

    changed = False
    if nav_mode in _VALID_NAV_MODES and prefs.nav_mode != nav_mode:
        prefs.nav_mode = nav_mode
        changed = True
    if theme_mode in _VALID_THEME_MODES and getattr(prefs, "theme_mode", "") != theme_mode:
        prefs.theme_mode = theme_mode
        changed = True
    if font_scale in _VALID_FONT_SCALES and prefs.font_scale != font_scale:
        prefs.font_scale = font_scale
        changed = True
    if sidebar_collapsed_raw in {"0", "1"}:
        collapsed = sidebar_collapsed_raw == "1"
        if prefs.sidebar_collapsed != collapsed:
            prefs.sidebar_collapsed = collapsed
            changed = True
    if sidebar_footer_actions_raw is not None:
        compact_actions = compact_sidebar_footer_actions(sidebar_footer_actions_raw)
        if prefs.sidebar_footer_actions != compact_actions:
            prefs.sidebar_footer_actions = compact_actions
            changed = True

    if changed:
        prefs.save()

    session_data = _ui_prefs_session_payload(prefs)
    try:
        request.session[_UI_PREFS_SESSION_KEY] = session_data
    except Exception:
        pass
    return prefs, session_data


def _module_key_from_nav_item(item) -> str:
    modulo = str(getattr(item, "modulo", "") or "").strip().lower()
    if modulo in _MODULE_REGISTRY:
        return modulo
    codice = str(getattr(item, "codice", "") or "").strip().lower()
    return _NAV_CODE_TO_MODULE_KEY.get(codice, "")


def _visible_module_keys_for_request(request) -> set[str]:
    try:
        nav_items = list((legacy_nav(request) or {}).get("nav_items") or [])
    except Exception:
        nav_items = []
    visible: set[str] = set()
    for item in nav_items:
        module_key = _module_key_from_nav_item(item)
        if module_key:
            visible.add(module_key)
    return visible


def _build_onboarding_notification_options(request, onboarding=None) -> list[dict[str, object]]:
    visible_module_keys = _visible_module_keys_for_request(request)
    saved_config = onboarding.notifiche_config if onboarding and isinstance(onboarding.notifiche_config, dict) else {}
    options: list[dict[str, object]] = []
    for spec in _ONBOARDING_NOTIFICATION_SPECS:
        key = str(spec["key"])
        label = str(spec["label"])
        default_enabled = bool(spec.get("default", True))
        module_keys = {str(value).strip().lower() for value in spec.get("module_keys", set()) if str(value).strip()}
        visible = bool(visible_module_keys.intersection(module_keys))
        enabled = bool(saved_config.get(key, default_enabled if visible else False))
        visible_labels = sorted(
            {
                resolve_module_label(module_key, fallback=module_key.replace("_", " ").title(), surface="menu")
                for module_key in module_keys
                if module_key in visible_module_keys
            }
        )
        options.append(
            {
                "key": key,
                "label": label,
                "description": str(spec["description"]),
                "default": default_enabled,
                "visible": visible,
                "enabled": enabled,
                "visible_module_labels": visible_labels,
            }
        )
    return options


def _csrf_recovery_target(request, login_path: str) -> str:
    referer = (request.META.get("HTTP_REFERER") or "").strip()
    if referer and url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        parsed = urlsplit(referer)
        target = parsed.path or login_path
        if parsed.query:
            target = f"{target}?{parsed.query}"
        return target

    if request.method in _SAFE_HTTP_METHODS:
        return request.path

    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return reverse("dashboard_home")

    return login_path


def _append_query_param(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _is_json_request(request) -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    content_type = (request.headers.get("Content-Type") or "").lower()
    requested_with = (request.headers.get("X-Requested-With") or "").lower()
    path = request.path or ""
    return (
        "application/json" in accept
        or "application/json" in content_type
        or requested_with == "xmlhttprequest"
        or "/api/" in path
    )


def _current_legacy_user_id(request) -> int | None:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user or not getattr(legacy_user, "id", None):
        return None
    try:
        return int(legacy_user.id)
    except Exception:
        return None


def _notification_panel_context(request) -> dict:
    from core.models import Notifica

    legacy_user_id = _current_legacy_user_id(request)
    if not legacy_user_id:
        return {"notifications": [], "unread_count": 0, "latest_count": 0}
    qs = Notifica.objects.filter(legacy_user_id=legacy_user_id)
    notifications = list(qs.order_by("-created_at")[:8])
    unread_count = qs.filter(letta=False).count()
    return {
        "notifications": notifications,
        "unread_count": unread_count,
        "latest_count": len(notifications),
    }


def _notification_payload(notifica) -> dict:
    created_at = getattr(notifica, "created_at", None)
    if created_at:
        created_local = timezone.localtime(created_at)
        created_iso = created_local.isoformat()
        created_label = created_local.strftime("%d-%m-%Y %H:%M")
    else:
        created_iso = ""
        created_label = ""
    return {
        "id": notifica.id,
        "tipo": notifica.tipo,
        "tipo_label": notifica.get_tipo_display(),
        "messaggio": notifica.messaggio,
        "url_azione": notifica.url_azione or "",
        "created_at": created_iso,
        "created_label": created_label,
        "letta": bool(notifica.letta),
    }


def csrf_failure(request, reason=""):
    """Custom CSRF failure view.

    Quando il cookie manca (tipicamente da browser/VPN che non ha ancora il cookie),
    reindirizza alla login con un messaggio invece di mostrare il 403 tecnico.
    Per qualsiasi altra pagina mostra una pagina italiana con pulsante reload.
    """
    from django.contrib import messages

    login_path = reverse("login")
    # Se il cookie manca del tutto, basta un reload con GET per ottenerlo
    if "cookie" in reason.lower():
        target = _csrf_recovery_target(request, login_path)
        if request.method not in _SAFE_HTTP_METHODS and target.rstrip("/") != login_path.rstrip("/"):
            target = _append_query_param(target, "csrf_retry", "1")
        if _is_json_request(request):
            return JsonResponse(
                {
                    "ok": False,
                    "csrf_retry": True,
                    "error": "Sessione scaduta o cookie mancante. Ricarico la pagina e riprova.",
                    "reload_url": target,
                },
                status=403,
            )
        if request.path.rstrip("/") == login_path.rstrip("/"):
            messages.warning(request, "Sessione scaduta o cookie mancante. Riprova il login.")
            return redirect(login_path)
        messages.warning(request, "Sessione scaduta o cookie mancante. Riapri la pagina e riprova.")
        return redirect(target)

    return render(
        request,
        "core/pages/csrf_failure.html",
        {"reason": reason, "login_path": login_path},
        status=403,
    )


def health(request):
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")


def version(request):
    version_value = getattr(settings, "APP_VERSION", "0.0.0")
    version_file = Path(settings.BASE_DIR) / "VERSION"
    if version_file.exists():
        try:
            file_value = version_file.read_text(encoding="utf-8").strip()
            if file_value:
                version_value = file_value
        except OSError:
            pass
    return HttpResponse(version_value, content_type="text/plain; charset=utf-8")


def _italian_date_label() -> str:
    dt = timezone.now().astimezone(ZoneInfo(getattr(settings, "TIME_ZONE", "Europe/Rome")))
    weekdays = [
        "Lunedì",
        "Martedì",
        "Mercoledì",
        "Giovedì",
        "Venerdì",
        "Sabato",
        "Domenica",
    ]
    months = [
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ]
    return f"{weekdays[dt.weekday()]} {dt.day} {months[dt.month - 1]} {dt.year} - Hub Operativo"


def dashboard(request):
    stats = [
        {"icon": "✅", "icon_class": "green", "value": 12, "label": "Approvate"},
        {"icon": "⏳", "icon_class": "yellow", "value": 3, "label": "In attesa"},
        {"icon": "⚠️", "icon_class": "red", "value": 7, "label": "Anomalie aperte"},
        {"icon": "👥", "icon_class": "blue", "value": 48, "label": "Utenti attivi"},
    ]
    modules = [
        {"icon": "📅", "name": "Gestione Assenze", "sub": "Visualizza richieste", "url_name": "assenze_menu"},
        {"icon": "✏️", "name": "Richiedi Assenza", "sub": "Nuovo permesso/ferie", "url_name": "assenze_richiesta"},
        {"icon": "👥", "name": "Utenti", "sub": "Gestione anagrafica", "url_name": "coming_admin"},
        {"icon": "🔒", "name": "Permessi", "sub": "Ruoli e accessi", "url_name": "coming_admin"},
        {"icon": "⚠️", "name": "Anomalie", "sub": "Non conformità", "url_name": "coming_anomalie"},
        {"icon": "💻", "name": "Asset", "sub": "Inventario", "url_name": "coming_admin"},
    ]
    activities = [
        {"dot_class": "", "text": "M. Rossi ha richiesto 3 giorni di ferie", "time": "Oggi, 08:42"},
        {"dot_class": "green", "text": "Assenza di G. Verdi approvata", "time": "Ieri, 16:15"},
        {"dot_class": "blue", "text": "Nuovo utente aggiunto: F. Bianchi", "time": "Ieri, 11:30"},
        {"dot_class": "", "text": "Anomalia #047 segnalata - Qualità", "time": "24 feb, 14:20"},
        {"dot_class": "green", "text": "Permesso di L. Neri approvato", "time": "24 feb, 09:05"},
    ]

    display_name = "Guest"
    if request.user.is_authenticated:
        display_name = request.user.get_full_name() or request.user.get_username()

    context = {
        "page_title": "Dashboard",
        "greeting_name": display_name,
        "date_label": _italian_date_label(),
        "pending_approvals": 3,
        "stats": stats,
        "modules": modules,
        "activities": activities,
    }
    return render(request, "core/pages/dashboard.html", context)


def root_redirect_to_dashboard(request):
    """Mantiene / come entrypoint tecnico ma forza l'URL canonico /dashboard."""
    return redirect("dashboard_home")


def _coming_soon(request, section_title: str):
    return render(
        request,
        "core/pages/coming_soon.html",
        {
            "page_title": section_title,
            "section_title": section_title,
            "date_label": _italian_date_label(),
        },
    )


def coming_assenze(request):
    return redirect("assenze_menu")


def coming_anomalie(request):
    return _coming_soon(request, "Anomalie")


def coming_admin(request):
    return redirect("admin_portale:index")


def _anagrafica_columns(needed: list[str]) -> list[str]:
    cols = legacy_table_columns("anagrafica_dipendenti")
    return [c for c in needed if c in cols]


_TEAM_MANAGER_ROLES = {"caporeparto", "capo reparto", "car"}


def _legacy_role_name(legacy_user) -> str:
    return " ".join(str(getattr(legacy_user, "ruolo", "") or "").strip().lower().split())


def _can_manage_team_assignments(legacy_user) -> bool:
    return bool(is_legacy_admin(legacy_user) or _legacy_role_name(legacy_user) in _TEAM_MANAGER_ROLES)


def _load_option_values(tipo: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in (
        OptioneConfig.objects.filter(tipo__iexact=tipo, is_active=True)
        .order_by("ordine", "valore", "id")
        .values_list("valore", flat=True)
    ):
        txt = str(value or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def _resolve_effective_reparto(legacy_user_id: int | None) -> str:
    if not legacy_user_id:
        return ""
    extra = UserExtraInfo.objects.filter(legacy_user_id=legacy_user_id).only("reparto").first()
    if extra and str(extra.reparto or "").strip():
        return str(extra.reparto or "").strip()
    try:
        ana = AnagraficaDipendente.objects.filter(utente_id=legacy_user_id).only("reparto").first()
    except Exception:
        ana = None
    return str(getattr(ana, "reparto", "") or "").strip()


def _resolve_team_manager_value(legacy_user, caporeparto_options: list[str] | None = None) -> str:
    options = caporeparto_options if caporeparto_options is not None else _load_option_values("caporeparto")
    by_key = {str(v).strip().lower(): str(v).strip() for v in options if str(v or "").strip()}
    candidates = [
        str(getattr(legacy_user, "nome", "") or "").strip(),
        str(getattr(legacy_user, "email", "") or "").strip(),
    ]
    for candidate in candidates:
        key = candidate.lower()
        if key and key in by_key:
            return by_key[key]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


@login_required
def profilo(request):
    legacy_user = get_legacy_user(request.user)
    profile = getattr(request.user, "profile", None)

    anagrafica_row: dict | None = None
    extra_info = None
    try:
        select_cols = _anagrafica_columns(
            ["nome", "cognome", "reparto", "mansione", "email", "aliasusername", "attivo"]
        )
        if not select_cols:
            raise RuntimeError("anagrafica_dipendenti non disponibile")
        with connections["default"].cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(select_cols)} "
                "FROM anagrafica_dipendenti WHERE LOWER(aliasusername) = LOWER(%s)",
                [request.user.username],
            )
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            if row:
                anagrafica_row = dict(zip(cols, row))
    except Exception:
        pass

    if legacy_user:
        extra_info = UserExtraInfo.objects.filter(legacy_user_id=legacy_user.id).first()

    from core.models import UserOnboarding
    onboarding = UserOnboarding.objects.filter(user=request.user).first()

    # Lista (label, abilitato) per il template — nessuna logica nel template
    onboarding_notifiche = []
    if onboarding and onboarding.completed:
        onboarding_notifiche = [
            (option["label"], option["enabled"])
            for option in _build_onboarding_notification_options(request, onboarding=onboarding)
            if option["visible"]
        ]

    return render(request, "core/pages/profilo.html", {
        "page_title": "Profilo",
        "legacy_user": legacy_user,
        "profile": profile,
        "anagrafica_row": anagrafica_row,
        "extra_info": extra_info,
        "onboarding": onboarding,
        "onboarding_notifiche": onboarding_notifiche,
        "can_manage_team_assignments": _can_manage_team_assignments(legacy_user),
    })


@login_required
def gestione_reparto(request):
    legacy_user = get_legacy_user(request.user)
    if not _can_manage_team_assignments(legacy_user):
        return render(request, "core/pages/forbidden.html", status=403)

    q = str(request.GET.get("q") or "").strip()
    is_admin = is_legacy_admin(legacy_user)
    reparti_options = _load_option_values("reparto")
    caporeparto_options = _load_option_values("caporeparto")
    reparti_keys = {v.lower() for v in reparti_options}
    caporeparto_keys = {v.lower() for v in caporeparto_options}
    manager_reparto = _resolve_effective_reparto(getattr(legacy_user, "id", None))
    manager_caporeparto = _resolve_team_manager_value(legacy_user, caporeparto_options)

    rows: list[dict] = []
    try:
        utenti_qs = UtenteLegacy.objects.filter(attivo=True)
        if q:
            utenti_qs = utenti_qs.filter(Q(nome__icontains=q) | Q(email__icontains=q))
        utenti = list(utenti_qs.order_by("nome", "email", "id")[:200])
        user_ids = [int(u.id) for u in utenti]
        extra_map = {int(obj.legacy_user_id): obj for obj in UserExtraInfo.objects.filter(legacy_user_id__in=user_ids)}
        ana_map = {int(obj.utente_id): obj for obj in AnagraficaDipendente.objects.filter(utente_id__in=user_ids)}

        for utente in utenti:
            extra = extra_map.get(int(utente.id))
            ana = ana_map.get(int(utente.id))
            reparto_attuale = ""
            if extra and str(extra.reparto or "").strip():
                reparto_attuale = str(extra.reparto or "").strip()
            elif ana and str(ana.reparto or "").strip():
                reparto_attuale = str(ana.reparto or "").strip()
            caporeparto_attuale = str(extra.caporeparto or "").strip() if extra else ""

            if not is_admin and not q and manager_reparto:
                reparto_key = reparto_attuale.lower()
                if reparto_key and reparto_key != manager_reparto.lower():
                    continue

            rows.append(
                {
                    "id": int(utente.id),
                    "nome": str(utente.nome or "").strip() or f"Utente #{utente.id}",
                    "email": str(utente.email or "").strip(),
                    "ruolo": str(utente.ruolo or "").strip(),
                    "reparto_attuale": reparto_attuale,
                    "caporeparto_attuale": caporeparto_attuale,
                    "reparto_in_options": reparto_attuale.lower() in reparti_keys if reparto_attuale else False,
                    "caporeparto_in_options": caporeparto_attuale.lower() in caporeparto_keys if caporeparto_attuale else False,
                }
            )
    except Exception:
        rows = []

    return render(
        request,
        "core/pages/gestione_reparto.html",
        {
            "page_title": "Gestione reparto",
            "legacy_user": legacy_user,
            "is_admin": is_admin,
            "q": q,
            "rows": rows,
            "reparti_options": reparti_options,
            "caporeparto_options": caporeparto_options,
            "manager_reparto": manager_reparto,
            "manager_caporeparto": manager_caporeparto,
        },
    )


@login_required
@require_POST
def api_gestione_reparto_assegna(request, user_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _can_manage_team_assignments(legacy_user):
        return JsonResponse({"ok": False, "error": "Permessi insufficienti."}, status=403)

    target = UtenteLegacy.objects.filter(id=user_id).first()
    if target is None:
        return JsonResponse({"ok": False, "error": "Utente non trovato."}, status=404)

    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    if is_legacy_admin(legacy_user):
        reparto = str(payload.get("reparto") or "").strip()[:200]
        caporeparto = str(payload.get("caporeparto") or "").strip()[:200]
    else:
        reparto = _resolve_effective_reparto(getattr(legacy_user, "id", None))[:200]
        if not reparto:
            return JsonResponse(
                {"ok": False, "error": "Imposta prima il tuo reparto nel profilo o nell'anagrafica utente."},
                status=400,
            )
        requested_reparto = str(payload.get("reparto") or "").strip()
        if requested_reparto and requested_reparto.lower() != reparto.lower():
            return JsonResponse({"ok": False, "error": "Puoi assegnare solo il tuo reparto."}, status=403)
        caporeparto = _resolve_team_manager_value(legacy_user, _load_option_values("caporeparto"))[:200]

    extra_info, _created = UserExtraInfo.objects.get_or_create(legacy_user_id=int(target.id))
    extra_info.reparto = reparto
    extra_info.caporeparto = caporeparto
    extra_info.save()

    return JsonResponse(
        {
            "ok": True,
            "reparto": reparto,
            "caporeparto": caporeparto,
            "utente": str(target.nome or target.email or f"Utente #{target.id}").strip(),
        }
    )


@login_required
def rubrica(request):
    q = request.GET.get("q", "").strip()
    reparto_sel = request.GET.get("reparto", "").strip()
    mansione_sel = request.GET.get("mansione", "").strip()

    dipendenti = []
    reparti = []
    mansioni = []
    try:
        select_cols = _anagrafica_columns(["nome", "cognome", "reparto", "mansione", "email", "aliasusername", "attivo"])
        if "attivo" not in select_cols:
            raise RuntimeError("Colonna attivo non presente")
        with connections["default"].cursor() as cur:
            sql = (
                f"SELECT {', '.join(select_cols)} "
                "FROM anagrafica_dipendenti WHERE attivo = 1"
            )
            params: list = []
            if q:
                sql += " AND (LOWER(COALESCE(nome,'')) LIKE %s OR LOWER(COALESCE(cognome,'')) LIKE %s OR LOWER(COALESCE(email,'')) LIKE %s)"
                like = f"%{q.lower()}%"
                params += [like, like, like]
            if reparto_sel:
                sql += " AND reparto = %s"
                params.append(reparto_sel)
            if mansione_sel and "mansione" in select_cols:
                sql += " AND mansione = %s"
                params.append(mansione_sel)
            sql += " ORDER BY cognome, nome"
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            dipendenti = [dict(zip(cols, row)) for row in cur.fetchall()]

        with connections["default"].cursor() as cur:
            if "reparto" in select_cols:
                cur.execute(
                    "SELECT DISTINCT reparto FROM anagrafica_dipendenti "
                    "WHERE attivo = 1 AND reparto IS NOT NULL AND reparto <> '' "
                    "ORDER BY reparto"
                )
                reparti = [r[0] for r in cur.fetchall()]
            if "mansione" in select_cols:
                cur.execute(
                    "SELECT DISTINCT mansione FROM anagrafica_dipendenti "
                    "WHERE attivo = 1 AND mansione IS NOT NULL AND mansione <> '' "
                    "ORDER BY mansione"
                )
                mansioni = [r[0] for r in cur.fetchall()]
    except Exception:
        pass

    return render(request, "core/pages/rubrica.html", {
        "page_title": "Rubrica",
        "dipendenti": dipendenti,
        "reparti": reparti,
        "mansioni": mansioni,
        "q": q,
        "reparto_sel": reparto_sel,
        "mansione_sel": mansione_sel,
    })


@login_required
def organigramma(request):
    q = request.GET.get("q", "").strip()
    reparto_sel = request.GET.get("reparto", "").strip()
    mansione_sel = request.GET.get("mansione", "").strip()

    reparti: list[str] = []
    mansioni: list[str] = []
    gruppi: list[dict] = []
    totale = 0

    try:
        select_cols = _anagrafica_columns(["nome", "cognome", "reparto", "mansione", "email", "aliasusername", "attivo"])
        if "attivo" not in select_cols:
            raise RuntimeError("Colonna attivo non presente")
        with connections["default"].cursor() as cur:
            sql = (
                f"SELECT {', '.join(select_cols)} "
                "FROM anagrafica_dipendenti WHERE attivo = 1"
            )
            params: list = []
            if q:
                sql += " AND (LOWER(COALESCE(nome,'')) LIKE %s OR LOWER(COALESCE(cognome,'')) LIKE %s OR LOWER(COALESCE(email,'')) LIKE %s)"
                like = f"%{q.lower()}%"
                params += [like, like, like]
            if reparto_sel and "reparto" in select_cols:
                sql += " AND reparto = %s"
                params.append(reparto_sel)
            if mansione_sel and "mansione" in select_cols:
                sql += " AND mansione = %s"
                params.append(mansione_sel)
            sql += " ORDER BY reparto, mansione, cognome, nome"
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        by_key: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            reparto = str(r.get("reparto") or "").strip() or "Senza reparto"
            mansione = str(r.get("mansione") or "").strip() or "Senza mansione"
            by_key.setdefault((reparto, mansione), []).append(r)

        grouped_by_reparto: dict[str, dict] = {}
        for (reparto, mansione), people in by_key.items():
            blocco = grouped_by_reparto.setdefault(reparto, {"reparto": reparto, "mansioni": [], "count": 0})
            blocco["mansioni"].append({"mansione": mansione, "count": len(people), "persone": people})
            blocco["count"] += len(people)

        gruppi = sorted(grouped_by_reparto.values(), key=lambda g: g["reparto"].lower())
        for g in gruppi:
            g["mansioni"].sort(key=lambda x: x["mansione"].lower())
            totale += int(g["count"])

        with connections["default"].cursor() as cur:
            if "reparto" in select_cols:
                cur.execute(
                    "SELECT DISTINCT reparto FROM anagrafica_dipendenti "
                    "WHERE attivo = 1 AND reparto IS NOT NULL AND reparto <> '' "
                    "ORDER BY reparto"
                )
                reparti = [r[0] for r in cur.fetchall()]
            if "mansione" in select_cols:
                cur.execute(
                    "SELECT DISTINCT mansione FROM anagrafica_dipendenti "
                    "WHERE attivo = 1 AND mansione IS NOT NULL AND mansione <> '' "
                    "ORDER BY mansione"
                )
                mansioni = [r[0] for r in cur.fetchall()]
    except Exception:
        pass

    return render(
        request,
        "core/pages/organigramma.html",
        {
            "page_title": "Organigramma",
            "q": q,
            "reparto_sel": reparto_sel,
            "mansione_sel": mansione_sel,
            "reparti": reparti,
            "mansioni": mansioni,
            "gruppi": gruppi,
            "totale": totale,
        },
    )


@login_required
def notifiche(request):
    from core.models import Notifica
    legacy_user = get_legacy_user(request.user)
    if not legacy_user:
        lista = []
    else:
        qs = Notifica.objects.filter(legacy_user_id=legacy_user.id)
        if (request.GET.get("export") or "").strip().lower() in {"csv", "xlsx"}:
            return export_rows_response(
                rows=qs.order_by("-created_at")[:500],
                columns=[
                    ("Data", "created_at"),
                    ("Tipo", lambda n: n.get_tipo_display()),
                    ("Messaggio", "messaggio"),
                    ("Letta", lambda n: "Si" if n.letta else "No"),
                    ("URL", "url_azione"),
                ],
                filename="notifiche",
                fmt=request.GET.get("export"),
            )
        lista = list(qs[:50])
        # segna tutte come lette
        Notifica.objects.filter(legacy_user_id=legacy_user.id, letta=False).update(letta=True)
    return render(request, "core/pages/notifiche.html", {
        "page_title": "Notifiche",
        "notifiche_list": lista,
    })


@login_required
@require_POST
def stop_impersonation(request):
    state = get_impersonation_state(request)
    if not state or not getattr(request, "impersonation_active", False):
        messages.info(request, "Nessuna impersonazione attiva.")
        return redirect("dashboard_home")

    admin_display = display_name_for_user(
        django_user=getattr(request, "impersonator_user", None),
        legacy_user=getattr(request, "impersonator_legacy_user", None),
    )
    target_display = display_name_for_user(
        django_user=getattr(request, "impersonated_user", None) or getattr(request, "user", None),
        legacy_user=getattr(request, "impersonated_legacy_user", None) or getattr(request, "legacy_user", None),
    )
    next_url = (request.POST.get("next") or "").strip() or "dashboard_home"
    if is_impersonation_stop_path(next_url):
        next_url = "dashboard_home"

    log_action(
        request,
        "impersonation_stop",
        "core",
        {
            "target_legacy_user_id": getattr(getattr(request, "impersonated_legacy_user", None), "id", None),
            "target_display": target_display,
        },
    )
    clear_impersonation_state(request)
    messages.success(request, f"Impersonazione terminata. Sei tornato a {admin_display or 'amministratore'}.")
    return redirect(next_url)


@login_required
@require_POST
def api_notifica_leggi(request, notifica_id: int):
    from core.models import Notifica
    legacy_user = get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False, "error": "Utente non trovato"}, status=403)
    updated = Notifica.objects.filter(id=notifica_id, legacy_user_id=legacy_user.id).update(letta=True)
    return JsonResponse({"ok": bool(updated)})


@login_required
@require_POST
def api_notifiche_popup_ack(request):
    """Marca come popup_shown=True le notifiche indicate mostrate nella UI globale."""
    from core.models import Notifica
    legacy_user = get_legacy_user(request.user)
    if not legacy_user:
        return JsonResponse({"ok": False}, status=403)
    try:
        data = json.loads(request.body)
        ids = [int(i) for i in (data.get("ids") or []) if str(i).lstrip("-").isdigit()]
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)
    if ids:
        Notifica.objects.filter(
            id__in=ids,
            legacy_user_id=legacy_user.id,
        ).update(popup_shown=True)
    return JsonResponse({"ok": True})


@login_required
def api_notifiche_panel(request):
    return render(request, "core/components/notification_center_panel.html", _notification_panel_context(request))


@login_required
def api_notifiche_live(request):
    """Endpoint leggero per badge e popup live delle notifiche in-app."""
    from core.models import Notifica

    legacy_user_id = _current_legacy_user_id(request)
    if not legacy_user_id:
        return JsonResponse({"ok": False, "error": "Utente non trovato"}, status=403)
    qs = Notifica.objects.filter(legacy_user_id=legacy_user_id)
    popup_notifications = list(
        qs.filter(letta=False, popup_shown=False).order_by("-created_at")[:5]
    )
    return JsonResponse({
        "ok": True,
        "unread_count": qs.filter(letta=False).count(),
        "popup_notifications": [
            _notification_payload(notifica)
            for notifica in popup_notifications
        ],
        "poll_after_ms": 15000,
    })


@login_required
@require_POST
def api_notifiche_mark_all_read(request):
    from core.models import Notifica

    legacy_user_id = _current_legacy_user_id(request)
    if not legacy_user_id:
        return JsonResponse({"ok": False, "error": "Utente non trovato"}, status=403)
    updated = Notifica.objects.filter(legacy_user_id=legacy_user_id, letta=False).update(letta=True)
    return JsonResponse({"ok": True, "updated": updated})


_VALID_NAV_MODES = {"top", "side"}
_VALID_THEME_MODES = {"light", "dark"}
_VALID_FONT_SCALES = {"small", "normal", "large", "xl"}


@login_required
def ui_prefs_page(request):
    if request.method == "POST":
        nav_mode = request.POST.get("nav_mode", "").strip()
        theme_mode = request.POST.get("theme_mode", "").strip()
        font_scale = request.POST.get("font_scale", "").strip()
        sidebar_collapsed_raw = request.POST.get("sidebar_collapsed", "0").strip()
        sidebar_footer_actions_raw = request.POST.get("sidebar_footer_actions") if "sidebar_footer_actions" in request.POST else None
        _prefs, _session_data = _save_user_ui_preferences(
            request,
            nav_mode=nav_mode,
            theme_mode=theme_mode,
            font_scale=font_scale,
            sidebar_collapsed_raw=sidebar_collapsed_raw,
            sidebar_footer_actions_raw=sidebar_footer_actions_raw,
        )
        return redirect(reverse("ui_prefs_page") + "?saved=1")

    current = _get_current_ui_prefs_for_user(request.user)
    sidebar_footer_catalog = get_sidebar_footer_catalog()
    return render(request, "core/pages/ui_prefs.html", {
        "page_title": "Preferenze interfaccia",
        "current": current,
        "saved": request.GET.get("saved") == "1",
        "sidebar_footer_catalog": sidebar_footer_catalog,
    })


@login_required
@require_POST
def api_ui_prefs_save(request):  # route: ui_prefs_api_save
    nav_mode = request.POST.get("nav_mode", "").strip()
    theme_mode = request.POST.get("theme_mode", "").strip()
    font_scale = request.POST.get("font_scale", "").strip()
    sidebar_collapsed_raw = request.POST.get("sidebar_collapsed", "").strip()
    sidebar_footer_actions_raw = request.POST.get("sidebar_footer_actions") if "sidebar_footer_actions" in request.POST else None

    _prefs, session_data = _save_user_ui_preferences(
        request,
        nav_mode=nav_mode,
        theme_mode=theme_mode,
        font_scale=font_scale,
        sidebar_collapsed_raw=sidebar_collapsed_raw,
        sidebar_footer_actions_raw=sidebar_footer_actions_raw,
    )

    return JsonResponse({"ok": True, "prefs": session_data})


@login_required
def api_table_prefs(request, table_id: str):
    """GET/POST/DELETE delle preferenze tabella per (utente, table_id).

    Vedi `docs/ai/TABELLE_PERSONALIZZABILI.md`. Lo stato è un blob JSON opaco
    salvato dal JS `fm-table-enhanced.js`. Il backend non interpreta il contenuto.

    - GET    → ritorna `{"ok": true, "state": {...}}` (vuoto se mai salvato).
    - POST   → body JSON `{"state": {...}}`; upsert sul record (utente, table_id).
    - DELETE → rimuove il record (reset preferenze al default).
    """
    from core.models import UserTablePreference

    table_id = (table_id or "").strip()
    if not table_id or len(table_id) > 100:
        return JsonResponse({"ok": False, "error": "table_id non valido"}, status=400)

    if request.method == "GET":
        try:
            pref = UserTablePreference.objects.get(user=request.user, table_id=table_id)
            return JsonResponse({"ok": True, "state": pref.state_json or {}})
        except UserTablePreference.DoesNotExist:
            return JsonResponse({"ok": True, "state": {}})

    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except (ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)
        state = data.get("state")
        if not isinstance(state, dict):
            return JsonResponse({"ok": False, "error": "campo 'state' deve essere un oggetto"}, status=400)
        # Cap dimensione blob (evita abuso): 10 KB ampiamente sufficiente.
        try:
            blob = json.dumps(state)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "state non serializzabile"}, status=400)
        if len(blob) > 10240:
            return JsonResponse({"ok": False, "error": "state troppo grande"}, status=400)
        UserTablePreference.objects.update_or_create(
            user=request.user, table_id=table_id,
            defaults={"state_json": state},
        )
        return JsonResponse({"ok": True})

    if request.method == "DELETE":
        UserTablePreference.objects.filter(user=request.user, table_id=table_id).delete()
        return JsonResponse({"ok": True})

    from django.http import HttpResponseNotAllowed
    return HttpResponseNotAllowed(["GET", "POST", "DELETE"])


def sidebar_toggle_save(request):
    """Endpoint dedicato e leggero per salvare solo sidebar_collapsed.

    Non usa @login_required (che farebbe redirect 302): restituisce JSON 401
    per utenti non autenticati, così il client AJAX non va in errore silenzioso.
    CSRF verificato automaticamente da CsrfViewMiddleware su ogni POST.
    """
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return JsonResponse({"ok": False, "reason": "unauthenticated"}, status=401)

    raw = request.POST.get("sidebar_collapsed", "").strip()
    if raw not in {"0", "1"}:
        return JsonResponse({"ok": False, "reason": "invalid_value"}, status=400)

    collapsed = raw == "1"

    # Crea il record solo se non esiste ancora; altrimenti aggiorna solo il campo.
    prefs, created = UserUiPreference.objects.get_or_create(
        user=request.user,
        defaults={
            "nav_mode": _UI_PREFS_DEFAULTS["nav_mode"],
            "theme_mode": "light",
            "font_scale": "normal",
            "sidebar_collapsed": collapsed,
            "sidebar_footer_actions": None,
        },
    )
    if not created:
        prefs.sidebar_collapsed = collapsed
        prefs.save(update_fields=["sidebar_collapsed"])

    # Aggiorna cache di sessione senza invalidarla completamente
    cached = request.session.get(_UI_PREFS_SESSION_KEY)
    if isinstance(cached, dict) and "nav_mode" in cached:
        cached["theme_mode"] = cached.get("theme_mode") or getattr(prefs, "theme_mode", "light")
        cached["sidebar_collapsed"] = collapsed
        cached["sidebar_footer_actions"] = normalize_sidebar_footer_actions(
            cached.get("sidebar_footer_actions"), fallback_to_default=True
        )
    else:
        cached = {
            "nav_mode": prefs.nav_mode,
            "theme_mode": getattr(prefs, "theme_mode", "light"),
            "font_scale": prefs.font_scale,
            "sidebar_collapsed": collapsed,
            "sidebar_footer_actions": normalize_sidebar_footer_actions(
                prefs.sidebar_footer_actions, fallback_to_default=True
            ),
        }
    try:
        request.session[_UI_PREFS_SESSION_KEY] = cached
    except Exception:
        pass

    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Onboarding wizard (primo accesso)
# ---------------------------------------------------------------------------

@login_required
def onboarding_wizard(request):
    """Wizard di primo accesso: raccoglie contatti, UI prefs e preferenze notifiche."""
    from core.models import UserOnboarding

    onboarding = UserOnboarding.get_or_create_for(request.user)

    # Se già completato/esentato, vai alla dashboard
    if onboarding.is_done():
        return redirect("dashboard_home")

    notification_options = _build_onboarding_notification_options(request, onboarding=onboarding)
    visible_notification_options = [option for option in notification_options if option["visible"]]

    if request.method == "POST":
        email_contatto = request.POST.get("email_contatto", "").strip()
        cellulare_contatto = request.POST.get("cellulare_contatto", "").strip()

        # Raccoglie tutti i toggle "notifiche_*" dal POST in modo dinamico —
        # aggiungere nuovi moduli al wizard non richiede modifiche qui.
        nav_mode = request.POST.get("nav_mode", "").strip()
        theme_mode = request.POST.get("theme_mode", "").strip()
        font_scale = request.POST.get("font_scale", "").strip()
        sidebar_collapsed_raw = request.POST.get("sidebar_collapsed", "0").strip()
        sidebar_footer_actions_raw = request.POST.getlist("sidebar_footer_actions")

        existing_config = onboarding.notifiche_config if isinstance(onboarding.notifiche_config, dict) else {}
        known_keys = {str(spec["key"]) for spec in _ONBOARDING_NOTIFICATION_SPECS}
        notifiche_config = {
            key: bool(value)
            for key, value in existing_config.items()
            if key not in known_keys
        }
        for option in notification_options:
            key = str(option["key"])
            if option["visible"]:
                notifiche_config[key] = request.POST.get(f"notifiche_{key}") == "1"
            else:
                notifiche_config[key] = False

        _prefs, _session_data = _save_user_ui_preferences(
            request,
            nav_mode=nav_mode,
            theme_mode=theme_mode,
            font_scale=font_scale,
            sidebar_collapsed_raw=sidebar_collapsed_raw,
            sidebar_footer_actions_raw=sidebar_footer_actions_raw,
        )

        onboarding.email_contatto = email_contatto
        onboarding.cellulare_contatto = cellulare_contatto
        onboarding.notifiche_config = notifiche_config
        onboarding.completed = True
        onboarding.completed_at = timezone.now()
        onboarding.save()

        try:
            log_action(
                request,
                "onboarding_completato",
                "core",
                {
                    "wizard": "primo_accesso",
                    "email_contatto": email_contatto,
                    "ui_nav_mode": nav_mode,
                    "ui_theme_mode": theme_mode,
                },
            )
        except Exception:
            pass

        messages.success(request, "Profilo configurato. Benvenuto nel portale!")
        return redirect("dashboard_home")

    # Prefill: usa email django user se disponibile, cellulare da UserExtraInfo se presente
    prefill_email = onboarding.email_contatto or request.user.email or ""
    prefill_cellulare = onboarding.cellulare_contatto
    if not prefill_cellulare:
        try:
            from core.legacy_utils import get_legacy_user as _glu
            lu = _glu(request.user)
            if lu:
                extra = UserExtraInfo.objects.filter(legacy_user_id=lu.id).first()
                if extra:
                    prefill_cellulare = extra.cellulare or ""
        except Exception:
            pass
    ui_prefs_current = _get_current_ui_prefs_for_user(request.user)

    return render(request, "core/pages/onboarding_wizard.html", {
        "page_title": "Benvenuto",
        "prefill_email": prefill_email,
        "prefill_cellulare": prefill_cellulare,
        "onboarding": onboarding,
        "notification_options": notification_options,
        "visible_notification_options": visible_notification_options,
        "sidebar_footer_catalog": get_sidebar_footer_catalog(),
        "ui_prefs_current": ui_prefs_current,
    })


@require_POST
@login_required
def api_onboarding_email_save(request):
    """Salva solo l'email di contatto dell'onboarding per l'utente corrente."""
    from core.models import UserOnboarding
    import re

    email = request.POST.get("email_contatto", "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return JsonResponse({"ok": False, "reason": "email_invalida"}, status=400)

    onboarding = UserOnboarding.get_or_create_for(request.user)
    onboarding.email_contatto = email
    onboarding.save(update_fields=["email_contatto"])
    return JsonResponse({"ok": True, "email_contatto": email})


@require_POST
@login_required
def api_onboarding_reset(request, user_id: int):
    """Resetta il wizard di onboarding per un utente specifico (solo admin)."""
    from core.models import UserOnboarding

    if not (request.user.is_superuser or is_legacy_admin(get_legacy_user(request.user))):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "reason": "user_not_found"}, status=404)

    onboarding, _ = UserOnboarding.objects.get_or_create(user=target_user)
    action = request.POST.get("action", "reset")

    if action == "skip":
        onboarding.skipped = True
        onboarding.completed = False
        onboarding.reset_at = timezone.now()
        onboarding.reset_by = request.user
        onboarding.save(update_fields=["skipped", "completed", "reset_at", "reset_by"])
        try:
            log_action(
                request,
                "onboarding_esentato",
                "core",
                {"target_username": target_user.username, "action": "skip"},
            )
        except Exception:
            pass
        return JsonResponse({"ok": True, "stato": "esentato"})
    else:
        # reset: rimanda il wizard
        onboarding.completed = False
        onboarding.skipped = False
        onboarding.completed_at = None
        onboarding.reset_at = timezone.now()
        onboarding.reset_by = request.user
        onboarding.save(update_fields=["completed", "skipped", "completed_at", "reset_at", "reset_by"])
        try:
            log_action(
                request,
                "onboarding_reset",
                "core",
                {"target_username": target_user.username, "action": "reset"},
            )
        except Exception:
            pass
        return JsonResponse({"ok": True, "stato": "reset"})


@login_required
def api_global_search(request):
    """
    GET /api/search/?q=<query>
    Ricerca globale su Dipendenti, Asset, Ticket, Kickoff/Task, Procedure.
    Restituisce risultati raggruppati per tipo, max 5 per gruppo.
    """
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": [], "query": q})

    results = []

    # ── Dipendenti ──────────────────────────────────────────────────────────
    try:
        dips = AnagraficaDipendente.objects.filter(
            Q(nome__icontains=q)
            | Q(cognome__icontains=q)
            | Q(aliasusername__icontains=q)
            | Q(email__icontains=q)
            | Q(mansione__icontains=q)
            | Q(reparto__icontains=q)
        ).order_by("cognome", "nome")[:5]
        for d in dips:
            try:
                url = reverse("anagrafica:dipendente_detail", args=[d.id])
            except Exception:
                url = "/anagrafica/dipendenti/"
            results.append({
                "tipo": "dipendente",
                "label": f"{d.cognome} {d.nome}".strip(),
                "sub": d.mansione or d.reparto or "",
                "url": url,
            })
    except Exception:
        pass

    # ── Asset ────────────────────────────────────────────────────────────────
    try:
        from assets.models import Asset as AssetModel
        assets_qs = AssetModel.objects.filter(
            Q(name__icontains=q)
            | Q(asset_tag__icontains=q)
            | Q(serial_number__icontains=q)
            | Q(manufacturer__icontains=q)
            | Q(model__icontains=q)
        ).order_by("name")[:5]
        for a in assets_qs:
            try:
                url = reverse("assets:asset_view", args=[a.id])
            except Exception:
                url = "/assets/lista/"
            results.append({
                "tipo": "asset",
                "label": a.name or a.asset_tag,
                "sub": f"{a.asset_tag} · {a.get_asset_type_display() if hasattr(a, 'get_asset_type_display') else ''}".strip(" ·"),
                "url": url,
            })
    except Exception:
        pass

    # ── Ticket ───────────────────────────────────────────────────────────────
    try:
        from tickets.models import Ticket
        tickets_qs = Ticket.objects.filter(
            Q(numero_ticket__icontains=q)
            | Q(titolo__icontains=q)
            | Q(descrizione__icontains=q)
            | Q(richiedente_nome__icontains=q)
        ).order_by("-data_apertura")[:5]
        for t in tickets_qs:
            try:
                url = reverse("tickets:detail", args=[t.pk])
            except Exception:
                url = "/tickets/"
            results.append({
                "tipo": "ticket",
                "label": t.titolo or t.numero_ticket,
                "sub": f"{t.numero_ticket} · {t.get_stato_display() if hasattr(t, 'get_stato_display') else t.stato}",
                "url": url,
            })
    except Exception:
        pass

    # ── Kickoff / Progetto ───────────────────────────────────────────────────
    try:
        from tasks.models import Project
        projects_qs = Project.objects.filter(
            Q(name__icontains=q)
            | Q(part_number__icontains=q)
            | Q(client_name__icontains=q)
            | Q(description__icontains=q)
            | Q(vrf_description__icontains=q)
        ).order_by("-id")[:5]
        for p in projects_qs:
            url = f"/tasks/projects/"
            results.append({
                "tipo": "kickoff",
                "label": p.name or f"KICK-OFF {p.kickoff_number}",
                "sub": " · ".join(filter(None, [p.part_number, p.client_name])),
                "url": url,
            })
    except Exception:
        pass

    # ── Task / Attività ──────────────────────────────────────────────────────
    try:
        from tasks.models import Task
        tasks_qs = Task.objects.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(tags__icontains=q)
        ).select_related("project").order_by("-id")[:5]
        for t in tasks_qs:
            try:
                url = reverse("tasks:detail", args=[t.pk])
            except Exception:
                url = "/tasks/"
            results.append({
                "tipo": "task",
                "label": t.title,
                "sub": t.project.name if t.project else "",
                "url": url,
            })
    except Exception:
        pass

    # ── Procedure / Documenti ────────────────────────────────────────────────
    try:
        from procedure_refresh.models import ProcedureDocument
        docs_qs = ProcedureDocument.objects.filter(
            Q(code__icontains=q)
            | Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(owner_department__icontains=q)
        ).filter(is_active=True).order_by("code")[:5]
        for d in docs_qs:
            try:
                url = reverse("procedure_refresh:document_edit", args=[d.pk])
            except Exception:
                url = "/procedure-refresh/admin/documenti/"
            results.append({
                "tipo": "procedura",
                "label": d.title,
                "sub": d.code or "",
                "url": url,
            })
    except Exception:
        pass

    # DPI / Richieste
    try:
        from dpi.models import RichiestaDPI
        dpi_qs = RichiestaDPI.objects.filter(
            Q(numero__icontains=q)
            | Q(richiedente_nome__icontains=q)
            | Q(richiedente_reparto__icontains=q)
            | Q(motivazione__icontains=q)
            | Q(categoria__nome__icontains=q)
        ).select_related("categoria").order_by("-created_at")[:5]
        for r in dpi_qs:
            try:
                url = reverse("dpi:gestione_detail", args=[r.pk])
            except Exception:
                url = "/dpi/gestione/"
            results.append({
                "tipo": "dpi",
                "label": r.numero or str(r),
                "sub": f"{r.richiedente_nome} - {r.label_stato}",
                "preview": " - ".join(filter(None, [
                    r.categoria.nome if r.categoria_id else "",
                    r.richiedente_reparto,
                    r.motivazione,
                ]))[:220],
                "url": url,
            })
    except Exception:
        pass

    module_labels = {
        "dipendente": "Anagrafica",
        "asset": "Asset",
        "ticket": "Ticket",
        "kickoff": "KICK-OFF",
        "task": "KICK-OFF",
        "procedura": "Procedure",
        "dpi": "DPI",
    }
    module_filter = (request.GET.get("module") or "").strip().lower()
    enriched = []
    for item in results:
        tipo = str(item.get("tipo") or "")
        module = module_labels.get(tipo, tipo.title())
        if module_filter and module_filter not in {tipo.lower(), module.lower()}:
            continue
        item.setdefault("module", module)
        item.setdefault("preview", item.get("sub") or "")
        enriched.append(item)

    return JsonResponse({"results": enriched, "query": q})
