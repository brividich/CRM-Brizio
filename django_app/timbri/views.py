from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.acl import user_can_modulo_action
from core.audit import log_action
from core.legacy_anagrafica import ensure_anagrafica_schema
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns
from core.models import AuditLog
from core.module_branding import get_module_branding_context, handle_module_branding_post

from .forms import RegistroTimbroForm, save_variant_image
from .models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine, TimbriImportIssue

logger = logging.getLogger(__name__)

_READ_ROLE_NAMES = {"admin", "amministrazione", "caporeparto", "hr"}
_EDIT_ROLE_NAMES = {"admin", "amministrazione"}
_COPY_ROLE_NAMES = {"admin", "amministrazione", "hr"}
_DOWNLOAD_ROLE_NAMES = {"admin", "amministrazione", "hr"}
_TIMBRI_REQUIRED_TABLES = {
    "timbri_operatoretimbri",
    "timbri_registrotimbro",
    "timbri_registrotimbroimmagine",
    "timbri_timbriimportissue",
}


def _legacy_user(request):
    return getattr(request, "legacy_user", None) or get_legacy_user(request.user)


def _legacy_role_name(legacy_user) -> str:
    return " ".join(str(getattr(legacy_user, "ruolo", "") or "").strip().lower().split())


def _can_view_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    if _legacy_role_name(legacy_user) in _READ_ROLE_NAMES:
        return True
    return any(
        user_can_modulo_action(request, "timbri", action)
        for action in ["timbri_home", "timbri_view", "admin_timbri"]
    )


def _can_edit_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    if _legacy_role_name(legacy_user) in _EDIT_ROLE_NAMES:
        return True
    return user_can_modulo_action(request, "timbri", "timbri_edit")


def _user_timbri_override(user, azione: str):
    """Ritorna il TimbriUserPermOverride per l'utente e l'azione dati, o None."""
    try:
        from .models import TimbriUserPermOverride
        return TimbriUserPermOverride.objects.filter(user=user, azione=azione).first()
    except Exception:
        return None


def _can_copy_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    # user-level override (explicit grant or deny)
    override = _user_timbri_override(request.user, "timbri_copy")
    if override is not None:
        return bool(override.granted)
    if _legacy_role_name(legacy_user) in _COPY_ROLE_NAMES:
        return True
    return user_can_modulo_action(request, "timbri", "timbri_copy")


