"""
Rentri — Registro Rifiuti RENTRI
Gestione locale + sincronizzazione con SharePoint tramite Microsoft Graph API.
"""
from __future__ import annotations

import configparser
import json
import os
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

import requests
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import RegistroRifiuti

# ── Helpers Graph / SharePoint ────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(_repo_root() / "config.ini", encoding="utf-8")
    return parser


_INI = _load_ini()


def _env_or_ini(section: str, option: str, *env_keys: str) -> str:
    for key in env_keys:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    if _INI.has_section(section):
        return str(_INI.get(section, option, fallback="") or "").strip()
    return ""


def _is_placeholder(value: str) -> bool:
    return not value or value.startswith("<") and value.endswith(">")


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id": _env_or_ini("AZIENDA", "tenant_id", "GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": _env_or_ini("AZIENDA", "client_id", "GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": _env_or_ini("AZIENDA", "client_secret", "GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "site_id": _env_or_ini("AZIENDA", "site_id", "GRAPH_SITE_ID"),
        "list_id_rentri": _env_or_ini("AZIENDA", "list_id_rentri", "GRAPH_LIST_ID_RENTRI"),
    }


def _graph_configured() -> bool:
    gs = _graph_settings()
    required = ("tenant_id", "client_id", "client_secret", "site_id", "list_id_rentri")
    return all(not _is_placeholder(gs.get(k, "")) for k in required)


def _graph_base_url() -> str:
    gs = _graph_settings()
    return (
        f"https://graph.microsoft.com/v1.0/sites/{gs['site_id']}"
        f"/lists/{gs['list_id_rentri']}/items"
    )


def _acquire_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _graph_token() -> str:
    if not _graph_configured():
        raise RuntimeError("Configurazione Graph incompleta per RENTRI")
    gs = _graph_settings()
    return _acquire_graph_token(gs["tenant_id"], gs["client_id"], gs["client_secret"])


def _graph_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"}


def _graph_get_all() -> list[dict]:
    url = f"{_graph_base_url()}?expand=fields&$top=500"
    rows: list[dict] = []
    while url:
        r = requests.get(url, headers=_graph_headers(), timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"Graph GET {r.status_code}: {r.text[:300]}")
        payload = r.json()
        rows.extend(payload.get("value", []) or [])
        url = payload.get("@odata.nextLink")
    return rows


def _graph_create(fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.post(
        _graph_base_url(),
        headers=_graph_headers(),
        json={"fields": fields_payload},
        timeout=20,
    )
    if r.status_code in (200, 201):
        return True, r.json()
    return False, r.text


def _graph_update(item_id: str, fields_payload: dict) -> tuple[bool, dict | str]:
    r = requests.patch(
        f"{_graph_base_url()}/{item_id}/fields",
        headers=_graph_headers(),
        json=fields_payload,
        timeout=20,
    )
    if r.status_code in (200, 204):
        if not r.text:
            return True, {}
        try:
            return True, r.json()
        except Exception:
            return True, {}
    return False, r.text


def _graph_delete(item_id: str) -> tuple[bool, str]:
    r = requests.delete(f"{_graph_base_url()}/{item_id}", headers=_graph_headers(), timeout=20)
    if r.status_code in (200, 202, 204):
        return True, ""
    if r.status_code == 404:
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        error_code = str((payload.get("error") or {}).get("code") or "").strip()
        if error_code == "itemNotFound":
            return True, ""
    return False, r.text


# ── Field mapping helpers ─────────────────────────────────────────────────────


def _to_sp_fields(registro: RegistroRifiuti) -> dict:
    """Convert a RegistroRifiuti instance to SharePoint field dict."""
    def _dec(v):
        return float(v) if v is not None else None

    fields: dict = {
        "Data": registro.data.isoformat() if registro.data else None,
        "IDRegistrazione": registro.id_registrazione or "",
        "Rif_x002e_Op": registro.rif_op or "",
        "Codice": registro.codice or "",
        "Quantit_x00e0_": _dec(registro.quantita),
        "Carico_x002f_Scarico": registro.carico_scarico or "",
        "RentriSI_x002f_NO": registro.rentri_si_no,
        "Salva": registro.salva,
        "NOTERENTRI": registro.note_rentri or "",
        "Pericolosit_x00e0_": registro.pericolosita or "",
        "RettificaScarico": _dec(registro.rettifica_scarico),
        "ARRIVOFIR": registro.arrivo_fir or "",
    }
    if registro.aggiornato:
        aggiornato_dt = registro.aggiornato
        if timezone.is_naive(aggiornato_dt):
            aggiornato_dt = timezone.make_aware(aggiornato_dt, timezone.get_current_timezone())
        aggiornato_dt = aggiornato_dt.astimezone(dt_timezone.utc)
        fields["Aggiornato"] = aggiornato_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Remove None values to avoid SP errors on non-nullable fields
    return {k: v for k, v in fields.items() if v is not None}


def _from_sp_item(item: dict) -> dict:
    """Map a SharePoint item to RegistroRifiuti field values."""
    fields = item.get("fields") or {}

    def _as_bool(v) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        try:
            return bool(int(v))
        except Exception:
            return str(v).strip().lower() in {"1", "true", "yes", "on", "si"}

    def _as_decimal(v):
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _parse_date(v):
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v)[:10]).date()
        except Exception:
            return None

    def _parse_dt(v):
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, dt_timezone.utc)
            return timezone.localtime(dt, timezone.get_current_timezone()).replace(tzinfo=None)
        except Exception:
            return None

    return {
        "sharepoint_item_id": str(item.get("id") or ""),
        "data": _parse_date(fields.get("Data")),
        "id_registrazione": str(fields.get("IDRegistrazione") or "").strip(),
        "rif_op": str(fields.get("Rif_x002e_Op") or "").strip(),
        "codice": str(fields.get("Codice") or "").strip(),
        "quantita": _as_decimal(fields.get("Quantit_x00e0_")),
        "carico_scarico": str(fields.get("Carico_x002f_Scarico") or "").strip(),
        "rentri_si_no": _as_bool(fields.get("RentriSI_x002f_NO")),
        "salva": _as_bool(fields.get("Salva")),
        "note_rentri": str(fields.get("NOTERENTRI") or "").strip(),
        "pericolosita": str(fields.get("Pericolosit_x00e0_") or "").strip(),
        "rettifica_scarico": _as_decimal(fields.get("RettificaScarico")),
        "arrivo_fir": str(fields.get("ARRIVOFIR") or "").strip(),
        "aggiornato": _parse_dt(fields.get("Aggiornato")),
    }


