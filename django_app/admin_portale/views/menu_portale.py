"""«Menu del portale»: la pagina pratica del Navigation Builder (28/10/2026).

Una pagina sola: a sinistra le voci del menu per area, a destra la voce scelta
con chi la vede, spiegato a parole. In alto «Guarda il menu come» un ruolo o
una persona. Niente codici, rotte o permessi: chi vede una voce lo decide la
pagina a cui porta (``core.navigation_registry._item_permission_info``) e si
cambia in «Ruoli e permessi». Snapshot, redirect, import e campi tecnici
restano nella vecchia pagina, ora «Strumenti avanzati»
(``navigazione.navigation_builder``).
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.icon_utils import render_semantic_icon
from core.templatetags.ui_icons import render_icon
from core.legacy_models import UtenteLegacy
from core.acl_v2 import normalize_permission_code
from core.models import AccessGroup, GroupPermissionGrant, ModuleCategory, NavigationItem, PermissionDefinition, RoutePermissionBinding
from core.module_registry import MODULE_DEFINITIONS, navigation_code_label_map
from core.navigation_registry import (
    PERMESSO_ASSENTE,
    PERMESSO_ESPLICITO_IGNORATO,
    bump_navigation_registry_version,
    describe_navigation_items_permission,
    is_external_navigation_item,
)

from ..decorators import legacy_admin_required
from . import _helpers

logger = logging.getLogger(__name__)

SEZIONI = ("topbar", "subnav")

# Icone proposte nella galleria della pagina (alias SVG di core.icon_utils).
ICONE_GALLERIA = (
    "home", "layout-dashboard", "calendar", "user", "users", "id-card", "clock", "briefcase",
    "ticket", "wrench", "tool", "settings", "shield", "shield-check", "siren", "triangle-alert",
    "package", "box", "layers", "clipboard-list", "list-todo", "check-circle", "file-text",
    "file-check", "book-open", "newspaper", "bell", "mail", "message-square", "map", "pin",
    "bar-chart", "pie-chart", "table", "folder", "database", "server", "cpu", "globe", "star",
    "flag", "workflow", "activity", "recycle", "archive", "key-round", "lock", "link",
)


def _sistema_attivo() -> bool:
    from core.permessi.motore import sistema_ruoli_attivo

    return sistema_ruoli_attivo()


def _nomi_da_branding() -> dict[str, str]:
    """Codice voce -> chiave del modulo, per le voci il cui nome lo decide il Branding."""
    brandizzati = navigation_code_label_map(surface="menu")
    result: dict[str, str] = {}
    for module_key, definition in MODULE_DEFINITIONS.items():
        for code in definition.navigation_codes:
            normalized = str(code or "").strip().lower()
            if normalized in brandizzati:
                result[normalized] = module_key
    return result


def _ruoli_portale() -> tuple[list[dict], int | None]:
    from core.permessi.motore import id_ruolo_base

    base_id = id_ruolo_base()
    try:
        gruppi = list(AccessGroup.objects.filter(is_active=True).order_by("-priority", "label"))
    except DatabaseError:
        return [], base_id
    ruoli = [
        {
            "id": int(g.id),
            "nome": g.label,
            "amministratore": bool(g.amministratore),
            "base": base_id is not None and int(g.id) == int(base_id),
            "priority": int(g.priority or 0),
        }
        for g in gruppi
    ]
    # Il ruolo base per primo: e' quello di tutti.
    ruoli.sort(key=lambda r: (not r["base"], r["amministratore"], -r["priority"], r["nome"].lower()))
    return ruoli, base_id


def _grant_per_ruolo(ruoli: list[dict]) -> dict[int, dict[str, tuple[int, bool]]]:
    ids = [r["id"] for r in ruoli]
    priorita = {r["id"]: r["priority"] for r in ruoli}
    mappa: dict[int, dict[str, tuple[int, bool]]] = {i: {} for i in ids}
    try:
        rows = GroupPermissionGrant.objects.filter(group_id__in=ids).values_list("group_id", "permission_id", "enabled")
        for group_id, code, enabled in rows:
            code = str(code or "").strip()
            if code:
                mappa[int(group_id)][code] = (priorita.get(int(group_id), 0), bool(enabled))
    except DatabaseError:
        logger.warning("menu_portale: grant dei ruoli non leggibili", exc_info=True)
    return mappa


def _ruolo_vede(ruolo: dict, codes: list[str], grants, base_id: int | None) -> bool:
    """Una persona con questo ruolo (e il ruolo base) vede la voce?

    Stessa regola di ``core.acl_resolver.group_grants_map``: vince la priorita'
    piu' alta, a parita' il diniego; nessuno si esprime = negato.
    """
    if ruolo["amministratore"]:
        return True
    if not codes:
        return False
    gruppi = [ruolo["id"]]
    if base_id is not None and int(base_id) != ruolo["id"]:
        gruppi.append(int(base_id))
    for code in codes:
        best: tuple[int, bool] | None = None
        for gid in gruppi:
            decisione = grants.get(gid, {}).get(code)
            if decisione is None:
                continue
            if best is None or decisione[0] > best[0] or (decisione[0] == best[0] and not decisione[1]):
                best = decisione
        if best is None or not best[1]:
            return False
    return True


def _permessi_sceglibili() -> list[dict]:
    """Permessi che si possono mettere su un link esterno: quelli che proteggono una pagina.

    Solo questi li concede la matrice di «Ruoli e permessi»: un codice che non
    protegge niente non lo avrebbe nessun ruolo e il link sparirebbe a tutti.
    """
    try:
        legati = {
            normalize_permission_code(str(c or ""))
            for c in RoutePermissionBinding.objects.filter(is_active=True).values_list("permission_id", flat=True)
        }
        definizioni = list(PermissionDefinition.objects.filter(is_active=True, code__in=legati).order_by("module", "label"))
    except DatabaseError:
        return []
    return [{"code": d.code, "nome": d.label or d.code, "modulo": d.module} for d in definizioni]


def _href(item: NavigationItem) -> str:
    if item.route_name:
        try:
            return reverse(item.route_name)
        except NoReverseMatch:
            return ""
    return str(item.url_path or "")


def _problema(stato: str, ruoli_che_vedono: list[dict], href: str) -> dict | None:
    if stato == PERMESSO_ESPLICITO_IGNORATO:
        return {
            "tipo": "vecchio",
            "titolo": "È rimasta legata al vecchio menu",
            "testo": "Chi può aprire la pagina potrebbe non trovare la voce. «Sistema da solo» la fa seguire la pagina.",
            "rimedio": "Sistema da solo",
        }
    if href.startswith(("http://", "https://")):
        return None
    if stato == PERMESSO_ASSENTE:
        return {
            "tipo": "senza_pagina",
            "titolo": "Non è legata a una pagina protetta",
            "testo": "Con «Ruoli e permessi» acceso la vedono solo gli amministratori.",
            "rimedio": "",
        }
    if not any(not r["amministratore"] for r in ruoli_che_vedono):
        return {
            "tipo": "nessuno",
            "titolo": "Nessun ruolo può aprire la pagina",
            "testo": "Oggi la vedono solo gli amministratori. Se serve ad altri, dagli l'accesso in «Ruoli e permessi».",
            "rimedio": "",
        }
    return None


def _app_di(item: NavigationItem, href: str) -> str:
    """App della pagina a cui porta la voce: e' la chiave delle sottovoci.

    La barra sotto la barra (sezione ``subnav``) compare nelle pagine dell'app
    ``parent_code`` (``core.context_processors._detect_subnav_parent_code``),
    non sotto un codice voce.
    """
    route = str(item.route_name or "").strip()
    if ":" in route:
        return route.split(":", 1)[0]
    if not href or href.startswith(("http://", "https://")):
        return ""
    try:
        return resolve(urlsplit(href).path).app_name or "dashboard"
    except Resolver404:
        return ""


def _sezioni_tendina(ids: list[int], voci: dict[int, dict]) -> list[dict]:
    """Sottogruppi della tendina come li disegna la barra (``_nav_sections``).

    Voci consecutive con lo stesso gruppo stanno insieme; con meno di due
    gruppi distinti la tendina non mostra intestazioni.
    """
    sezioni: list[dict] = []
    for vid in ids:
        nome = voci[vid]["gruppo"]
        if sezioni and sezioni[-1]["nome"] == nome:
            sezioni[-1]["voci"].append(vid)
        else:
            sezioni.append({"nome": nome, "voci": [vid]})
    if len({s["nome"] for s in sezioni if s["nome"]}) < 2:
        return [{"nome": "", "voci": list(ids)}]
    return sezioni


def dati_menu() -> dict:
    """Il menu com'e' nella barra in alto, con chi vede ogni voce e cosa non va.

    ``barra``: categorie (tendine) e voci da sole, nello stesso ordine della
    barra (``core.context_processors._group_nav_items``); ogni voce porta le sue
    sottovoci (la barra dentro le sue pagine).
    """
    items = list(
        NavigationItem.objects.filter(section__in=SEZIONI).select_related("category").order_by("order", "id")
    )
    info_map = describe_navigation_items_permission(items)
    nomi_menu = navigation_code_label_map(surface="menu")
    da_branding = _nomi_da_branding()
    ruoli, base_id = _ruoli_portale()
    grants = _grant_per_ruolo(ruoli)
    categorie = list(ModuleCategory.objects.all().order_by("order", "label"))

    voci: dict[int, dict] = {}
    for item in items:
        info = info_map.get(int(item.id)) or {}
        codes = list(info.get("codes") or [])
        if not codes and is_external_navigation_item(item):
            vedono = list(ruoli)  # link esterno: lo vedono tutti
        else:
            vedono = [r for r in ruoli if _ruolo_vede(r, codes, grants, base_id)]
        href = _href(item)
        code_norm = str(item.code or "").strip().lower()
        nome = nomi_menu.get(code_norm, item.label)
        voci[int(item.id)] = {
            "id": int(item.id),
            "code": item.code,
            "nome": nome,
            "nome_da_branding": code_norm in da_branding,
            "sezione": item.section,
            "categoria": int(item.category_id) if item.category_id else None,
            "gruppo": str(item.group or "").strip(),
            "padre": str(item.parent_code or "").strip(),
            "app": _app_di(item, href) if item.section == "topbar" else "",
            "ordine": int(item.order or 0),
            "icona": item.icon or "",
            "icona_html": str(render_icon(item.icon or "", nome)),
            "visibile": bool(item.is_visible and item.is_enabled),
            "href": href,
            "esterno": is_external_navigation_item(item),
            "nuova_scheda": bool(item.open_in_new_tab),
            # Indirizzo come lo scrive l'admin: percorso della pagina o https://…
            "indirizzo": href if item.route_name else str(item.url_path or ""),
            "permesso": str(info.get("explicit") or "") if is_external_navigation_item(item) else "",
            "ruoli": [r["id"] for r in vedono],
            "tutti": any(r["base"] for r in vedono),
            "problema": _problema(str(info.get("stato") or ""), vedono, href) if item.is_visible else None,
            "figli": [],
        }

    barra_voci = [v for v in voci.values() if v["sezione"] == "topbar"]

    # Sottovoci: sotto la voce della barra che porta alla stessa app. Se piu'
    # voci portano alla stessa app vince una nel menu, poi quella col codice
    # uguale, poi quella che porta piu' in alto nell'app (percorso piu' corto).
    voce_di_app: dict[str, dict] = {}
    for v in sorted(
        barra_voci,
        key=lambda v: (
            not v["visibile"],
            str(v["code"] or "").replace("-", "_").lower() != v["app"],
            len(urlsplit(v["href"]).path or "/"),
            v["ordine"],
        ),
    ):
        if v["app"]:
            voce_di_app.setdefault(v["app"], v)
    orfani: dict[str, list[int]] = {}
    for v in voci.values():
        if v["sezione"] != "subnav":
            continue
        padre = voce_di_app.get(v["padre"])
        if padre is not None:
            padre["figli"].append(v["id"])
            v["sotto"] = padre["id"]
        else:
            orfani.setdefault(v["padre"] or "?", []).append(v["id"])

    barra: list[dict] = []
    for cat in categorie:
        ids = [v["id"] for v in barra_voci if v["categoria"] == int(cat.id)]
        barra.append({
            "tipo": "categoria",
            "id": int(cat.id),
            "nome": cat.label,
            "icona": cat.icon or "",
            "icona_html": str(render_icon(cat.icon or "", cat.label)) if cat.icon else "",
            "ordine": int(cat.order or 0),
            "voci": ids,
            "sezioni": _sezioni_tendina(ids, voci),
            "gruppi": sorted({voci[i]["gruppo"] for i in ids if voci[i]["gruppo"]}),
        })
    for v in barra_voci:
        if v["categoria"] is None:
            barra.append({"tipo": "voce", "id": v["id"], "ordine": v["ordine"]})
    barra.sort(key=lambda n: n["ordine"])

    nomi_cat = {int(c.id): c.label for c in categorie}
    return {
        "barra": barra,
        "voci": {str(k): v for k, v in voci.items()},
        "orfani": [{"app": app, "voci": ids} for app, ids in sorted(orfani.items())],
        "ruoli": [r for r in ruoli if not r["amministratore"]],
        "categorie": [{"id": int(c.id), "nome": c.label} for c in categorie],
        "moduli": [
            {"app": app, "nome": v["nome"], "categoria": nomi_cat.get(v["categoria"], "")}
            for app, v in sorted(voce_di_app.items(), key=lambda kv: kv[1]["ordine"])
        ],
        "problemi": sum(1 for v in voci.values() if v["problema"]),
        "permessi": _permessi_sceglibili(),
    }


@legacy_admin_required
def menu_portale(request):
    dati = dati_menu()
    icone = [{"nome": nome, "svg": render_semantic_icon(nome)} for nome in ICONE_GALLERIA]
    return render(
        request,
        "admin_portale/pages/menu_portale.html",
        {
            "dati": dati,
            "icone": icone,
            "sistema_attivo": _sistema_attivo(),
            "n_problemi": dati["problemi"],
            "route_catalog": _helpers._route_catalog(),
        },
    )


@legacy_admin_required
@require_GET
def api_menu_vedi_persona(request):
    """Il menu come lo vede una persona: per voce si' / no e perche' (stesso risolutore delle pagine)."""
    from core.models import UserNavigationOverride

    from .navigazione import _nav_preview_rows

    user_id = _helpers._int_or_none(request.GET.get("user_id"))
    if not user_id:
        return _helpers._json_error("Persona mancante.")
    persona = UtenteLegacy.objects.filter(id=user_id).first()
    if persona is None:
        return _helpers._json_error("Persona non trovata.", status=404)
    items = list(NavigationItem.objects.filter(section__in=SEZIONI).order_by("order", "id"))
    nascoste = {
        int(ov.item_id): bool(ov.enabled)
        for ov in UserNavigationOverride.objects.filter(legacy_user_id=user_id)
    }
    righe = _nav_preview_rows(persona, items, nascoste, describe_navigation_items_permission(items))
    voci = {
        str(r["item_id"]): {
            "vede": bool(r["role_allowed"]) and r["state"] != "ov-hide",
            "nascosta_a_lui": r["state"] == "ov-hide",
            "perche": _perche_a_parole(r),
        }
        for r in righe
    }
    return JsonResponse({"ok": True, "voci": voci})


def _perche_a_parole(riga: dict) -> str:
    if riga["state"] == "ov-hide":
        return "L'hai nascosta tu a questa persona."
    reason = str(riga.get("reason") or "")
    if reason.startswith("Amministratore"):
        return "È un amministratore: vede tutto il menu."
    if riga["role_allowed"]:
        return "Può aprire la pagina, quindi la trova nel menu."
    if reason.startswith("Link esterno"):
        return "È un link a un sito esterno: lo vedono tutti."
    if "senza permesso" in reason.lower():
        return "La voce non è legata a una pagina protetta: la vedono solo gli amministratori."
    return "Non può aprire la pagina, quindi la voce non compare."


@legacy_admin_required
@csrf_protect
@require_POST
def api_menu_voce_salva(request):
    """Nome, categoria e sottogruppo (o voce madre), icona, «Nel menu», indirizzo,
    nuova scheda e, per i link esterni, il permesso che decide chi li vede.
    Il resto non si tocca."""
    from .navigazione import _normalize_nav_url_path

    payload = _helpers._post_or_json_payload(request)
    item = get_object_or_404(NavigationItem, id=_helpers._int_or_none(payload.get("id")) or 0)
    campi: list[str] = []
    if "route_name" in payload or "url_path" in payload:
        route_name = str(payload.get("route_name") or "").strip()
        url_path = "" if route_name else _normalize_nav_url_path(payload.get("url_path") or "")
        if route_name:
            try:
                reverse(route_name)
            except NoReverseMatch:
                return _helpers._json_error("Pagina del portale non trovata.")
        elif not url_path:
            return _helpers._json_error("Scrivi la pagina a cui porta la voce.")
        item.route_name = route_name[:120]
        item.url_path = url_path[:500]
        campi += ["route_name", "url_path"]
        if not is_external_navigation_item(item) and item.required_permission_code:
            # Torna una pagina del portale: chi la vede lo decide la pagina.
            item.required_permission_code = ""
            campi.append("required_permission_code")
    if "nuova_scheda" in payload:
        item.open_in_new_tab = _helpers._bool_from_any(payload.get("nuova_scheda"))
        campi.append("open_in_new_tab")
    if "permesso" in payload and is_external_navigation_item(item):
        code = normalize_permission_code(str(payload.get("permesso") or ""))
        if code and code not in {p["code"] for p in _permessi_sceglibili()}:
            return _helpers._json_error("Permesso non trovato fra quelli delle pagine del portale.")
        item.required_permission_code = code
        if "required_permission_code" not in campi:
            campi.append("required_permission_code")
    if "nome" in payload and str(item.code or "").strip().lower() not in _nomi_da_branding():
        nome = str(payload.get("nome") or "").strip()
        if not nome:
            return _helpers._json_error("Il nome non può essere vuoto.")
        item.label = nome[:120]
        campi.append("label")
    if "icona" in payload:
        item.icon = str(payload.get("icona") or "").strip()[:500]
        campi.append("icon")
    if "visibile" in payload:
        item.is_visible = _helpers._bool_from_any(payload.get("visibile"))
        campi.append("is_visible")
    if "categoria" in payload and item.section == "topbar":
        cat_id = _helpers._int_or_none(payload.get("categoria"))
        if cat_id and not ModuleCategory.objects.filter(id=cat_id).exists():
            return _helpers._json_error("Categoria non trovata.")
        item.category_id = cat_id
        campi.append("category")
    if "gruppo" in payload and item.section == "topbar":
        item.group = str(payload.get("gruppo") or "").strip()[:80]
        campi.append("group")
    if "padre" in payload and item.section == "subnav":
        padre = str(payload.get("padre") or "").strip()
        if padre not in {m["app"] for m in dati_menu()["moduli"]}:
            return _helpers._json_error("Voce del menu non trovata.")
        item.parent_code = padre
        campi.append("parent_code")
    if not campi:
        return JsonResponse({"ok": True, "salvati": []})
    item.updated_by = request.user
    campi += ["updated_by", "updated_at"]
    with transaction.atomic():
        item.save(update_fields=campi)
        transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True, "salvati": campi})


@legacy_admin_required
@csrf_protect
@require_POST
def api_menu_voce_sistema(request):
    """«Sistema da solo»: la voce smette di usare il permesso del vecchio menu e segue la pagina."""
    payload = _helpers._post_or_json_payload(request)
    item = get_object_or_404(NavigationItem, id=_helpers._int_or_none(payload.get("id")) or 0)
    info = describe_navigation_items_permission([item]).get(int(item.id)) or {}
    if info.get("stato") != PERMESSO_ESPLICITO_IGNORATO:
        return _helpers._json_error("Questa voce non ha niente da sistemare in automatico.")
    with transaction.atomic():
        NavigationItem.objects.filter(id=item.id).update(required_permission_code="")
        transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})



def _chiave_categoria(nome: str) -> str:
    base = (slugify(nome) or "categoria")[:34]
    chiave, n = base, 2
    while ModuleCategory.objects.filter(key=chiave).exists():
        chiave = f"{base}-{n}"
        n += 1
    return chiave


@legacy_admin_required
@csrf_protect
@require_POST
def api_menu_categoria_salva(request):
    """Crea o rinomina una categoria (tendina della barra) e ne cambia l'icona."""
    payload = _helpers._post_or_json_payload(request)
    nome = str(payload.get("nome") or "").strip()[:80]
    if not nome:
        return _helpers._json_error("Il nome della categoria non può essere vuoto.")
    cat_id = _helpers._int_or_none(payload.get("id"))
    with transaction.atomic():
        if cat_id:
            cat = get_object_or_404(ModuleCategory, id=cat_id)
            cat.label = nome
            campi = ["label"]
            if "icona" in payload:
                cat.icon = str(payload.get("icona") or "").strip()[:500]
                campi.append("icon")
            cat.save(update_fields=campi)
        else:
            # In fondo alla barra: dopo l'ultima categoria e l'ultima voce da sola.
            ultimo = max(
                [int(c.order or 0) for c in ModuleCategory.objects.all()]
                + [int(o or 0) for o in NavigationItem.objects.filter(section="topbar", category__isnull=True).values_list("order", flat=True)]
                + [0]
            )
            cat = ModuleCategory.objects.create(
                key=_chiave_categoria(nome),
                label=nome,
                icon=str(payload.get("icona") or "").strip()[:500],
                order=ultimo + 10,
            )
        transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True, "id": int(cat.id)})


