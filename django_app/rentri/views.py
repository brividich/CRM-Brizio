"""
Rentri — Registro Rifiuti RENTRI
Gestione locale + sincronizzazione con SharePoint tramite Microsoft Graph API.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date, datetime
from datetime import timezone as dt_timezone

import requests
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from django.contrib import messages

from config.env_config import get_first_env_value
from core.audit import log_action
from core.contact_people import parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.module_branding import get_module_branding_context, handle_module_branding_post
from core.upload_mime import safe_filename, validate_filename, UploadMimeValidationError


_RENTRI_CSV_MAX_BYTES = 5 * 1024 * 1024


def _validate_rentri_csv(uploaded_file):
    """Valida un upload CSV import RENTRI: nome, estensione, dimensione."""
    try:
        filename = validate_filename(getattr(uploaded_file, "name", ""), label="CSV")
    except UploadMimeValidationError as exc:
        return str(exc)
    if not filename.lower().endswith(".csv"):
        return f"{filename}: formato non consentito. Attesa estensione .csv."
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        return f"{filename}: file vuoto."
    if size > _RENTRI_CSV_MAX_BYTES:
        return f"{filename}: supera il limite di 5 MB."
    return None

from .models import RegistroRifiuti, RentriImpostazioni

# ── Helpers Graph / SharePoint ────────────────────────────────────────────────


def _is_placeholder(value: str) -> bool:
    return not value or value.startswith("<") and value.endswith(">")


def _graph_settings() -> dict[str, str]:
    return {
        "tenant_id": get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "site_id": get_first_env_value("GRAPH_SITE_ID"),
        "list_id_rentri": get_first_env_value("GRAPH_LIST_ID_RENTRI"),
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


def _build_families(records: list) -> list[dict]:
    """
    Raggruppa le registrazioni in famiglie: ogni famiglia ha uno o più C (carichi)
    e i relativi O/R/M collegati tramite il campo rif_op.
    Ritorna una lista ordinata per data del primo carico.
    """
    _ORM_ORDER = {"O": 0, "R": 1, "M": 2}

    c_map: dict[str, object] = {}
    ops: list = []
    for r in records:
        if r.tipo == "C":
            c_map[r.id_registrazione] = r
        else:
            ops.append(r)

    # family_key (tuple ordinata di id C) → lista di O/R/M
    family_ops: dict[tuple, list] = {}
    for op in ops:
        rif = str(op.rif_op or "").strip()
        fkey = tuple(sorted(x.strip() for x in rif.split(",") if x.strip())) if rif else ()
        family_ops.setdefault(fkey, []).append(op)

    # c_id → family_key
    c_to_fkey: dict[str, tuple] = {}
    for fkey in family_ops:
        for cid in fkey:
            c_to_fkey[cid] = fkey

    seen: set[tuple] = set()
    families: list[dict] = []

    for c_rec in sorted(c_map.values(), key=lambda r: (r.data or date.min, r.id_registrazione or "")):
        cid = c_rec.id_registrazione
        fkey = c_to_fkey.get(cid)

        if fkey:
            if fkey in seen:
                continue
            seen.add(fkey)
            carichi = sorted(
                [c_map[i] for i in fkey if i in c_map],
                key=lambda r: (r.data or date.min, r.id_registrazione or ""),
            )
            operazioni = sorted(
                family_ops.get(fkey, []),
                key=lambda r: (r.data or date.min, _ORM_ORDER.get(r.tipo, 9)),
            )
        else:
            carichi = [c_rec]
            operazioni = []

        families.append({"carichi": carichi, "operazioni": operazioni})

    # O/M/R orfani (nessun C trovato nel queryset corrente)
    for fkey, ops_list in family_ops.items():
        if fkey not in seen:
            families.append({
                "carichi": [],
                "operazioni": sorted(ops_list, key=lambda r: (r.data or date.min,)),
            })

    return families


_SORT_FIELDS = {
    "data": "data",
    "tipo": "tipo",
    "id_reg": "id_registrazione",
    "codice": "codice",
    "quantita": "quantita",
    "inserito_da": "inserito_da",
}

_GROUP_FIELDS = {
    "codice": ("codice", lambda r: r.codice or "—"),
    "tipo": ("tipo", lambda r: r.tipo),
    "anno": ("data__year", lambda r: str(r.data.year) if r.data else "—"),
    "inserito_da": ("inserito_da", lambda r: r.inserito_da or "—"),
}


@login_required
def elenco(request):
    qs = RegistroRifiuti.objects.all()

    q_tipo   = request.GET.get("tipo",  "").strip()
    q_search = request.GET.get("q",     "").strip()
    q_anno   = request.GET.get("anno",  "").strip()
    q_sort   = request.GET.get("sort",  "").strip()
    q_dir    = request.GET.get("dir",   "desc").strip()
    q_group  = request.GET.get("group", "").strip()
    q_view   = request.GET.get("view",  "famiglie").strip()  # default: vista famiglie

    if q_tipo in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=q_tipo)
    if q_search:
        qs = qs.filter(codice__icontains=q_search) | qs.filter(rif_op__icontains=q_search)
    if q_anno:
        try:
            qs = qs.filter(data__year=int(q_anno))
        except ValueError:
            pass

    ctx = {
        "q_tipo": q_tipo,
        "q_search": q_search,
        "q_anno": q_anno,
        "q_sort": q_sort,
        "q_dir": q_dir,
        "q_group": q_group,
        "q_view": q_view,
    }

    # ── Vista famiglie (default) ───────────────────────────────────────────────
    if q_view == "famiglie" and not q_group:
        # Carica tutti i record del filtro corrente, ordinati per data
        # La famiglia viene costruita in Python tramite rif_op
        records = list(qs.order_by("data", "id_registrazione"))
        families = _build_families(records)
        ctx["families"] = families
        ctx["total"] = sum(len(f["carichi"]) + len(f["operazioni"]) for f in families)
        return render(request, "rentri/pages/elenco.html", ctx)

    # ── Vista lista con sort/group ─────────────────────────────────────────────
    if q_sort in _SORT_FIELDS:
        order_field = _SORT_FIELDS[q_sort]
        qs = qs.order_by(order_field if q_dir == "asc" else f"-{order_field}", "id")
    else:
        qs = qs.order_by("-data", "-id")
        q_sort = "data"
        q_dir = "desc"
        ctx["q_sort"] = q_sort
        ctx["q_dir"] = q_dir

    # Raggruppamento — nessuna paginazione
    if q_group in _GROUP_FIELDS:
        order_db, key_fn = _GROUP_FIELDS[q_group]
        if q_sort in _SORT_FIELDS and q_sort != q_group:
            prefix = "" if q_dir == "asc" else "-"
            qs = qs.order_by(order_db, f"{prefix}{_SORT_FIELDS[q_sort]}", "id")
        else:
            qs = qs.order_by(order_db, "-data", "id")

        records = list(qs)
        groups = []
        current_key = None
        current_group: list = []
        for r in records:
            k = key_fn(r)
            if k != current_key:
                if current_group:
                    groups.append({"key": current_key, "rows": current_group})
                current_key = k
                current_group = [r]
            else:
                current_group.append(r)
        if current_group:
            groups.append({"key": current_key, "rows": current_group})

        ctx["groups"] = groups
        ctx["total"] = len(records)
        return render(request, "rentri/pages/elenco.html", ctx)

    # Vista flat paginata
    paginator = Paginator(qs, 50)
    ctx["page_obj"] = paginator.get_page(request.GET.get("page"))
    return render(request, "rentri/pages/elenco.html", ctx)


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


# ── CSV Import helpers ─────────────────────────────────────────────────────────

_IMPORT_TIPO_MAP = {
    "C - Carico": "C",
    "O - Scarico originario": "O",
    "M - Scarico effettivo": "M",
    "R - Rettifica scarico": "R",
}


def _parse_num_it(raw: str):
    """Converte numero in formato italiano (1.234 → 1234) in float o None."""
    s = raw.strip().replace(".", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_pericolosita_csv(raw: str) -> str:
    """Estrae codici HP (HP04, HP05…) da stringa JSON array."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        items = json.loads(raw)
        codes = []
        for item in items:
            m = re.match(r"(HP\d+)", str(item))
            if m:
                codes.append(m.group(1))
        return ", ".join(codes)[:100]
    except Exception:
        return raw[:100]