def _can_download_timbri(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = _legacy_user(request)
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True
    # user-level override (explicit grant or deny)
    override = _user_timbri_override(request.user, "timbri_download")
    if override is not None:
        return bool(override.granted)
    if _legacy_role_name(legacy_user) in _DOWNLOAD_ROLE_NAMES:
        return True
    return user_can_modulo_action(request, "timbri", "timbri_download")


def _can_manage_timbri_config(request) -> bool:
    return _can_edit_timbri(request)


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_all_caps_text(value: str) -> bool:
    text = "".join(ch for ch in str(value or "") if ch.isalpha())
    return bool(text) and text == text.upper()


def _legacy_row_identity(row: dict) -> str:
    full_name = f"{_field_to_text(row.get('nome'))} {_field_to_text(row.get('cognome'))}".strip()
    key = _normalized_key(full_name)
    if key:
        return key
    return _normalized_key(_field_to_text(row.get("aliasusername")))


def _legacy_row_score(row: dict) -> tuple[int, int, int, int, int, int]:
    nome = _field_to_text(row.get("nome"))
    cognome = _field_to_text(row.get("cognome"))
    return (
        1 if row.get("utente_id") else 0,
        1 if nome and not _is_all_caps_text(nome) else 0,
        1 if cognome and not _is_all_caps_text(cognome) else 0,
        1 if _field_to_text(row.get("aliasusername")) else 0,
        1 if row.get("attivo") else 0,
        int(row.get("id") or 0),
    )


def _merge_duplicate_legacy_rows(rows: list[dict]) -> list[dict]:
    merged_by_key: dict[str, dict] = {}
    ordered: list[dict] = []
    merge_fields = ["matricola", "reparto", "mansione", "ruolo", "email_notifica", "email", "aliasusername", "attivo"]

    for row in rows:
        key = _legacy_row_identity(row)
        if not key:
            ordered.append(row)
            continue
        current = merged_by_key.get(key)
        if current is None:
            clone = dict(row)
            clone["_merged_ids"] = [int(row.get("id") or 0)]
            merged_by_key[key] = clone
            ordered.append(clone)
            continue

        preferred = current
        alternate = row
        if _legacy_row_score(row) > _legacy_row_score(current):
            preferred = dict(row)
            preferred["_merged_ids"] = list(current.get("_merged_ids") or [])
            alternate = current
            merged_by_key[key] = preferred
            ordered[ordered.index(current)] = preferred

        merged_ids = {int(value) for value in list(preferred.get("_merged_ids") or []) if int(value or 0) > 0}
        merged_ids.add(int(alternate.get("id") or 0))
        preferred["_merged_ids"] = sorted(merged_ids)
        for field_name in merge_fields:
            if _field_to_text(preferred.get(field_name)):
                continue
            value = alternate.get(field_name)
            if value not in {None, ""}:
                preferred[field_name] = value

    return ordered


def _field_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ["displayValue", "description", "url", "serverUrl", "text", "Value", "value"]:
            raw = value.get(key)
            if raw:
                return str(raw).strip()
        return ""
    if isinstance(value, list):
        return " ".join([str(x).strip() for x in value if str(x or "").strip()])
    return str(value).strip()


def _legacy_employee_rows(*, legacy_id: int | None = None) -> list[dict]:
    cols = legacy_table_columns("anagrafica_dipendenti")
    if not cols:
        return []
    wanted = [
        c
        for c in ["id", "aliasusername", "nome", "cognome", "matricola", "reparto", "mansione", "ruolo", "email_notifica", "attivo"]
        if c in cols
    ]
    if not wanted:
        return []
    with connections["default"].cursor() as cursor:
        sql = f"SELECT {', '.join(wanted)} FROM anagrafica_dipendenti"
        params: list[object] = []
        if legacy_id is not None and "id" in wanted:
            sql += " WHERE id = %s"
            params.append(int(legacy_id))
        sql += " ORDER BY cognome, nome"
        cursor.execute(sql, params)
        headers = [str(col[0]).lower() for col in cursor.description]
        rows = [dict(zip(headers, row)) for row in cursor.fetchall()]
    if legacy_id is not None:
        return rows
    return _merge_duplicate_legacy_rows(rows)


def _legacy_role_value(row: dict) -> str:
    return _field_to_text(row.get("mansione") or row.get("ruolo"))[:200]


def _legacy_full_name(row: dict) -> str:
    text = f"{_field_to_text(row.get('cognome'))} {_field_to_text(row.get('nome'))}".strip()
    return " ".join(text.split()) or _field_to_text(row.get("aliasusername")) or f"anagrafica:{row.get('id')}"


def _load_legacy_employee(legacy_id: int) -> dict | None:
    rows = _legacy_employee_rows(legacy_id=legacy_id)
    return rows[0] if rows else None


def _normalize_text_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_legacy_employee(*, lookup_value, label_value, matricola_value) -> dict | None:
    lookup_text = _field_to_text(lookup_value)
    label = _field_to_text(label_value)
    matricola = _field_to_text(matricola_value)

    if lookup_text.isdigit():
        row = _load_legacy_employee(int(lookup_text))
        if row:
            return row

    rows = _legacy_employee_rows()
    if matricola:
        search_matricola = matricola.casefold()
        for row in rows:
            if _field_to_text(row.get("matricola")).casefold() == search_matricola:
                return row

    if label:
        search_label = _normalize_text_key(label)
        for row in rows:
            options = {
                _normalize_text_key(_legacy_full_name(row)),
                _normalize_text_key(f"{_field_to_text(row.get('nome'))} {_field_to_text(row.get('cognome'))}"),
                _normalize_text_key(f"{_field_to_text(row.get('cognome'))} {_field_to_text(row.get('nome'))}"),
            }
            if search_label in options:
                return row
    return None


def _ensure_legacy_operatore(row: dict) -> OperatoreTimbri:
    legacy_id = int(row.get("id") or 0)
    if legacy_id <= 0:
        raise RuntimeError("ID anagrafica non valido.")

    defaults = {
        "nome": _field_to_text(row.get("nome"))[:200] or "Operatore",
        "cognome": _field_to_text(row.get("cognome"))[:200],
        "matricola": _field_to_text(row.get("matricola"))[:100],
        "reparto": _field_to_text(row.get("reparto"))[:200],
        "ruolo": _legacy_role_value(row),
        "email_notifica": _field_to_text(row.get("email_notifica"))[:200],
        "is_active_legacy": bool(row.get("attivo")) if row.get("attivo") is not None else True,
    }
    obj = OperatoreTimbri.objects.filter(legacy_anagrafica_id=legacy_id).first()
    if obj is None:
        return OperatoreTimbri.objects.create(legacy_anagrafica_id=legacy_id, **defaults)

    updates: list[str] = []
    for field_name, value in defaults.items():
        if getattr(obj, field_name) != value:
            setattr(obj, field_name, value)
            updates.append(field_name)
    if updates:
        obj.save(update_fields=updates + ["updated_at"])
    return obj


def _tipo_from_text(raw_value: str) -> str:
    text = _field_to_text(raw_value).lower()
    if not text:
        return RegistroTimbro.TIPO_FISICO_E_DIGITALE
    if "fisico" in text and "digit" in text:
        return RegistroTimbro.TIPO_FISICO_E_DIGITALE
    if "digit" in text:
        return RegistroTimbro.TIPO_DIGITALE
    if "fisico" in text:
        return RegistroTimbro.TIPO_FISICO
    return RegistroTimbro.TIPO_ALTRO


def _resolve_operatore(lookup_value, label_value, matricola_value, reparto_value, ruolo_value) -> OperatoreTimbri:
    row = _find_legacy_employee(
        lookup_value=lookup_value,
        label_value=label_value,
        matricola_value=matricola_value,
    )
    if row is None:
        reparto = _field_to_text(reparto_value)
        ruolo = _field_to_text(ruolo_value)
        raise LookupError(
            "Operatore non trovato nell'anagrafica centrale"
            + (f" (matricola {matricola_value})" if _field_to_text(matricola_value) else "")
            + (f" [reparto {reparto}]" if reparto else "")
            + (f" [ruolo {ruolo}]" if ruolo else "")
        )
    return _ensure_legacy_operatore(row)


def cleanup_orphan_operatori() -> dict[str, int]:
    summary = {
        "orphans": 0,
        "deleted_empty": 0,
        "relinked_operatori": 0,
        "records_relinked": 0,
        "unmatched_with_records": 0,
    }
    orphans = list(
        OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=True).annotate(record_count=Count("registri")).order_by("id")
    )
    for operatore in orphans:
        summary["orphans"] += 1
        row = _find_legacy_employee(
            lookup_value="",
            label_value=operatore.full_name,
            matricola_value=operatore.matricola,
        )
        if row is not None:
            target = _ensure_legacy_operatore(row)
            moved = RegistroTimbro.objects.filter(operatore=operatore).update(operatore=target)
            summary["records_relinked"] += int(moved)
            operatore.delete()
            summary["relinked_operatori"] += 1
            continue
        if int(getattr(operatore, "record_count", 0) or 0) > 0:
            summary["unmatched_with_records"] += 1
            continue
        operatore.delete()
        summary["deleted_empty"] += 1
    return summary


