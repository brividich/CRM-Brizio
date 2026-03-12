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
from core.impersonation import clear_impersonation_state, display_name_for_user, get_impersonation_state, is_impersonation_stop_path
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns
from core.models import OptioneConfig, UserExtraInfo


_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


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
        {"icon": "📅", "name": "Gestione Assenze", "sub": "Visualizza richieste", "url_name": "coming_assenze"},
        {"icon": "✏️", "name": "Richiedi Assenza", "sub": "Nuovo permesso/ferie", "url_name": "coming_assenze"},
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
    return _coming_soon(request, "Assenze")


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

    return render(request, "core/pages/profilo.html", {
        "page_title": "Profilo",
        "legacy_user": legacy_user,
        "profile": profile,
        "anagrafica_row": anagrafica_row,
        "extra_info": extra_info,
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
        lista = list(Notifica.objects.filter(legacy_user_id=legacy_user.id)[:50])
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