def _parse_csv_rows(content: str) -> tuple[list[dict], list[dict]]:
    """Analizza il contenuto CSV; restituisce (righe_ok, errori)."""
    rows: list[dict] = []
    errors: list[dict] = []

    reader = csv.reader(io.StringIO(content))
    try:
        next(reader)  # salta intestazione
    except StopIteration:
        return [], [{"riga": 0, "msg": "File vuoto o senza intestazione"}]

    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < 12:
            errors.append({"riga": line_no, "msg": f"Colonne insufficienti ({len(row)})"})
            continue
        try:
            data_raw = row[0].strip()
            try:
                data = datetime.strptime(data_raw, "%d/%m/%Y").date()
            except ValueError:
                errors.append({"riga": line_no, "msg": f"Data non valida: '{data_raw}'"})
                continue

            tipo_raw = row[6].strip()
            tipo = _IMPORT_TIPO_MAP.get(tipo_raw)
            if not tipo:
                errors.append({"riga": line_no, "msg": f"Tipo sconosciuto: '{tipo_raw}'"})
                continue

            id_reg = row[1].strip()
            codice = " ".join(row[2].split())[:100]
            pericolosita = _parse_pericolosita_csv(row[3])
            quantita = _parse_num_it(row[4])
            rettifica = _parse_num_it(row[5])
            note = row[7].strip()
            rentri_si_no = row[8].strip().lower() in ("vero", "true", "1")
            arrivo_fir = row[9].strip()
            inserito_da = row[10].strip()
            rif_op = row[11].strip()

            esiste = RegistroRifiuti.objects.filter(id_registrazione=id_reg, tipo=tipo).exists()

            rows.append({
                "riga": line_no,
                "data": data.strftime("%d/%m/%Y"),
                "_data_iso": data.isoformat(),
                "tipo": tipo,
                "id_reg": id_reg,
                "codice": codice,
                "quantita": str(quantita) if quantita is not None else "",
                "rettifica": str(rettifica) if rettifica is not None else "",
                "pericolosita": pericolosita,
                "note": note,
                "rentri_si_no": rentri_si_no,
                "arrivo_fir": arrivo_fir,
                "inserito_da": inserito_da,
                "rif_op": rif_op,
                "esiste": esiste,
            })
        except Exception as exc:
            errors.append({"riga": line_no, "msg": str(exc)})

    return rows, errors