def reset_timbri_table() -> dict[str, int]:
    ensure_anagrafica_schema()
    summary = {
        "deleted_images": 0,
        "deleted_records": 0,
        "deleted_operatori": 0,
        "imported_operatori": 0,
    }
    employee_rows = _legacy_employee_rows()
    with transaction.atomic():
        summary["deleted_images"], _ = RegistroTimbroImmagine.objects.all().delete()
        summary["deleted_records"], _ = RegistroTimbro.objects.all().delete()
        summary["deleted_operatori"], _ = OperatoreTimbri.objects.all().delete()
        for row in employee_rows:
            _ensure_legacy_operatore(row)
            summary["imported_operatori"] += 1
    return summary


def _employee_row_payload(row: dict, bridge: OperatoreTimbri | None = None) -> dict:
    legacy_id = int(row.get("id") or 0)
    active_records = int(getattr(bridge, "active_records", 0) or 0)
    historical_records = int(getattr(bridge, "historical_records", 0) or 0)
    return {
        "legacy_id": legacy_id,
        "full_name": _legacy_full_name(row),
        "nome": _field_to_text(row.get("nome")),
        "cognome": _field_to_text(row.get("cognome")),
        "aliasusername": _field_to_text(row.get("aliasusername")),
        "matricola": _field_to_text(row.get("matricola")),
        "reparto": _field_to_text(row.get("reparto")),
        "ruolo": _legacy_role_value(row),
        "email_notifica": _field_to_text(row.get("email_notifica")),
        "is_active_legacy": bool(row.get("attivo")) if row.get("attivo") is not None else True,
        "active_records": active_records,
        "historical_records": historical_records,
        "timbri_count": active_records + historical_records,
        "bridge_id": getattr(bridge, "id", None),
    }


def _categorize_records(records: list[RegistroTimbro]) -> tuple[list, list, list]:
    """Split records into (timbri, firme, sigle) based on tipo_timbro."""
    timbri, firme, sigle = [], [], []
    for r in records:
        if r.tipo_timbro in RegistroTimbro.TIPI_FIRMA:
            firme.append(r)
        elif r.tipo_timbro in RegistroTimbro.TIPI_SIGLA:
            sigle.append(r)
        else:
            timbri.append(r)
    return timbri, firme, sigle


def _attach_image_maps(registri: list[RegistroTimbro]) -> None:
    for registro in registri:
        registro.image_map = {img.variante: img for img in registro.immagini.all()}
        registro.image_slots = [
            {"key": RegistroTimbroImmagine.VARIANTE_TIMBRO, "label": "Timbro", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_TIMBRO)},
            {"key": RegistroTimbroImmagine.VARIANTE_FIRMA, "label": "Firma", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_FIRMA)},
            {"key": RegistroTimbroImmagine.VARIANTE_SIGLA, "label": "Sigla", "image": registro.image_map.get(RegistroTimbroImmagine.VARIANTE_SIGLA)},
        ]


def _forbidden():
    return HttpResponseForbidden("Permesso negato.")


def _timbri_schema_issue() -> str:
    try:
        with connections["default"].cursor() as cursor:
            existing_tables = {
                str(name).strip().lower()
                for name in connections["default"].introspection.table_names(cursor)
            }
    except DatabaseError as exc:
        logger.warning("[timbri] verifica schema fallita: %s", exc)
        return "Impossibile verificare lo schema SQL del modulo Timbri."

    missing_tables = sorted(table for table in _TIMBRI_REQUIRED_TABLES if table not in existing_tables)
    if not missing_tables:
        return ""
    return (
        "Modulo Timbri non inizializzato sul database SQL Server. "
        "Mancano le tabelle: "
        + ", ".join(missing_tables)
        + ". Esegui `manage.py migrate timbri`."
    )


def _empty_page(page_number):
    return Paginator([], 30).get_page(page_number)


def _pending_import_issues(limit: int | None = None):
    qs = TimbriImportIssue.objects.filter(is_resolved=False).order_by(
        "operatore_label", "matricola", "csv_row_number", "id"
    )
    if limit:
        return list(qs[:limit])
    return list(qs)


def _base_context(request, **extra):
    legacy_user = _legacy_user(request)
    display_name = (
        (legacy_user.nome if legacy_user else None)
        or request.user.get_full_name()
        or request.user.username
    )
    base = {
        "page_title": "Registro timbri",
        "current": extra.get("current", "timbri:index"),
        "username": display_name,
        "can_edit_timbri": _can_edit_timbri(request),
        "can_copy_timbri": _can_copy_timbri(request),
        "can_download_timbri": _can_download_timbri(request),
        "can_manage_timbri_config": _can_manage_timbri_config(request),
        **get_module_branding_context("timbri", fallback_label="Timbri"),
    }
    base.update(extra)
    return base