@legacy_admin_required
@csrf_protect
@require_POST
def api_menu_categoria_elimina(request):
    """Elimina una categoria solo se non ha voci: niente sparisce dal menu per sbaglio."""
    payload = _helpers._post_or_json_payload(request)
    cat = get_object_or_404(ModuleCategory, id=_helpers._int_or_none(payload.get("id")) or 0)
    if NavigationItem.objects.filter(category=cat).exists():
        return _helpers._json_error("La categoria ha ancora delle voci: spostale prima in un'altra categoria.")
    with transaction.atomic():
        cat.delete()
        transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})


@legacy_admin_required
@csrf_protect
@require_POST
def api_menu_barra_riordina(request):
    """Ordine della barra in alto: categorie e voci da sole nella stessa sequenza.

    ``elementi``: lista di ``{"tipo": "categoria"|"voce", "id": int}``. La barra
    ordina categorie (``ModuleCategory.order``) e voci senza categoria
    (``NavigationItem.order``) sulla stessa scala, quindi si numerano insieme.
    """
    payload = _helpers._post_or_json_payload(request)
    elementi = payload.get("elementi")
    if not isinstance(elementi, list) or not elementi:
        return _helpers._json_error("Ordine mancante.")
    righe: list[tuple[str, int]] = []
    for el in elementi:
        tipo = str((el or {}).get("tipo") or "") if isinstance(el, dict) else ""
        el_id = _helpers._int_or_none((el or {}).get("id")) if isinstance(el, dict) else None
        if tipo not in {"categoria", "voce"} or not el_id:
            return _helpers._json_error("Ordine non valido.")
        righe.append((tipo, el_id))
    with transaction.atomic():
        for idx, (tipo, el_id) in enumerate(righe):
            ordine = (idx + 1) * 10
            if tipo == "categoria":
                ModuleCategory.objects.filter(id=el_id).update(order=ordine)
            else:
                NavigationItem.objects.filter(id=el_id, section="topbar", category__isnull=True).update(order=ordine)
        transaction.on_commit(bump_navigation_registry_version)
    return JsonResponse({"ok": True})