@login_required
@require_POST
def import_preview(request):
    """POST: riceve un file CSV e restituisce un'anteprima JSON senza scrivere sul DB."""
    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        return JsonResponse({"ok": False, "error": "Nessun file selezionato"}, status=400)
    err = _validate_rentri_csv(csv_file)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    try:
        content = csv_file.read().decode("utf-8-sig")
    except Exception:
        return JsonResponse({"ok": False, "error": "Errore lettura file CSV (atteso UTF-8)."}, status=400)

    rows, errors = _parse_csv_rows(content)
    nuovi = sum(1 for r in rows if not r["esiste"])

    return JsonResponse({
        "ok": True,
        "rows": rows,
        "errors": errors,
        "totale": len(rows),
        "nuovi": nuovi,
        "skip": len(rows) - nuovi,
    })


@login_required
@require_POST
def import_confirm(request):
    """POST: importa effettivamente il CSV nel DB."""
    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        return JsonResponse({"ok": False, "error": "Nessun file"}, status=400)
    err = _validate_rentri_csv(csv_file)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    try:
        content = csv_file.read().decode("utf-8-sig")
    except Exception:
        return JsonResponse({"ok": False, "error": "Errore lettura file CSV (atteso UTF-8)."}, status=400)

    rows, parse_errors = _parse_csv_rows(content)
    created = 0
    skipped = 0
    import_errors = list(parse_errors)

    for r in rows:
        if r["esiste"]:
            skipped += 1
            continue
        try:
            data = datetime.fromisoformat(r["_data_iso"]).date()
            quantita = float(r["quantita"]) if r["quantita"] else None
            rettifica = float(r["rettifica"]) if r["rettifica"] else None

            registro = RegistroRifiuti(
                tipo=r["tipo"],
                data=data,
                id_registrazione=r["id_reg"],
                codice=r["codice"],
                quantita=quantita,
                rettifica_scarico=rettifica,
                carico_scarico=r["tipo"],
                pericolosita=r["pericolosita"],
                note_rentri=r["note"],
                rentri_si_no=r["rentri_si_no"],
                arrivo_fir=r["arrivo_fir"],
                rif_op=r["rif_op"],
                inserito_da=r["inserito_da"] or _get_username(request),
            )
            registro.save()
            # Forza l'id_registrazione originale (save() potrebbe sovrascriverlo)
            if registro.id_registrazione != r["id_reg"]:
                RegistroRifiuti.objects.filter(pk=registro.pk).update(id_registrazione=r["id_reg"])
            created += 1
        except Exception as exc:
            import_errors.append({"riga": r["riga"], "msg": str(exc)})

    return JsonResponse({
        "ok": True,
        "created": created,
        "skipped": skipped,
        "errors": import_errors,
    })