@login_required
def index(request):
    if not _can_view_timbri(request):
        return _forbidden()

    schema_issue = _timbri_schema_issue()
    if schema_issue:
        return render(
            request,
            "timbri/pages/index.html",
            _base_context(
                request,
                current="timbri:index",
                page_obj=_empty_page(request.GET.get("page")),
                q=str(request.GET.get("q") or "").strip(),
                reparto=str(request.GET.get("reparto") or "").strip(),
                reparti=[],
                schema_issue=schema_issue,
                stats={
                    "dipendenti": 0,
                    "con_timbri": 0,
                    "record_attivi": 0,
                    "da_gestire": 0,
                },
                pending_issues=[],
            ),
        )

    q = str(request.GET.get("q") or "").strip()
    reparto = str(request.GET.get("reparto") or "").strip()
    rows = _legacy_employee_rows()
    reparti = sorted({_field_to_text(row.get("reparto")) for row in rows if _field_to_text(row.get("reparto"))})
    if q:
        q_norm = q.casefold()
        rows = [
            row
            for row in rows
            if any(
                q_norm in value.casefold()
                for value in [
                    _legacy_full_name(row),
                    _field_to_text(row.get("aliasusername")),
                    _field_to_text(row.get("matricola")),
                    _field_to_text(row.get("reparto")),
                    _legacy_role_value(row),
                ]
                if value
            )
        ]
    if reparto:
        rows = [row for row in rows if _field_to_text(row.get("reparto")).casefold() == reparto.casefold()]

    legacy_ids = [int(row.get("id") or 0) for row in rows if int(row.get("id") or 0) > 0]
    bridge_map = {
        int(obj.legacy_anagrafica_id): obj
        for obj in (
            OperatoreTimbri.objects.filter(legacy_anagrafica_id__in=legacy_ids)
            .annotate(
                active_records=Count("registri", filter=Q(registri__is_attivo=True, registri__is_archived=False), distinct=True),
                historical_records=Count("registri", filter=Q(registri__is_attivo=False) | Q(registri__is_archived=True), distinct=True),
            )
        )
        if obj.legacy_anagrafica_id
    }
    entries = [_employee_row_payload(row, bridge_map.get(int(row.get("id") or 0))) for row in rows]
    paginator = Paginator(entries, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    pending_issues = _pending_import_issues(100)

    return render(
        request,
        "timbri/pages/index.html",
        _base_context(
            request,
            current="timbri:index",
            page_obj=page_obj,
            q=q,
            reparto=reparto,
            reparti=reparti,
            stats={
                "dipendenti": len(rows),
                "con_timbri": sum(1 for item in entries if item["timbri_count"] > 0),
                "record_attivi": RegistroTimbro.objects.filter(is_attivo=True, is_archived=False).count(),
                "da_gestire": len(pending_issues),
            },
            pending_issues=pending_issues,
        ),
    )


@login_required
def operatore_delete(request, operatore_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")

    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        messages.error(request, "I dipendenti collegati all'anagrafica centrale non si eliminano dal modulo timbri.")
        return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))
    operatore_label = operatore.full_name
    registri = list(
        RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
            Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.all())
        )
    )
    record_count = len(registri)
    image_count = sum(record.immagini.count() for record in registri)

    for record in registri:
        for image in list(record.immagini.all()):
            image.delete()
        record.delete()
    operatore.delete()

    log_action(
        request,
        "timbri_operatore_delete",
        "timbri",
        {"operatore_id": operatore_id, "record_count": record_count, "image_count": image_count},
    )
    messages.success(request, f"Operatore {operatore_label} eliminato.")
    return redirect("timbri:index")


@login_required
def operatore_preview(request, legacy_id: int):
    if not _can_view_timbri(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        return JsonResponse({"records": []})
    operatore = OperatoreTimbri.objects.filter(legacy_anagrafica_id=legacy_id).first()
    if not operatore:
        return JsonResponse({"records": []})
    records = list(
        RegistroTimbro.objects.filter(operatore=operatore, is_attivo=True, is_archived=False)
        .prefetch_related("immagini")
        .order_by("-data_consegna")
    )
    _attach_image_maps(records)
    data = []
    for r in records:
        slots = []
        for slot in r.image_slots:
            slots.append({
                "label": slot["label"],
                "url": reverse("timbri:serve_image", args=[slot["image"].id]) if slot["image"] else None,
            })
        data.append({
            "codice": r.codice_timbro or "",
            "qualifica": r.qualifica or "",
            "tipo": r.get_tipo_timbro_display(),
            "slots": slots,
        })
    return JsonResponse({"records": data})


@login_required
def operatore_report(request, legacy_id: int):
    if not _can_view_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    row = _load_legacy_employee(legacy_id)
    if row is None:
        messages.error(request, "Dipendente non trovato nell'anagrafica centrale.")
        return redirect("timbri:index")

    show_timbri = request.GET.get("timbri", "1") != "0"

    # Timbri / firma / sigla
    operatore = _ensure_legacy_operatore(row)
    active_records = list(
        RegistroTimbro.objects.filter(operatore=operatore, is_attivo=True, is_archived=False)
        .prefetch_related(Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante")))
        .order_by("-data_consegna")
    )
    _attach_image_maps(active_records)
    timbri, firme, sigle = _categorize_records(active_records)

    # Asset assegnati
    assets = []
    try:
        from assets.models import Asset
        assets = list(
            Asset.objects.filter(assigned_legacy_user_id=legacy_id)
            .select_related("asset_category")
            .order_by("name", "asset_tag")
        )
    except Exception:
        logger.exception("Impossibile caricare asset per report dipendente %s", legacy_id)

    employee = {
        "legacy_id": int(row.get("id") or 0),
        "full_name": _legacy_full_name(row),
        "nome": _field_to_text(row.get("nome")),
        "cognome": _field_to_text(row.get("cognome")),
        "matricola": _field_to_text(row.get("matricola")),
        "reparto": _field_to_text(row.get("reparto")),
        "ruolo": _legacy_role_value(row),
        "mansione": _field_to_text(row.get("mansione")),
        "email": _field_to_text(row.get("email")),
        "email_notifica": _field_to_text(row.get("email_notifica")),
        "aliasusername": _field_to_text(row.get("aliasusername")),
        "attivo": bool(row.get("attivo")) if row.get("attivo") is not None else True,
    }

    base_url = reverse("timbri:operatore_report", args=[legacy_id])
    return render(request, "timbri/pages/report.html", {
        "employee": employee,
        "assets": assets,
        "timbri": timbri,
        "firme": firme,
        "sigle": sigle,
        "show_timbri": show_timbri,
        "generated_at": timezone.now(),
        "can_copy_timbri": _can_copy_timbri(request),
        "url_completo": base_url + "?timbri=1",
        "url_senza_timbri": base_url + "?timbri=0",
    })


@login_required
def operatore_create(request):
    if not _can_edit_timbri(request):
        return _forbidden()
    messages.info(request, "Gli operatori si gestiscono dall'anagrafica centrale. Da timbri puoi solo aggiungere record ai dipendenti esistenti.")
    return redirect("anagrafica:dipendenti_list")


@login_required
def operatore_detail(request, operatore_id: int):
    if not _can_view_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))

    registri_qs = RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
        Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))
    )
    active_records = list(registri_qs.filter(is_attivo=True, is_archived=False))
    historical_records = list(registri_qs.exclude(is_attivo=True, is_archived=False))
    _attach_image_maps(active_records)
    _attach_image_maps(historical_records)

    return render(
        request,
        "timbri/pages/operatore_detail.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={
                "legacy_id": None,
                "full_name": operatore.full_name,
                "matricola": operatore.matricola,
                "reparto": operatore.reparto,
                "ruolo": operatore.ruolo,
                "email_notifica": operatore.email_notifica,
                "source_label": "bridge locale",
            },
            is_central_profile=False,
            active_records=active_records,
            historical_records=historical_records,
            stats={
                "totale": registri_qs.count(),
                "attivi": len(active_records),
                "storico": len(historical_records),
            },
        ),
    )


