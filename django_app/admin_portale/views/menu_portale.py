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

from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core.icon_utils import render_semantic_icon
from core.templatetags.ui_icons import render_icon
from core.legacy_models import UtenteLegacy
from core.models import AccessGroup, GroupPermissionGrant, ModuleCategory, NavigationItem
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
AREA_ALTRE = "__altre__"

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


def dati_menu() -> dict:
    """Albero del menu con, per ogni voce, chi la vede e cosa non va."""
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
        voci[int(item.id)] = {
            "id": int(item.id),
            "code": item.code,
            "nome": nomi_menu.get(code_norm, item.label),
            "nome_da_branding": code_norm in da_branding,
            "sezione": item.section,
            "categoria": int(item.category_id) if item.category_id else None,
            "padre": item.parent_code or "",
            "icona": item.icon or "",
            "icona_html": str(render_icon(item.icon or "", nomi_menu.get(code_norm, item.label))),
            "visibile": bool(item.is_visible and item.is_enabled),
            "href": href,
            "ruoli": [r["id"] for r in vedono],
            "tutti": any(r["base"] for r in vedono),
            "problema": _problema(str(info.get("stato") or ""), vedono, href) if item.is_visible else None,
        }

    # Aree = categorie della barra; le voci di secondo livello sotto il loro modulo.
    per_codice = {v["code"]: v for v in voci.values() if v["sezione"] == "topbar"}
    figli: dict[str, list[dict]] = {}
    orfani: list[dict] = []
    for v in voci.values():
        if v["sezione"] != "subnav":
            continue
        if v["padre"] in per_codice:
            figli.setdefault(v["padre"], []).append(v)
        else:
            orfani.append(v)

    aree: list[dict] = []
    for cat in categorie:
        moduli = [v for v in voci.values() if v["sezione"] == "topbar" and v["categoria"] == int(cat.id)]
        aree.append({"chiave": str(cat.id), "nome": cat.label, "voci": moduli})
    senza = [v for v in voci.values() if v["sezione"] == "topbar" and v["categoria"] is None]
    if senza:
        aree.append({"chiave": AREA_ALTRE, "nome": "Altre voci", "voci": senza})
    for area in aree:
        for modulo in area["voci"]:
            modulo["figli"] = figli.get(modulo["code"], [])
    if orfani:
        aree.append({"chiave": "__orfani__", "nome": "Sottovoci senza modulo", "voci": [dict(v, figli=[]) for v in orfani]})
    aree = [a for a in aree if a["voci"]]

    return {
        "aree": aree,
        "ruoli": [r for r in ruoli if not r["amministratore"]],
        "categorie": [{"id": int(c.id), "nome": c.label} for c in categorie],
        "moduli": [{"code": v["code"], "nome": v["nome"]} for v in per_codice.values()],
        "problemi": sum(1 for v in voci.values() if v["problema"]),
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
    """Nome, area (o modulo), icona e «Nel menu» di una voce. Il resto non si tocca."""
    payload = _helpers._post_or_json_payload(request)
    item = get_object_or_404(NavigationItem, id=_helpers._int_or_none(payload.get("id")) or 0)
    campi: list[str] = []
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
            return _helpers._json_error("Area non trovata.")
        item.category_id = cat_id
        campi.append("category")
    if "padre" in payload and item.section == "subnav":
        padre = str(payload.get("padre") or "").strip().lower()
        if padre and not NavigationItem.objects.filter(section="topbar", code=padre).exists():
            return _helpers._json_error("Modulo non trovato.")
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