@login_required
def export_pdf(request):
    """GET: genera ed invia un PDF con le registrazioni RENTRI."""
    from io import BytesIO

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    # ── filtri ────────────────────────────────────────────────────────────────
    q_tipo = request.GET.get("tipo", "").strip()
    q_search = request.GET.get("q", "").strip()
    q_anno = request.GET.get("anno", "").strip()

    qs = RegistroRifiuti.objects.all()
    if q_tipo in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=q_tipo)
    if q_search:
        qs = qs.filter(codice__icontains=q_search) | qs.filter(rif_op__icontains=q_search)
    if q_anno:
        try:
            qs = qs.filter(data__year=int(q_anno))
        except ValueError:
            pass

    records = list(qs.order_by("data", "id"))
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── palette colori ────────────────────────────────────────────────────────
    COL_DARK  = colors.HexColor("#1e3a5f")
    COL_MID   = colors.HexColor("#2d5a9b")
    COL_ALT   = colors.HexColor("#f0f4fb")
    COL_GRID  = colors.HexColor("#d1d9e6")

    TIPO_BG = {
        "C": "#dbeafe",
        "O": "#fed7aa",
        "M": "#d9f99d",
        "R": "#fef08a",
    }
    TIPO_FG = {
        "C": "#1e40af",
        "O": "#9a3412",
        "M": "#166534",
        "R": "#854d0e",
    }
    TIPO_LABEL = {
        "C": "Carico",
        "O": "Scarico orig.",
        "M": "Scarico eff.",
        "R": "Rettifica",
    }

    # ── dimensioni pagina ─────────────────────────────────────────────────────
    PAGE_W, PAGE_H = landscape(A4)
    MARGIN   = 1.5 * cm
    HDR_H    = 2.1 * cm
    FTR_H    = 0.9 * cm

    # ── filtri stringa per footer ─────────────────────────────────────────────
    filter_parts = []
    if q_tipo:
        filter_parts.append(f"Tipo: {TIPO_LABEL.get(q_tipo, q_tipo)}")
    if q_anno:
        filter_parts.append(f"Anno: {q_anno}")
    if q_search:
        filter_parts.append(f"Ricerca: {q_search}")
    filters_str = " | ".join(filter_parts) if filter_parts else "Tutte le registrazioni"
    n_records = len(records)

    # ── callback decorazione pagina ───────────────────────────────────────────
    def _draw_page(canv, doc):
        canv.saveState()

        # banner superiore
        canv.setFillColor(COL_DARK)
        canv.rect(0, PAGE_H - HDR_H, PAGE_W, HDR_H, fill=1, stroke=0)

        # linea accent
        canv.setFillColor(COL_MID)
        canv.rect(0, PAGE_H - HDR_H - 2, PAGE_W, 2, fill=1, stroke=0)

        # titolo sinistro
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 15)
        canv.drawString(MARGIN, PAGE_H - HDR_H + 0.75 * cm, "RENTRI")
        canv.setFont("Helvetica", 8)
        canv.drawString(MARGIN, PAGE_H - HDR_H + 0.30 * cm,
                        "Registro Elettronico Nazionale Tracciabilità Rifiuti")

        # info destra
        canv.setFont("Helvetica-Bold", 8)
        canv.drawRightString(PAGE_W - MARGIN, PAGE_H - HDR_H + 0.75 * cm,
                             f"{n_records} registrazioni")
        canv.setFont("Helvetica", 7.5)
        canv.drawRightString(PAGE_W - MARGIN, PAGE_H - HDR_H + 0.30 * cm, now_str)

        # riga separazione colori tipo (legenda)
        legend_items = [
            ("C", "Carico"),
            ("O", "Scarico originario"),
            ("M", "Scarico effettivo"),
            ("R", "Rettifica"),
        ]
        lx = MARGIN
        ly = PAGE_H - HDR_H - 1.05 * cm
        dot_r = 3
        canv.setFont("Helvetica", 6.5)
        for tipo, label in legend_items:
            canv.setFillColor(colors.HexColor(TIPO_BG[tipo]))
            canv.circle(lx + dot_r, ly + dot_r, dot_r, fill=1, stroke=0)
            canv.setFillColor(colors.HexColor(TIPO_FG[tipo]))
            canv.drawString(lx + dot_r * 2 + 3, ly + 1, f"{tipo} – {label}")
            lx += 4.8 * cm

        # linea separazione legenda
        canv.setStrokeColor(COL_GRID)
        canv.setLineWidth(0.3)
        canv.line(MARGIN, PAGE_H - HDR_H - 1.5 * cm, PAGE_W - MARGIN, PAGE_H - HDR_H - 1.5 * cm)

        # footer
        canv.setStrokeColor(COL_GRID)
        canv.line(MARGIN, FTR_H + 0.1 * cm, PAGE_W - MARGIN, FTR_H + 0.1 * cm)
        canv.setFillColor(colors.HexColor("#6b7280"))
        canv.setFont("Helvetica", 6.5)
        canv.drawString(MARGIN, FTR_H * 0.35, filters_str)
        canv.drawRightString(PAGE_W - MARGIN, FTR_H * 0.35, f"Pagina {doc.page}")

        canv.restoreState()

    # ── documento ─────────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=HDR_H + 1.7 * cm,   # spazio per banner + legenda
        bottomMargin=FTR_H + 0.5 * cm,
    )

    # ── stili ─────────────────────────────────────────────────────────────────
    cell_s = ParagraphStyle("cell", fontName="Helvetica", fontSize=7, leading=9, wordWrap="CJK")
    cell_r = ParagraphStyle("cell_r", parent=cell_s, alignment=2)  # right-align numeri
    hdr_s  = ParagraphStyle(
        "hdr", fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=colors.white, alignment=1,
    )

    def _tipo_cell(tipo):
        label = f"<b>{tipo}</b> {TIPO_LABEL.get(tipo, '')}"
        fg = TIPO_FG.get(tipo, "#333333")
        s = ParagraphStyle(
            f"tipo_{tipo}", fontName="Helvetica", fontSize=7, leading=9,
            textColor=colors.HexColor(fg), alignment=1,
        )
        return Paragraph(label, s)

    # ── dati tabella ──────────────────────────────────────────────────────────
    COL_W = [2.0*cm, 3.0*cm, 3.0*cm, 7.4*cm, 1.9*cm, 1.9*cm, 5.2*cm, 2.3*cm]

    header_row = [
        Paragraph("Data", hdr_s),
        Paragraph("ID Reg.", hdr_s),
        Paragraph("Tipo", hdr_s),
        Paragraph("Codice EER", hdr_s),
        Paragraph("Qtà", hdr_s),
        Paragraph("Rettifica", hdr_s),
        Paragraph("Note / FIR", hdr_s),
        Paragraph("Inserito da", hdr_s),
    ]
    table_data = [header_row]
    for r in records:
        note_fir = r.note_rentri or r.arrivo_fir or ""
        table_data.append([
            Paragraph(r.data.strftime("%d/%m/%Y") if r.data else "", cell_s),
            Paragraph(r.id_registrazione or "", cell_s),
            _tipo_cell(r.tipo),
            Paragraph((r.codice or "")[:80], cell_s),
            Paragraph(str(r.quantita) if r.quantita is not None else "", cell_r),
            Paragraph(str(r.rettifica_scarico) if r.rettifica_scarico is not None else "", cell_r),
            Paragraph(note_fir[:70], cell_s),
            Paragraph((r.inserito_da or "")[:22], cell_s),
        ])

    table = Table(table_data, colWidths=COL_W, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  COL_DARK),
        ("LINEBELOW",     (0, 0), (-1, 0),  1.5,  COL_MID),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, COL_ALT]),
        ("GRID",          (0, 0), (-1, -1), 0.25, COL_GRID),
        ("LINEBEFORE",    (0, 0), (-1, -1), 0,    colors.white),   # annulla bordo sinistro
        ("LINEAFTER",     (-1, 0),(-1, -1), 0,    colors.white),   # annulla bordo destro
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ])
    for i, r in enumerate(records, start=1):
        bg = TIPO_BG.get(r.tipo)
        if bg:
            ts.add("BACKGROUND", (2, i), (2, i), colors.HexColor(bg))
    table.setStyle(ts)

    doc.build([table], onFirstPage=_draw_page, onLaterPages=_draw_page)

    buffer.seek(0)
    anno_str = q_anno or datetime.now().strftime("%Y")
    filename = f"rentri_{anno_str}_{datetime.now().strftime('%Y%m%d')}.pdf"
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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