@login_required
def operatore_detail_by_legacy(request, legacy_id: int):
    if not _can_view_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    row = _load_legacy_employee(legacy_id)
    if row is None:
        messages.error(request, "Dipendente non trovato nell'anagrafica centrale.")
        return redirect("timbri:index")

    operatore = _ensure_legacy_operatore(row)
    registri_qs = RegistroTimbro.objects.filter(operatore=operatore).prefetch_related(
        Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))
    )
    active_records = list(registri_qs.filter(is_attivo=True, is_archived=False))
    historical_records = list(registri_qs.exclude(is_attivo=True, is_archived=False))
    _attach_image_maps(active_records)
    _attach_image_maps(historical_records)
    active_timbri, active_firme, active_sigle = _categorize_records(active_records)
    hist_timbri, hist_firme, hist_sigle = _categorize_records(historical_records)
    legacy_id_int = int(row.get("id") or 0)

    from anagrafica.models import DipendenteAnagraficaCivile
    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id_int).first()
    foto_url = ""
    if civile and civile.foto:
        try:
            foto_url = civile.foto.url
        except (OSError, ValueError):
            foto_url = ""

    return render(
        request,
        "timbri/pages/operatore_detail.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={
                "legacy_id": legacy_id_int,
                "full_name": _legacy_full_name(row),
                "nome": _field_to_text(row.get("nome")),
                "cognome": _field_to_text(row.get("cognome")),
                "matricola": _field_to_text(row.get("matricola")),
                "reparto": _field_to_text(row.get("reparto")),
                "ruolo": _legacy_role_value(row),
                "email_notifica": _field_to_text(row.get("email_notifica")),
                "source_label": "anagrafica centrale",
                "foto_url": foto_url,
            },
            is_central_profile=True,
            active_records=active_records,
            historical_records=historical_records,
            active_timbri=active_timbri,
            active_firme=active_firme,
            active_sigle=active_sigle,
            hist_timbri=hist_timbri,
            hist_firme=hist_firme,
            hist_sigle=hist_sigle,
            report_url=reverse("timbri:operatore_report", args=[legacy_id_int]) if legacy_id_int else None,
            stats={
                "totale": registri_qs.count(),
                "attivi": len(active_records),
                "storico": len(historical_records),
            },
        ),
    )


def _save_record_from_form(request, form: RegistroTimbroForm, *, operatore: OperatoreTimbri) -> RegistroTimbro:
    registro = form.save(commit=False)
    registro.operatore = operatore
    registro.updated_by = request.user
    registro.edited_in_portal = True
    registro.is_archived = False
    if not registro.pk:
        registro.created_by = request.user
    registro.save()
    for field_name, variante in [
        ("image_timbro", RegistroTimbroImmagine.VARIANTE_TIMBRO),
        ("image_firma", RegistroTimbroImmagine.VARIANTE_FIRMA),
        ("image_sigla", RegistroTimbroImmagine.VARIANTE_SIGLA),
    ]:
        uploaded = form.cleaned_data.get(field_name)
        if uploaded:
            save_variant_image(registro=registro, variante=variante, uploaded_file=uploaded)
    return registro


@login_required
def registro_create(request, operatore_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    operatore = get_object_or_404(OperatoreTimbri, pk=operatore_id)
    if operatore.legacy_anagrafica_id:
        return redirect("timbri:registro_create_by_legacy", legacy_id=int(operatore.legacy_anagrafica_id))
    initial_tipo = str(request.GET.get("tipo") or "").strip().upper()
    allowed_types = {choice[0] for choice in RegistroTimbro.TIPO_CHOICES}
    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=operatore)
            log_action(request, "timbri_registro_create", "timbri", {"operatore_id": operatore.id, "registro_id": registro.id})
            messages.success(request, "Registro timbro salvato.")
            return redirect("timbri:operatore_detail", operatore_id=operatore.id)
    else:
        form = RegistroTimbroForm(
            initial={
                "is_attivo": True,
                "tipo_timbro": initial_tipo if initial_tipo in allowed_types else RegistroTimbro.TIPO_FISICO_E_DIGITALE,
            }
        )
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={"legacy_id": None, "full_name": operatore.full_name},
            form=form,
            form_title="Nuovo record timbro",
            record=None,
        ),
    )