# ── Request parsing helpers ───────────────────────────────────────────────────


def _parse_json_body(request) -> dict:
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _get_username(request) -> str:
    if request.user and request.user.is_authenticated:
        return request.user.get_full_name() or request.user.username
    return ""


def _populate_registro(registro: RegistroRifiuti, data: dict, tipo: str) -> list[str]:
    """Populate registro fields from POST data dict; return list of error strings."""
    errors = []

    # data (date)
    data_val = str(data.get("data") or "").strip()
    if not data_val:
        errors.append("Il campo Data è obbligatorio.")
    else:
        try:
            registro.data = datetime.fromisoformat(data_val).date()
        except ValueError:
            errors.append("Formato data non valido.")

    registro.tipo = tipo
    registro.rif_op = str(data.get("rif_op") or "").strip()
    registro.codice = str(data.get("codice") or "").strip()

    quantita_raw = str(data.get("quantita") or "").strip()
    if quantita_raw:
        try:
            registro.quantita = float(quantita_raw)
        except ValueError:
            errors.append("Quantità non valida.")
    else:
        registro.quantita = None

    registro.carico_scarico = str(data.get("carico_scarico") or "").strip()
    registro.rentri_si_no = bool(data.get("rentri_si_no"))
    registro.salva = bool(data.get("salva"))
    registro.note_rentri = str(data.get("note_rentri") or "").strip()
    registro.pericolosita = str(data.get("pericolosita") or "").strip()

    rett_raw = str(data.get("rettifica_scarico") or "").strip()
    if rett_raw:
        try:
            registro.rettifica_scarico = float(rett_raw)
        except ValueError:
            errors.append("Rettifica scarico non valida.")
    else:
        registro.rettifica_scarico = None

    registro.arrivo_fir = str(data.get("arrivo_fir") or "").strip()

    id_reg = str(data.get("id_registrazione") or "").strip()
    if id_reg:
        registro.id_registrazione = id_reg

    return errors


def _sync_to_sp(registro: RegistroRifiuti) -> None:
    """Push a registro to SharePoint (create or update)."""
    if not _graph_configured():
        return
    fields = _to_sp_fields(registro)
    if registro.sharepoint_item_id:
        _graph_update(registro.sharepoint_item_id, fields)
    else:
        ok, result = _graph_create(fields)
        if ok and isinstance(result, dict):
            sp_id = str((result.get("id") or result.get("fields", {}).get("id") or "")).strip()
            if not sp_id:
                # Try nested
                sp_id = str(result.get("fields", {}).get("@odata.id") or "").strip()
            if sp_id:
                RegistroRifiuti.objects.filter(pk=registro.pk).update(sharepoint_item_id=sp_id)
                registro.sharepoint_item_id = sp_id