@login_required
def impostazioni(request):
    """Impostazioni modulo Rentri — solo admin legacy."""
    legacy_user = get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    cfg = RentriImpostazioni.get_singleton()

    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="rentri",
            redirect_to="rentri_impostazioni",
            audit_module="rentri",
            fallback_label="RENTRI",
        )
        if branding_response is not None:
            return branding_response
        responsabili = parse_contact_people(request.POST.get("responsabili_raw", ""))
        primary = primary_contact(responsabili)
        cfg.codice_iscrizione_rentri = request.POST.get("codice_iscrizione_rentri", "").strip()
        cfg.ragione_sociale = request.POST.get("ragione_sociale", "").strip()
        cfg.responsabili = responsabili
        cfg.responsabile_nome = primary["nome"]
        cfg.responsabile_email = primary["email"]
        cfg.note_generali = request.POST.get("note_generali", "").strip()
        cfg.save()
        log_action(request, "modifica", "rentri", "Aggiornate impostazioni Rentri")
        messages.success(request, "Impostazioni salvate.")
        return redirect("rentri_impostazioni")

    return render(
        request,
        "rentri/pages/impostazioni.html",
        {
            "cfg": cfg,
            "responsabili_raw": serialize_contact_people(
                cfg.responsabili,
                fallback_name=cfg.responsabile_nome,
                fallback_email=cfg.responsabile_email,
            ),
            **get_module_branding_context("rentri", fallback_label="RENTRI"),
        },
    )