@login_required
def registro_create_by_legacy(request, legacy_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")

    row = _load_legacy_employee(legacy_id)
    if row is None:
        messages.error(request, "Dipendente non trovato nell'anagrafica centrale.")
        return redirect("timbri:index")

    operatore = _ensure_legacy_operatore(row)
    initial_tipo = str(request.GET.get("tipo") or "").strip().upper()
    allowed_types = {choice[0] for choice in RegistroTimbro.TIPO_CHOICES}
    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=operatore)
            log_action(request, "timbri_registro_create", "timbri", {"operatore_id": operatore.id, "registro_id": registro.id})
            messages.success(request, "Registro timbro salvato.")
            return redirect("timbri:operatore_detail_by_legacy", legacy_id=legacy_id)
    else:
        form = RegistroTimbroForm(
            initial={
                "is_attivo": True,
                "tipo_timbro": initial_tipo if initial_tipo in allowed_types else RegistroTimbro.TIPO_FISICO_E_DIGITALE,
            }
        )
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=operatore,
            employee={"legacy_id": int(row.get("id") or 0), "full_name": _legacy_full_name(row)},
            form=form,
            form_title="Nuovo record timbro",
            record=None,
        ),
    )


@login_required
def registro_edit(request, record_id: int):
    if not _can_edit_timbri(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        messages.error(request, schema_issue)
        return redirect("timbri:index")
    record = get_object_or_404(
        RegistroTimbro.objects.prefetch_related(Prefetch("immagini", queryset=RegistroTimbroImmagine.objects.order_by("variante"))),
        pk=record_id,
    )
    _attach_image_maps([record])
    if request.method == "POST" and str(request.POST.get("action") or "").strip() == "archive":
        record.is_attivo = False
        record.is_archived = True
        if not record.data_ritiro:
            record.data_ritiro = timezone.now().date()
        record.edited_in_portal = True
        record.updated_by = request.user
        record.save(update_fields=["is_attivo", "is_archived", "data_ritiro", "edited_in_portal", "updated_by", "updated_at"])
        log_action(request, "timbri_registro_archive", "timbri", {"registro_id": record.id, "operatore_id": record.operatore_id})
        messages.success(request, "Record archiviato.")
        if record.operatore.legacy_anagrafica_id:
            return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(record.operatore.legacy_anagrafica_id))
        return redirect("timbri:operatore_detail", operatore_id=record.operatore_id)

    if request.method == "POST":
        form = RegistroTimbroForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            registro = _save_record_from_form(request, form, operatore=record.operatore)
            log_action(request, "timbri_registro_update", "timbri", {"registro_id": registro.id, "operatore_id": registro.operatore_id})
            messages.success(request, "Record aggiornato.")
            if registro.operatore.legacy_anagrafica_id:
                return redirect("timbri:operatore_detail_by_legacy", legacy_id=int(registro.operatore.legacy_anagrafica_id))
            return redirect("timbri:operatore_detail", operatore_id=registro.operatore_id)
    else:
        form = RegistroTimbroForm(instance=record)

    employee = {
        "legacy_id": None,
        "full_name": record.operatore.full_name,
    }
    if record.operatore.legacy_anagrafica_id:
        row = _load_legacy_employee(int(record.operatore.legacy_anagrafica_id))
        employee = {
            "legacy_id": int(record.operatore.legacy_anagrafica_id),
            "full_name": _legacy_full_name(row) if row else record.operatore.full_name,
        }
    return render(
        request,
        "timbri/pages/record_form.html",
        _base_context(
            request,
            current="timbri:index",
            operatore=record.operatore,
            employee=employee,
            form=form,
            form_title="Modifica record timbro",
            record=record,
        ),
    )


def _permessi_timbri_context() -> dict:
    """Legge i permessi ACL v2 correnti per copia/download timbri, inclusi override utente."""
    try:
        from core.legacy_models import Permesso, Ruolo
        from .models import TimbriUserPermOverride
        from django.contrib.auth import get_user_model
        User = get_user_model()

        ruoli = list(Ruolo.objects.order_by("nome"))
        permessi_copy = {
            int(p.ruolo_id): p
            for p in Permesso.objects.filter(modulo="timbri", azione="timbri_copy")
        }
        permessi_download = {
            int(p.ruolo_id): p
            for p in Permesso.objects.filter(modulo="timbri", azione="timbri_download")
        }
        rows = []
        for ruolo in ruoli:
            rid = int(ruolo.id)
            pc = permessi_copy.get(rid)
            pd = permessi_download.get(rid)
            rows.append({
                "ruolo_id": rid,
                "ruolo_nome": ruolo.nome,
                "can_copy": bool(pc and pc.can_view),
                "can_download": bool(pd and pd.can_view),
            })

        # Override per-utente
        overrides = list(
            TimbriUserPermOverride.objects.select_related("user").order_by("user__username", "azione")
        )
        # Raggruppa per user: {user_id: {"user": ..., "copy": bool|None, "download": bool|None}}
        user_override_map: dict[int, dict] = {}
        for ov in overrides:
            uid = int(ov.user_id)
            if uid not in user_override_map:
                user_override_map[uid] = {"user": ov.user, "copy": None, "download": None}
            if ov.azione == TimbriUserPermOverride.AZIONE_COPY:
                user_override_map[uid]["copy"] = ov.granted
            elif ov.azione == TimbriUserPermOverride.AZIONE_DOWNLOAD:
                user_override_map[uid]["download"] = ov.granted
        user_override_rows = list(user_override_map.values())

        # Tutti gli utenti attivi (per la select di aggiunta)
        all_users = list(
            User.objects.filter(is_active=True).order_by("username").values("id", "username", "first_name", "last_name")
        )
        overridden_user_ids = set(user_override_map.keys())

        return {
            "permessi_rows": rows,
            "user_override_rows": user_override_rows,
            "all_users": all_users,
            "overridden_user_ids": overridden_user_ids,
        }
    except Exception:
        return {"permessi_rows": [], "user_override_rows": [], "all_users": [], "overridden_user_ids": set()}