# ── Views ─────────────────────────────────────────────────────────────────────


@login_required
def menu(request):
    return render(request, "rentri/pages/menu.html")


def _handle_form(request, tipo: str, template: str):
    """Generic handler for C/O/M/R form pages."""
    if request.method == "GET":
        return render(request, template, {"tipo": tipo})

    # POST — expect JSON
    data = _parse_json_body(request)
    registro = RegistroRifiuti()
    registro.inserito_da = _get_username(request)
    errors = _populate_registro(registro, data, tipo)

    if errors:
        return JsonResponse({"ok": False, "error": "; ".join(errors)}, status=400)

    try:
        registro.save()
        _sync_to_sp(registro)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    return JsonResponse({"ok": True, "id": registro.pk, "id_registrazione": registro.id_registrazione})


@login_required
def carico(request):
    return _handle_form(request, "C", "rentri/pages/carico.html")


@login_required
def scarico_originale(request):
    return _handle_form(request, "O", "rentri/pages/scarico_originale.html")


@login_required
def scarico_effettivo(request):
    return _handle_form(request, "M", "rentri/pages/scarico_effettivo.html")


@login_required
def rettifica_scarico(request):
    return _handle_form(request, "R", "rentri/pages/rettifica_scarico.html")


@login_required
def elenco(request):
    qs = RegistroRifiuti.objects.all()

    q_tipo = request.GET.get("tipo", "").strip()
    q_search = request.GET.get("q", "").strip()
    q_anno = request.GET.get("anno", "").strip()

    if q_tipo in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=q_tipo)
    if q_search:
        qs = qs.filter(codice__icontains=q_search) | qs.filter(rif_op__icontains=q_search)
    if q_anno:
        try:
            anno_int = int(q_anno)
            qs = qs.filter(data__year=anno_int)
        except ValueError:
            pass

    paginator = Paginator(qs.order_by("-data", "-id"), 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "rentri/pages/elenco.html", {
        "page_obj": page_obj,
        "q_tipo": q_tipo,
        "q_search": q_search,
        "q_anno": q_anno,
    })


@login_required
def modifica(request, pk: int):
    registro = get_object_or_404(RegistroRifiuti, pk=pk)

    if request.method == "GET":
        tipo_template_map = {
            "C": "rentri/pages/carico.html",
            "O": "rentri/pages/scarico_originale.html",
            "M": "rentri/pages/scarico_effettivo.html",
            "R": "rentri/pages/rettifica_scarico.html",
        }
        template = tipo_template_map.get(registro.tipo, "rentri/pages/carico.html")
        return render(request, template, {"registro": registro, "edit_mode": True})

    # POST or PATCH — accept JSON
    data = _parse_json_body(request)
    errors = _populate_registro(registro, data, registro.tipo)

    if errors:
        return JsonResponse({"ok": False, "error": "; ".join(errors)}, status=400)

    try:
        registro.save()
        _sync_to_sp(registro)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    return JsonResponse({"ok": True, "id": registro.pk, "id_registrazione": registro.id_registrazione})


@login_required
@require_POST
def elimina(request, pk: int):
    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    sp_id = registro.sharepoint_item_id
    registro.delete()
    if sp_id and _graph_configured():
        _graph_delete(sp_id)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_sync_pull(request):
    """Pull all items from SharePoint and upsert locally."""
    if not _graph_configured():
        return JsonResponse({"ok": False, "error": "Configurazione Graph non disponibile."}, status=503)

    try:
        items = _graph_get_all()
    except RuntimeError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    created = updated = 0
    for item in items:
        sp_id = str(item.get("id") or "").strip()
        if not sp_id:
            continue
        mapped = _from_sp_item(item)
        if not mapped.get("data"):
            continue

        existing = RegistroRifiuti.objects.filter(sharepoint_item_id=sp_id).first()
        if existing:
            for field, value in mapped.items():
                setattr(existing, field, value)
            existing.save()
            updated += 1
        else:
            # Determine tipo from carico_scarico or default to C
            cs = str(mapped.get("carico_scarico") or "").strip().upper()
            tipo = "C" if cs == "C" else "O"
            RegistroRifiuti.objects.create(tipo=tipo, **mapped)
            created += 1

    return JsonResponse({"ok": True, "created": created, "updated": updated, "total": len(items)})
