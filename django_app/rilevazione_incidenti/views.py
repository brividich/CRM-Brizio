from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from functools import wraps

import requests
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.graph_utils import acquire_graph_token
from core.legacy_utils import get_legacy_user, is_legacy_admin

from .models import RilevazioneIncidente, SicurezzaImpostazioni

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

TIPOLOGIE = [
    ("Unsafe Condition", "Unsafe Condition"),
    ("Unsafe Act", "Unsafe Act"),
    ("Near Miss", "Near Miss"),
    ("Accident", "Accident"),
]

REPARTI = [
    "AGGIUSTAGGIO",
    "TORNI / FRESE",
    "CNC",
    "CNC 5 ASSI",
    "CN5",
    "CQF",
    "LOGISTICA",
    "IMBALLAGGIO",
    "P.PRESSIONE / LAV.CONDOTTI",
    "UFFICI",
    "MANUTENZIONE",
    "ALTRO",
]

CAUSE_EVENTO = [
    "Comportamento non sicuro",
    "Condizione non sicura",
    "Mancanza di formazione",
    "Mancanza di DPI",
    "Guasto attrezzatura",
    "Procedure non rispettate",
    "Fattore ambientale",
    "Altro",
]

PERSONE_COINVOLTE_CHOICES = [
    "Dipendente",
    "Visitatore",
    "Appaltatore",
    "Fornitore",
]

APPROVAZIONE_RLS_CHOICES = [
    "Approvato",
    "Non approvato",
    "In attesa",
]

# ---------------------------------------------------------------------------
# Helpers interni
# ---------------------------------------------------------------------------


def _get_impostazioni() -> SicurezzaImpostazioni:
    obj, _ = SicurezzaImpostazioni.objects.get_or_create(pk=1)
    return obj


def _get_reparti() -> list[str]:
    cfg = _get_impostazioni()
    return list(cfg.reparti_custom) if cfg.reparti_custom else REPARTI


def _get_cause_evento() -> list[str]:
    cfg = _get_impostazioni()
    return list(cfg.cause_evento_custom) if cfg.cause_evento_custom else CAUSE_EVENTO


def _legacy_identity(request) -> tuple[str, str]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user:
        name = (legacy_user.nome or "").strip() or request.user.get_full_name() or request.user.get_username()
        email = (legacy_user.email or "").strip().lower() or (request.user.email or "").strip().lower()
        return name, email
    name = request.user.get_full_name() or request.user.get_username()
    email = (request.user.email or "").strip().lower()
    return name, email


def _can_create(request) -> bool:
    """Capireparto/preposti: acl_preposti whitelist. Vuota = accesso aperto."""
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    cfg = _get_impostazioni()
    acl = cfg.acl_preposti or []
    if not acl:
        return True
    username = request.user.get_username().lower()
    email = (request.user.email or "").lower()
    return any(v.lower() in (username, email) for v in acl)


def _can_manage_rspp(request) -> bool:
    """RSPP/ASPP: acl_rspp whitelist. Solo admin se vuota."""
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    cfg = _get_impostazioni()
    acl = cfg.acl_rspp or []
    if not acl:
        return False
    username = request.user.get_username().lower()
    email = (request.user.email or "").lower()
    return any(v.lower() in (username, email) for v in acl)


def _create_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _can_create(request):
            return render(request, "core/pages/forbidden.html", status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


# ---------------------------------------------------------------------------
# Graph API helpers
# ---------------------------------------------------------------------------


def _graph_headers() -> dict:
    from django.conf import settings
    tenant_id = getattr(settings, "GRAPH_TENANT_ID", "")
    client_id = getattr(settings, "GRAPH_CLIENT_ID", "")
    client_secret = getattr(settings, "GRAPH_CLIENT_SECRET", "")
    token = acquire_graph_token(tenant_id, client_id, client_secret)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _sp_base_url() -> str:
    cfg = _get_impostazioni()
    site_id = cfg.sharepoint_site_id.strip()
    list_id = cfg.sharepoint_list_id.strip()
    return f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}"


def _fetch_items() -> list[dict]:
    """Recupera tutti gli item dalla lista SharePoint."""
    url = (
        _sp_base_url()
        + "/items?$expand=fields"
        "&$top=999"
        "&$orderby=fields/Data_e_ora_rilevazione desc"
    )
    headers = _graph_headers()
    items = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return items