@login_required
def configurazione_page(request):
    if not _can_manage_timbri_config(request):
        return _forbidden()

    schema_issue = _timbri_schema_issue()
    tab = str(request.GET.get("tab") or "operazioni").strip() or "operazioni"
    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        redirect_url = f"{reverse('timbri:configurazione')}?tab={tab}"
        branding_response = handle_module_branding_post(
            request,
            module_key="timbri",
            redirect_to=redirect_url,
            audit_module="timbri",
            fallback_label="Timbri",
        )
        if branding_response is not None:
            return branding_response

        if action == "save_permessi":
            try:
                from core.legacy_models import Permesso, Ruolo
                ruoli = list(Ruolo.objects.all())
                azioni = ["timbri_copy", "timbri_download"]
                for ruolo in ruoli:
                    rid = int(ruolo.id)
                    for azione in azioni:
                        field_key = f"perm_{azione}_{rid}"
                        granted = request.POST.get(field_key) == "1"
                        row = Permesso.objects.filter(ruolo_id=rid, modulo="timbri", azione=azione).order_by("-id").first()
                        fields = {
                            "consentito": 1 if granted else 0,
                            "can_view": 1 if granted else 0,
                            "can_edit": 1 if granted else 0,
                            "can_delete": 0,
                            "can_approve": 0,
                        }
                        if row is None:
                            Permesso.objects.create(ruolo_id=rid, modulo="timbri", azione=azione, **fields)
                        else:
                            updates = []
                            for f, v in fields.items():
                                if getattr(row, f, None) != v:
                                    setattr(row, f, v)
                                    updates.append(f)
                            if updates:
                                row.save(update_fields=updates)
                log_action(request, "timbri_permessi_save", "timbri", {"azioni": azioni})
                messages.success(request, "Permessi copia/download aggiornati.")
            except Exception as exc:
                logger.exception("[timbri] salvataggio permessi fallito")
                messages.error(request, f"Errore salvataggio permessi: {exc}")
            return redirect(f"{reverse('timbri:configurazione')}?tab=permessi")

        if action == "save_user_override":
            try:
                from .models import TimbriUserPermOverride
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user_id = int(request.POST.get("user_id") or 0)
                target_user = User.objects.filter(pk=user_id).first()
                if not target_user:
                    messages.error(request, "Utente non trovato.")
                else:
                    for azione in [TimbriUserPermOverride.AZIONE_COPY, TimbriUserPermOverride.AZIONE_DOWNLOAD]:
                        field_key = f"user_perm_{azione}"
                        val = request.POST.get(field_key)
                        if val == "grant":
                            TimbriUserPermOverride.objects.update_or_create(
                                user=target_user, azione=azione, defaults={"granted": True}
                            )
                        elif val == "deny":
                            TimbriUserPermOverride.objects.update_or_create(
                                user=target_user, azione=azione, defaults={"granted": False}
                            )
                        elif val == "remove":
                            TimbriUserPermOverride.objects.filter(user=target_user, azione=azione).delete()
                    log_action(request, "timbri_user_override_save", "timbri", {"target_user": target_user.username})
                    messages.success(request, f"Override utente {target_user.username} aggiornato.")
            except Exception as exc:
                logger.exception("[timbri] salvataggio override utente fallito")
                messages.error(request, f"Errore override utente: {exc}")
            return redirect(f"{reverse('timbri:configurazione')}?tab=permessi")

        if action == "delete_user_override":
            try:
                from .models import TimbriUserPermOverride
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user_id = int(request.POST.get("user_id") or 0)
                target_user = User.objects.filter(pk=user_id).first()
                if target_user:
                    deleted, _ = TimbriUserPermOverride.objects.filter(user=target_user).delete()
                    log_action(request, "timbri_user_override_delete", "timbri", {"target_user": target_user.username, "deleted": deleted})
                    messages.success(request, f"Override per {target_user.username} rimosso.")
            except Exception as exc:
                logger.exception("[timbri] eliminazione override utente fallita")
                messages.error(request, f"Errore rimozione override: {exc}")
            return redirect(f"{reverse('timbri:configurazione')}?tab=permessi")

        if action == "cleanup_orphans":
            if schema_issue:
                messages.error(request, schema_issue)
                return redirect(redirect_url)
            try:
                result = cleanup_orphan_operatori()
                messages.success(
                    request,
                    "Bonifica completata. "
                    f"Orfani={result['orphans']} "
                    f"Riallineati={result['relinked_operatori']} "
                    f"Record spostati={result['records_relinked']} "
                    f"Vuoti eliminati={result['deleted_empty']} "
                    f"Non agganciati con record={result['unmatched_with_records']}",
                )
                log_action(request, "timbri_cleanup_orphans", "timbri", result)
            except Exception as exc:
                logger.exception("[timbri] bonifica orfani fallita")
                messages.error(request, f"Bonifica operatori orfani fallita: {exc}")
            return redirect(redirect_url)

        if action == "reset_table":
            if schema_issue:
                messages.error(request, schema_issue)
                return redirect(redirect_url)
            try:
                result = reset_timbri_table()
                messages.success(
                    request,
                    "Reset tabella completato. "
                    f"Immagini eliminate={result['deleted_images']} "
                    f"Registri eliminati={result['deleted_records']} "
                    f"Operatori eliminati={result['deleted_operatori']} "
                    f"Nominativi reimportati={result['imported_operatori']}",
                )
                log_action(request, "timbri_reset_table", "timbri", result)
            except Exception as exc:
                logger.exception("[timbri] reset tabella fallito")
                messages.error(request, f"Reset tabella timbri fallito: {exc}")
            return redirect(redirect_url)

    log_filter = str(request.GET.get("log_action") or "").strip()
    audit_qs = AuditLog.objects.filter(modulo="timbri").order_by("-created_at")
    if log_filter:
        audit_qs = audit_qs.filter(azione=log_filter)
    audit_entries = list(audit_qs[:200])
    audit_actions = list(
        AuditLog.objects.filter(modulo="timbri")
        .values_list("azione", flat=True)
        .distinct()
        .order_by("azione")
    )
    return render(
        request,
        "timbri/pages/configurazione.html",
        _base_context(
            request,
            current="timbri:configurazione",
            tab=tab,
            audit_entries=audit_entries,
            audit_actions=audit_actions,
            log_filter=log_filter,
            schema_issue=schema_issue,
            local_stats={
                "linked_anagrafica": 0 if schema_issue else OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=False).count(),
                "registri": 0 if schema_issue else RegistroTimbro.objects.count(),
                "orphan_operatori": 0 if schema_issue else OperatoreTimbri.objects.filter(legacy_anagrafica_id__isnull=True).count(),
            },
            **_permessi_timbri_context(),
        ),
    )


class _Echo:
    def write(self, value):
        return value


@login_required
def export_csv(request):
    if not _can_manage_timbri_config(request):
        return _forbidden()
    schema_issue = _timbri_schema_issue()
    if schema_issue:
        return HttpResponse(schema_issue, status=503, content_type="text/plain; charset=utf-8")

    def stream():
        writer = csv.writer(_Echo())
        headers = [
            "operatore",
            "matricola",
            "reparto",
            "ruolo",
            "codice_timbro",
            "qualifica",
            "tipo_timbro",
            "data_consegna",
            "data_ritiro",
            "is_attivo",
            "is_archived",
            "sharepoint_item_id",
            "edited_in_portal",
        ]
        yield writer.writerow(headers)
        qs = RegistroTimbro.objects.select_related("operatore").order_by("operatore__cognome", "operatore__nome", "-created_at")
        for row in qs.iterator():
            yield writer.writerow(
                [
                    row.operatore.full_name,
                    row.operatore.matricola,
                    row.operatore.reparto,
                    row.operatore.ruolo,
                    row.codice_timbro,
                    row.qualifica,
                    row.get_tipo_timbro_display(),
                    row.data_consegna.isoformat() if row.data_consegna else "",
                    row.data_ritiro.isoformat() if row.data_ritiro else "",
                    "1" if row.is_attivo else "0",
                    "1" if row.is_archived else "0",
                    row.sharepoint_item_id,
                    "1" if row.edited_in_portal else "0",
                ]
            )

    log_action(request, "timbri_export_csv", "timbri", {"count": RegistroTimbro.objects.count()})
    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = 'attachment; filename="registro_timbri.csv"'
    return response


@login_required
def serve_timbri_image(request, image_id: int):
    """Serve un'immagine timbro/firma verificando i permessi ACL.
    I file sono in TIMBRI_PRIVATE_ROOT, mai esposta dal web server.
    ?download=1  → forza Content-Disposition attachment (richiede timbri_download).
    Senza parametro → inline (richiede timbri_view).
    """
    as_download = request.GET.get("download") == "1"

    if as_download:
        can_access = _can_download_timbri(request)
        denied_reason = "download_not_allowed"
    else:
        can_access = _can_view_timbri(request)
        denied_reason = "permission_denied"

    if not can_access:
        log_action(
            request,
            "timbri_image_denied",
            "timbri",
            {"image_id": int(image_id), "tipo": "download" if as_download else "view", "motivo": denied_reason},
        )
        return HttpResponseForbidden("Accesso non autorizzato.")

    img = get_object_or_404(RegistroTimbroImmagine, pk=image_id)
    storage = img.image.storage
    if not img.image or not img.image.name or not storage.exists(img.image.name):
        log_action(
            request,
            "timbri_image_not_found",
            "timbri",
            {"image_id": img.id, "registro_id": getattr(img, "registro_id", None)},
        )
        return HttpResponse("Immagine non trovata.", status=404)

    ext = Path(img.image.name).suffix.lower()
    content_type = "image/png" if ext == ".png" else "image/jpeg" if ext in {".jpg", ".jpeg"} else "application/octet-stream"
    log_action(
        request,
        "timbri_image_download" if as_download else "timbri_image_view",
        "timbri",
        {
            "image_id": img.id,
            "registro_id": getattr(img, "registro_id", None),
            "variante": img.variante,
        },
    )
    response = FileResponse(storage.open(img.image.name, "rb"), content_type=content_type)
    if as_download:
        safe_name = img.original_filename or f"timbro_{img.id}{ext}"
        response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return response