def _fetch_item(sp_id: str) -> dict:
    url = _sp_base_url() + f"/items/{sp_id}?$expand=fields"
    resp = requests.get(url, headers=_graph_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _create_item(fields: dict) -> dict:
    url = _sp_base_url() + "/items"
    payload = {"fields": fields}
    resp = requests.post(url, json=payload, headers=_graph_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _update_item(sp_id: str, fields: dict) -> None:
    url = _sp_base_url() + f"/items/{sp_id}/fields"
    resp = requests.patch(url, json=fields, headers=_graph_headers(), timeout=15)
    resp.raise_for_status()


def _delete_item(sp_id: str) -> None:
    url = _sp_base_url() + f"/items/{sp_id}"
    resp = requests.delete(url, headers=_graph_headers(), timeout=15)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Derivazione stato
# ---------------------------------------------------------------------------


def _deriva_stato(fields: dict) -> str:
    """Restituisce CHIUSO / APPROVATO / APERTO in base ai campi SharePoint."""
    if fields.get("Chiusura_RSPP"):
        return "CHIUSO"
    if fields.get("Approvazione_RLS"):
        return "APPROVATO"
    return "APERTO"


def _safe_year(date_str: str) -> bool:
    try:
        datetime.fromisoformat(date_str[:10])
        return True
    except Exception:
        return False


def _bool_field(fields: dict, key: str) -> bool:
    val = fields.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "si", "sì", "yes")
    return bool(val)


# ---------------------------------------------------------------------------
# Storage locale (fallback quando SharePoint non è configurato)
# ---------------------------------------------------------------------------

# Mapping nome-campo SP → campo modello RilevazioneIncidente
_SP_TO_MODEL: dict[str, str] = {
    "Nominativo": "nominativo",
    "Tipologia_scheda": "tipologia_scheda",
    "Reparto": "reparto",
    "Reparto_txt": "reparto",
    "Data_e_ora_rilevazione": "data_segnalazione",
    "Descrizione_x0020_attivit_x00e0__x0020_che_x0020_venivano_x0020_svolte_x0020_durante_x0020_l_x0027_accaduto": "descrizione_attivita",
    "Descrizione_x0020_avvenimento": "descrizione_avvenimento",
    "Descrizione_x0020_avvenimento_x0020__x0022_Quasi_x0020_incidente_x0022_": "descrizione_avvenimento",
    "Incidenti_causato_da_uso_macchina_x0020_": "usa_macchina",
    "Nome_x0020_macchina_x002F_attrezzatura_e_utilizzo": "nome_macchina",
    "Buono_x0020_stato_x0020_macchina_x002F_attrezzatura": "buono_stato_macchina",
    "Utilizzo_x0020_DPI_x0020_previsti": "utilizzo_dpi",
    "Prima_x0020_volta_x0020_quasi_x0020_incidente": "prima_volta",
    "Persone_x0020_coinvolte": "persone_coinvolte",
    "Causa_x0020_che_x0020_ha_x0020_determinato_x0020_l_x0027_evento": "causa_evento",
    "Altre_x0020_cause": "altre_cause",
    "Misure_x0020_tecniche_x002C__x0020_organizzative_x0020_o_x0020_procedurali_x0020_per_x0020_evitare_x0020_che_x0020_possa_x0020_riaccedere_x0020_questo_x0020_genere_x0020_di_x0020_evento": "misure_tecniche",
    "Quali_x0020_misure_x0020_adottare": "quali_misure",
    "Approvazione_RLS": "approvazione_rls",
    "Note_x0020_preposto": "note_preposto",
    "Note_RSPP_x0020__x002F__x0020_ASPP": "note_rspp",
    "Data_approvazione_RLS": "data_approvazione_rls",
    "Chiusura_RSPP": "chiusura_rspp",
    "Data_chiusura_RSPP": "data_chiusura_rspp",
    "x31__x0020_WHY": "why_1",
    "x32__x0020_WHY": "why_2",
    "x33__x0020_WHY": "why_3",
    "x34__x0020_WHY": "why_4",
    "x35__x0020_WHY": "why_5",
    "Partecipanti": "partecipanti",
}

_BOOL_MODEL_FIELDS = {
    "usa_macchina", "buono_stato_macchina", "utilizzo_dpi",
    "prima_volta", "misure_tecniche", "chiusura_rspp",
}
_DATE_MODEL_FIELDS = {"data_approvazione_rls", "data_chiusura_rspp"}
_DATETIME_MODEL_FIELDS = {"data_segnalazione"}


def _use_local(cfg: SicurezzaImpostazioni) -> bool:
    return not (cfg.sharepoint_site_id and cfg.sharepoint_list_id)


def _sp_fields_to_kwargs(sp_fields: dict) -> dict:
    """Converte un dict con nomi-campo SP in kwargs per il modello RilevazioneIncidente."""
    from datetime import date as date_type

    result: dict = {}
    seen: set[str] = set()  # evita doppio write su campi con più chiavi SP

    for sp_key, value in sp_fields.items():
        model_field = _SP_TO_MODEL.get(sp_key)
        if model_field is None or model_field in seen:
            continue
        seen.add(model_field)

        if model_field in _BOOL_MODEL_FIELDS:
            if isinstance(value, bool):
                result[model_field] = value
            else:
                result[model_field] = str(value).lower() in ("true", "1", "on", "si", "sì")
        elif model_field in _DATETIME_MODEL_FIELDS:
            if value:
                try:
                    from django.utils import timezone as tz
                    naive = datetime.fromisoformat(str(value))
                    result[model_field] = tz.make_aware(naive) if tz.is_naive(naive) else naive
                except (ValueError, TypeError):
                    result[model_field] = None
            else:
                result[model_field] = None
        elif model_field in _DATE_MODEL_FIELDS:
            if value:
                try:
                    result[model_field] = date_type.fromisoformat(str(value)[:10])
                except (ValueError, TypeError):
                    result[model_field] = None
            else:
                result[model_field] = None
        else:
            result[model_field] = value or ""

    return result


def _fetch_items_local() -> list[dict]:
    items = []
    for inst in RilevazioneIncidente.objects.all():
        items.append({"id": str(inst.pk), "fields": inst.as_sp_fields()})
    return items


def _fetch_item_local(pk: str) -> dict:
    inst = RilevazioneIncidente.objects.get(pk=int(pk))
    return {"id": str(inst.pk), "fields": inst.as_sp_fields()}


def _create_item_local(sp_fields: dict) -> dict:
    kwargs = _sp_fields_to_kwargs(sp_fields)
    inst = RilevazioneIncidente.objects.create(**kwargs)
    return {"id": str(inst.pk)}


def _update_item_local(pk: str, sp_fields: dict) -> None:
    inst = RilevazioneIncidente.objects.get(pk=int(pk))
    kwargs = _sp_fields_to_kwargs(sp_fields)
    for field, value in kwargs.items():
        setattr(inst, field, value)
    if kwargs:
        inst.save(update_fields=list(kwargs.keys()))


def _delete_item_local(pk: str) -> None:
    RilevazioneIncidente.objects.filter(pk=int(pk)).delete()


# ---------------------------------------------------------------------------
# View: lista
# ---------------------------------------------------------------------------


def lista(request):
    cfg = _get_impostazioni()
    items = []
    error = None

    if not _use_local(cfg):
        try:
            raw = _fetch_items()
            for item in raw:
                f = item.get("fields", {})
                f["sp_id"] = item["id"]
                f["stato"] = _deriva_stato(f)
                items.append(f)
        except Exception as exc:
            logger.warning("rilevazione_incidenti lista: errore Graph API: %s", exc)
            error = str(exc)
    else:
        try:
            raw = _fetch_items_local()
            for item in raw:
                f = item.get("fields", {})
                f["sp_id"] = item["id"]
                f["stato"] = _deriva_stato(f)
                items.append(f)
        except Exception as exc:
            logger.warning("rilevazione_incidenti lista: errore DB locale: %s", exc)
            error = str(exc)

    # Stats globali (prima dei filtri)
    _stati_cnt = Counter(f["stato"] for f in items)
    _tipi_cnt = Counter((f.get("Tipologia_scheda") or "").strip() for f in items)
    all_reparti = sorted({
        (f.get("Reparto") or f.get("Reparto_txt") or "").strip()
        for f in items
        if (f.get("Reparto") or f.get("Reparto_txt") or "").strip()
    })
    stats = {
        "totale": len(items),
        "aperti": _stati_cnt.get("APERTO", 0),
        "approvati": _stati_cnt.get("APPROVATO", 0),
        "chiusi": _stati_cnt.get("CHIUSO", 0),
        "unsafe_condition": _tipi_cnt.get("Unsafe Condition", 0),
        "unsafe_act": _tipi_cnt.get("Unsafe Act", 0),
        "near_miss": _tipi_cnt.get("Near Miss", 0),
        "accident": _tipi_cnt.get("Accident", 0),
    }

    # Filtri
    search = (request.GET.get("q") or "").strip()
    tipo_filter = (request.GET.get("tipo") or "").strip()
    stato_filter = (request.GET.get("stato") or "").strip()
    reparto_filter = (request.GET.get("reparto") or "").strip()

    if search:
        sl = search.lower()
        items = [
            f for f in items
            if sl in (f.get("Nominativo") or "").lower()
            or sl in (f.get("Reparto") or "").lower()
            or sl in (f.get("Reparto_txt") or "").lower()
            or sl in (f.get("Descrizione_x0020_avvenimento") or "").lower()
        ]
    if tipo_filter:
        items = [f for f in items if (f.get("Tipologia_scheda") or "") == tipo_filter]
    if stato_filter:
        items = [f for f in items if f["stato"] == stato_filter]
    if reparto_filter:
        items = [
            f for f in items
            if (f.get("Reparto") or f.get("Reparto_txt") or "") == reparto_filter
        ]

    can_create = _can_create(request)
    can_rspp = _can_manage_rspp(request)

    return render(request, "rilevazione_incidenti/pages/lista.html", {
        "items": items,
        "search": search,
        "tipo_filter": tipo_filter,
        "stato_filter": stato_filter,
        "reparto_filter": reparto_filter,
        "tipologie": [t[0] for t in TIPOLOGIE],
        "all_reparti": all_reparti,
        "can_create": can_create,
        "can_rspp": can_rspp,
        "error": error,
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# View: nuovo (selezione tipo + form)
# ---------------------------------------------------------------------------


@_create_required
def nuovo(request):
    tipo = (request.GET.get("tipo") or "").strip()
    valid_types = [t[0] for t in TIPOLOGIE]
    if tipo not in valid_types:
        tipo = ""

    error = None
    form_data = {}

    if request.method == "POST":
        tipo_post = (request.POST.get("Tipologia_scheda") or "").strip()
        if tipo_post not in valid_types:
            error = "Tipologia non valida."
            tipo = tipo_post
        else:
            name, email = _legacy_identity(request)
            fields = _build_fields_from_post(request.POST, request.user)
            cfg = _get_impostazioni()
            try:
                if _use_local(cfg):
                    created = _create_item_local(fields)
                else:
                    created = _create_item(fields)
                sp_id = created["id"]
                log_action(request, "crea", "rilevazione_incidenti", f"Nuova rilevazione {tipo_post} id={sp_id}")
                messages.success(request, "Rilevazione salvata correttamente.")
                return redirect("rilevazione_incidenti:dettaglio", sp_id=sp_id)
            except Exception as exc:
                logger.error("rilevazione_incidenti nuovo POST: %s", exc)
                error = f"Errore durante il salvataggio: {exc}"
                tipo = tipo_post
                form_data = dict(request.POST)

    name, _email = _legacy_identity(request)
    return render(request, "rilevazione_incidenti/pages/nuovo.html", {
        "tipo": tipo,
        "tipologie": TIPOLOGIE,
        "reparti": _get_reparti(),
        "cause_evento": _get_cause_evento(),
        "persone_coinvolte_choices": PERSONE_COINVOLTE_CHOICES,
        "error": error,
        "form_data": form_data,
        "nome_utente": name,
    })


def _build_fields_from_post(post, user) -> dict:
    def b(key) -> bool:
        return post.get(key, "0") in ("1", "true", "on", "si", "sì")

    fields = {
        "Tipologia_scheda": post.get("Tipologia_scheda", ""),
        "Nominativo": post.get("Nominativo", ""),
        "Data_e_ora_rilevazione": post.get("Data_e_ora_rilevazione", ""),
        "Reparto": post.get("Reparto", ""),
        "Reparto_txt": post.get("Reparto", ""),
        "RepScelto": post.get("Reparto", ""),
        "Incidenti_causato_da_uso_macchina_x0020_": b("usa_macchina"),
        "Nome_x0020_macchina_x002F_attrezzatura_e_utilizzo": post.get("nome_macchina", ""),
        "Buono_x0020_stato_x0020_macchina_x002F_attrezzatura": b("buono_stato_macchina"),
        "Utilizzo_x0020_DPI_x0020_previsti": b("utilizzo_dpi"),
        "Descrizione_x0020_attivit_x00e0__x0020_che_x0020_venivano_x0020_svolte_x0020_durante_x0020_l_x0027_accaduto": post.get("descrizione_attivita", ""),
        "Descrizione_x0020_avvenimento": post.get("descrizione_avvenimento", ""),
        "Descrizione_x0020_avvenimento_x0020__x0022_Quasi_x0020_incidente_x0022_": post.get("descrizione_quasi_incidente", ""),
        "Prima_x0020_volta_x0020_quasi_x0020_incidente": b("prima_volta_quasi_incidente"),
        "Causa_x0020_che_x0020_ha_x0020_determinato_x0020_l_x0027_evento": post.get("causa_evento", ""),
        "Altre_x0020_cause": post.get("altre_cause", ""),
        "Persone_x0020_coinvolte": post.get("persone_coinvolte", ""),
        "Misure_x0020_tecniche_x002C__x0020_organizzative_x0020_o_x0020_procedurali_x0020_per_x0020_evitare_x0020_che_x0020_possa_x0020_riaccedere_x0020_questo_x0020_genere_x0020_di_x0020_evento": b("misure_tecniche"),
        "Quali_x0020_misure_x0020_adottare": post.get("quali_misure", ""),
        # 5WHY
        "x31__x0020_WHY": post.get("why_1", ""),
        "x32__x0020_WHY": post.get("why_2", ""),
        "x33__x0020_WHY": post.get("why_3", ""),
        "x34__x0020_WHY": post.get("why_4", ""),
        "x35__x0020_WHY": post.get("why_5", ""),
        "Partecipanti": post.get("partecipanti", ""),
        "Note_x0020_preposto": post.get("note_preposto", ""),
    }
    # Rimuovi campi vuoti per non sovrascrivere valori SP con string vuote inutili
    return {k: v for k, v in fields.items() if v != ""}


# ---------------------------------------------------------------------------
# View: dettaglio
# ---------------------------------------------------------------------------


def dettaglio(request, sp_id):
    cfg = _get_impostazioni()
    item_fields = None
    error = None

    if not _use_local(cfg):
        try:
            item = _fetch_item(sp_id)
            item_fields = item.get("fields", {})
            item_fields["sp_id"] = sp_id
            item_fields["stato"] = _deriva_stato(item_fields)
        except Exception as exc:
            logger.warning("rilevazione_incidenti dettaglio %s: %s", sp_id, exc)
            error = str(exc)
    else:
        try:
            item = _fetch_item_local(sp_id)
            item_fields = item.get("fields", {})
            item_fields["sp_id"] = sp_id
            item_fields["stato"] = _deriva_stato(item_fields)
        except Exception as exc:
            logger.warning("rilevazione_incidenti dettaglio locale %s: %s", sp_id, exc)
            error = str(exc)

    can_edit_preposto = _can_create(request) and (
        item_fields is None or item_fields.get("stato") == "APERTO"
    )
    can_edit_rspp = _can_manage_rspp(request)

    return render(request, "rilevazione_incidenti/pages/dettaglio.html", {
        "f": item_fields,
        "sp_id": sp_id,
        "error": error,
        "can_edit_preposto": can_edit_preposto,
        "can_edit_rspp": can_edit_rspp,
        "b": _bool_field,
    })


# ---------------------------------------------------------------------------
# View: modifica
# ---------------------------------------------------------------------------


def modifica(request, sp_id):
    cfg = _get_impostazioni()
    use_local = _use_local(cfg)

    can_preposto = _can_create(request)
    can_rspp = _can_manage_rspp(request)

    if not can_preposto and not can_rspp:
        return render(request, "core/pages/forbidden.html", status=403)

    item_fields = {}
    error = None
    try:
        if use_local:
            item = _fetch_item_local(sp_id)
        else:
            item = _fetch_item(sp_id)
        item_fields = item.get("fields", {})
        item_fields["stato"] = _deriva_stato(item_fields)
    except Exception as exc:
        logger.error("rilevazione_incidenti modifica GET %s: %s", sp_id, exc)
        error = str(exc)

    # Verifica che preposto possa ancora modificare
    if can_preposto and not can_rspp and item_fields.get("stato") != "APERTO":
        messages.warning(request, "La scheda è già approvata o chiusa: non modificabile.")
        return redirect("rilevazione_incidenti:dettaglio", sp_id=sp_id)

    if request.method == "POST":
        fields_to_update = {}
        if can_preposto and item_fields.get("stato") == "APERTO":
            fields_to_update.update(_build_fields_from_post(request.POST, request.user))
        if can_rspp:
            def b(key): return request.POST.get(key, "0") in ("1", "true", "on", "si", "sì")
            approvazione = request.POST.get("Approvazione_RLS", "")
            if approvazione:
                fields_to_update["Approvazione_RLS"] = approvazione
            data_approv = request.POST.get("Data_approvazione_RLS", "")
            if data_approv:
                fields_to_update["Data_approvazione_RLS"] = data_approv
            note_rspp = request.POST.get("note_rspp_aspp", "")
            if note_rspp:
                fields_to_update["Note_RSPP_x0020__x002F__x0020_ASPP"] = note_rspp
            chiusura = b("chiusura_rspp")
            fields_to_update["Chiusura_RSPP"] = chiusura
            if chiusura:
                data_chiusura = request.POST.get("data_chiusura_rspp", "")
                if data_chiusura:
                    fields_to_update["Data_chiusura_RSPP"] = data_chiusura

        if fields_to_update:
            try:
                if use_local:
                    _update_item_local(sp_id, fields_to_update)
                else:
                    _update_item(sp_id, fields_to_update)
                log_action(request, "modifica", "rilevazione_incidenti", f"Modifica rilevazione id={sp_id}")
                messages.success(request, "Modifiche salvate.")
                return redirect("rilevazione_incidenti:dettaglio", sp_id=sp_id)
            except Exception as exc:
                logger.error("rilevazione_incidenti modifica POST %s: %s", sp_id, exc)
                error = f"Errore: {exc}"
        else:
            messages.info(request, "Nessuna modifica da salvare.")
            return redirect("rilevazione_incidenti:dettaglio", sp_id=sp_id)

    return render(request, "rilevazione_incidenti/pages/modifica.html", {
        "f": item_fields,
        "sp_id": sp_id,
        "error": error,
        "can_preposto": can_preposto,
        "can_rspp": can_rspp,
        "tipologie": TIPOLOGIE,
        "reparti": _get_reparti(),
        "cause_evento": _get_cause_evento(),
        "persone_coinvolte_choices": PERSONE_COINVOLTE_CHOICES,
        "approvazione_rls_choices": APPROVAZIONE_RLS_CHOICES,
    })


# ---------------------------------------------------------------------------
# View: elimina
# ---------------------------------------------------------------------------


@require_POST
def elimina(request, sp_id):
    if not _can_manage_rspp(request):
        return render(request, "core/pages/forbidden.html", status=403)
    cfg = _get_impostazioni()
    try:
        if _use_local(cfg):
            _delete_item_local(sp_id)
        else:
            _delete_item(sp_id)
        log_action(request, "elimina", "rilevazione_incidenti", f"Eliminata rilevazione id={sp_id}")
        messages.success(request, "Rilevazione eliminata.")
    except Exception as exc:
        logger.error("rilevazione_incidenti elimina %s: %s", sp_id, exc)
        messages.error(request, f"Errore: {exc}")
    return redirect("rilevazione_incidenti:lista")


# ---------------------------------------------------------------------------
# View: statistiche
# ---------------------------------------------------------------------------


def statistiche(request):
    cfg = _get_impostazioni()
    items = []
    error = None

    if not _use_local(cfg):
        try:
            raw = _fetch_items()
            for item in raw:
                f = item.get("fields", {})
                f["stato"] = _deriva_stato(f)
                items.append(f)
        except Exception as exc:
            logger.warning("rilevazione_incidenti statistiche: %s", exc)
            error = str(exc)
    else:
        try:
            raw = _fetch_items_local()
            for item in raw:
                f = item.get("fields", {})
                f["stato"] = _deriva_stato(f)
                items.append(f)
        except Exception as exc:
            logger.warning("rilevazione_incidenti statistiche locale: %s", exc)
            error = str(exc)

    # Aggregazioni
    totale = len(items)
    per_tipologia = Counter(f.get("Tipologia_scheda", "N/D") for f in items)
    per_reparto = Counter(f.get("Reparto", f.get("Reparto_txt", "N/D")) or "N/D" for f in items)
    per_stato = Counter(f["stato"] for f in items)

    # Trend mensile ultimi 12 mesi
    mesi_labels = []
    mesi_values = []
    mesi_counter: dict[str, int] = defaultdict(int)
    for f in items:
        raw_date = f.get("Data_e_ora_rilevazione") or f.get("Created", "")
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date[:10])
                key = dt.strftime("%Y-%m")
                mesi_counter[key] += 1
            except Exception:
                pass

    if mesi_counter:
        sorted_keys = sorted(mesi_counter.keys())[-12:]
        for k in sorted_keys:
            y, m = k.split("-")
            mesi_labels.append(f"{int(m):02d}/{y[2:]}")
            mesi_values.append(mesi_counter[k])

    max_val = max(mesi_values) if mesi_values else 1
    trend_pairs = [
        (mesi_labels[i], mesi_values[i], max(4, int(mesi_values[i] / max_val * 100)))
        for i in range(len(mesi_labels))
    ]

    # Valutazione media
    voti = [f.get("Valutazione_x0020__x00280_2D5_x0029_") or f.get("OData__x0052_ating") for f in items]
    voti_num = [float(v) for v in voti if v is not None]
    valutazione_media = round(sum(voti_num) / len(voti_num), 1) if voti_num else None

    reparto_top = sorted(per_reparto.items(), key=lambda x: x[1], reverse=True)[:10]

    # Distribuzione cause evento
    per_causa = Counter(
        (f.get("Causa_x0020_che_x0020_ha_x0020_determinato_x0020_l_x0027_evento") or "Non specificata").strip()
        for f in items
    )
    cause_top = sorted(per_causa.items(), key=lambda x: x[1], reverse=True)[:8]

    # Anni attivi
    anni = sorted({
        datetime.fromisoformat(f.get("Data_e_ora_rilevazione", "")[:10]).year
        for f in items
        if f.get("Data_e_ora_rilevazione")
        and len(f.get("Data_e_ora_rilevazione", "")) >= 10
        and _safe_year(f.get("Data_e_ora_rilevazione", ""))
    })

    # Dati JSON per Chart.js
    n_uc = per_tipologia.get("Unsafe Condition", 0)
    n_ua = per_tipologia.get("Unsafe Act", 0)
    n_nm = per_tipologia.get("Near Miss", 0)
    n_ac = per_tipologia.get("Accident", 0)
    n_ap = per_stato.get("APERTO", 0)
    n_appr = per_stato.get("APPROVATO", 0)
    n_ch = per_stato.get("CHIUSO", 0)

    chart_tipologie = json.dumps({
        "labels": ["Unsafe Condition", "Unsafe Act", "Near Miss", "Accident"],
        "data": [n_uc, n_ua, n_nm, n_ac],
        "colors": ["#16a34a", "#0369a1", "#ea580c", "#dc2626"],
        "bg": ["#dcfce7", "#e0f2fe", "#fff7ed", "#fee2e2"],
    })
    chart_stati = json.dumps({
        "labels": ["Aperti", "Approvati", "Chiusi"],
        "data": [n_ap, n_appr, n_ch],
        "colors": ["#eab308", "#22c55e", "#15803d"],
    })
    chart_trend = json.dumps({
        "labels": mesi_labels,
        "data": mesi_values,
    })
    chart_reparti = json.dumps({
        "labels": [r[0] for r in reparto_top],
        "data": [r[1] for r in reparto_top],
    })
    chart_cause = json.dumps({
        "labels": [c[0] for c in cause_top],
        "data": [c[1] for c in cause_top],
    })

    return render(request, "rilevazione_incidenti/pages/statistiche.html", {
        "totale": totale,
        "n_unsafe_condition": n_uc,
        "n_unsafe_act": n_ua,
        "n_near_miss": n_nm,
        "n_accident": n_ac,
        "n_aperto": n_ap,
        "n_approvato": n_appr,
        "n_chiuso": n_ch,
        "reparto_top": reparto_top,
        "cause_top": cause_top,
        "trend_pairs": trend_pairs,
        "valutazione_media": valutazione_media,
        "anni_attivi": len(anni),
        "chart_tipologie": chart_tipologie,
        "chart_stati": chart_stati,
        "chart_trend": chart_trend,
        "chart_reparti": chart_reparti,
        "chart_cause": chart_cause,
        "error": error,
    })


# ---------------------------------------------------------------------------
# View: impostazioni
# ---------------------------------------------------------------------------


def impostazioni(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not (request.user.is_superuser or (legacy_user and is_legacy_admin(legacy_user))):
        return render(request, "core/pages/forbidden.html", status=403)

    cfg = _get_impostazioni()
    error = None

    if request.method == "POST":
        tab = request.POST.get("_tab", "sharepoint")
        if tab == "sharepoint":
            cfg.sharepoint_site_id = request.POST.get("sharepoint_site_id", "").strip()
            cfg.sharepoint_list_id = request.POST.get("sharepoint_list_id", "").strip()
        elif tab == "permessi":
            raw_preposti = request.POST.get("acl_preposti", "").strip()
            raw_rspp = request.POST.get("acl_rspp", "").strip()
            cfg.acl_preposti = [v.strip() for v in raw_preposti.splitlines() if v.strip()]
            cfg.acl_rspp = [v.strip() for v in raw_rspp.splitlines() if v.strip()]
        elif tab == "liste":
            raw_reparti = request.POST.get("reparti_custom", "").strip()
            raw_cause = request.POST.get("cause_evento_custom", "").strip()
            cfg.reparti_custom = [v.strip() for v in raw_reparti.splitlines() if v.strip()]
            cfg.cause_evento_custom = [v.strip() for v in raw_cause.splitlines() if v.strip()]
        try:
            cfg.save()
            messages.success(request, "Impostazioni salvate.")
            return redirect(f"{request.path}?tab={tab}")
        except Exception as exc:
            error = str(exc)

    active_tab = request.GET.get("tab", "sharepoint")
    n_record_db = RilevazioneIncidente.objects.count()
    storage_mode = "locale" if _use_local(cfg) else "sharepoint"

    return render(request, "rilevazione_incidenti/pages/impostazioni.html", {
        "cfg": cfg,
        "error": error,
        "active_tab": active_tab,
        "acl_preposti_text": "\n".join(cfg.acl_preposti or []),
        "acl_rspp_text": "\n".join(cfg.acl_rspp or []),
        "reparti_custom_text": "\n".join(cfg.reparti_custom or []),
        "cause_evento_custom_text": "\n".join(cfg.cause_evento_custom or []),
        "reparti_default": REPARTI,
        "cause_evento_default": CAUSE_EVENTO,
        "n_record_db": n_record_db,
        "storage_mode": storage_mode,
    })


# ---------------------------------------------------------------------------
# View: export CSV
# ---------------------------------------------------------------------------


def export_csv(request):
    import csv as csv_module
    from django.http import HttpResponse

    if not _can_manage_rspp(request):
        return render(request, "core/pages/forbidden.html", status=403)

    cfg = _get_impostazioni()
    items = []
    try:
        if _use_local(cfg):
            raw = _fetch_items_local()
        else:
            raw = _fetch_items()
        for item in raw:
            f = item.get("fields", {})
            f["sp_id"] = item["id"]
            f["stato"] = _deriva_stato(f)
            items.append(f)
    except Exception as exc:
        messages.error(request, f"Errore durante l'export: {exc}")
        return redirect("rilevazione_incidenti:lista")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="rilevazioni_sicurezza.csv"'
    response.write("\ufeff")  # BOM per Excel

    writer = csv_module.writer(response)
    writer.writerow([
        "ID", "Stato", "Tipologia", "Nominativo", "Reparto", "Data segnalazione",
        "Causa evento", "Persone coinvolte", "Utilizzo DPI", "Usa macchina",
        "Nome macchina", "Approvazione RLS", "Data approvazione", "Chiusura RSPP",
        "Data chiusura", "Note preposto", "Note RSPP/ASPP",
        "1 WHY", "2 WHY", "3 WHY", "4 WHY", "5 WHY",
    ])
    for f in items:
        writer.writerow([
            f.get("sp_id", ""),
            f.get("stato", ""),
            f.get("Tipologia_scheda", ""),
            f.get("Nominativo", ""),
            f.get("Reparto") or f.get("Reparto_txt", ""),
            (f.get("Data_e_ora_rilevazione") or "")[:16],
            f.get("Causa_x0020_che_x0020_ha_x0020_determinato_x0020_l_x0027_evento", ""),
            f.get("Persone_x0020_coinvolte", ""),
            "Sì" if f.get("Utilizzo_x0020_DPI_x0020_previsti") else "No",
            "Sì" if f.get("Incidenti_causato_da_uso_macchina_x0020_") else "No",
            f.get("Nome_x0020_macchina_x002F_attrezzatura_e_utilizzo", ""),
            f.get("Approvazione_RLS", ""),
            (f.get("Data_approvazione_RLS") or "")[:10],
            "Sì" if f.get("Chiusura_RSPP") else "No",
            (f.get("Data_chiusura_RSPP") or "")[:10],
            f.get("Note_x0020_preposto", ""),
            f.get("Note_RSPP_x0020__x002F__x0020_ASPP", ""),
            f.get("x31__x0020_WHY", ""),
            f.get("x32__x0020_WHY", ""),
            f.get("x33__x0020_WHY", ""),
            f.get("x34__x0020_WHY", ""),
            f.get("x35__x0020_WHY", ""),
        ])

    log_action(request, "export", "rilevazione_incidenti", f"Export CSV {len(items)} rilevazioni")
    return response
