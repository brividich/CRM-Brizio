"""Scadenze amministrative, contratti di assistenza, licenze software.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.legacy_models import AnagraficaDipendente
from ..forms import (
    AssistanceContractForm,
    AssetAdministrativeDeadlineForm,
    SoftwareLicenseForm,
    SoftwareLicenseRenewalForm,
)
from ..models import (
    Asset,
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    AssetAdministrativeDeadlineCompletionAttachment,
    AssetComponent,
    AssetCalendarEvent,
    AssistanceContract,
    SoftwareLicense,
    SoftwareLicenseRenewal,
)
from ..maintenance import (
    contract_state_payload,
)

from ._helpers import (  # noqa: F401
    AUDIT_OGGETTO_ASSET,
    PERIODIC_EXECUTION_WINDOW_DEFAULT,
    _as_int,
    _asset_administrative_deadline_create_page_url,
    _asset_administrative_deadline_page_url,
    _asset_administrative_deadline_state,
    _asset_calendar_default_user_id,
    _asset_calendar_source_key,
    _asset_calendar_transaction_id,
    _asset_component_page_url,
    _assistance_contracts_page_url,
    _build_outlook_event_payload,
    _clean_string,
    _create_asset_calendar_event_record,
    _is_assets_admin,
    _legacy_employee_options,
    _outlook_calendar_graph_ready,
    _parse_execution_cost_input,
    _periodic_execution_window_cutoff,
    _software_license_state_payload,
    _software_licenses_page_url,
)
from ._helpers_b import (  # noqa: F401
    _periodic_verifications_page_url,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _validate_workorder_attachment_uploads,
)

def _contract_scope_payload(contract: AssistanceContract) -> dict[str, str]:
    if contract.asset_id and contract.asset:
        return {
            "label": "Asset",
            "detail": f"{contract.asset.asset_tag} - {contract.asset.name}",
            "badge_class": "info",
        }
    if contract.asset_category_id and contract.asset_category:
        return {
            "label": "Categoria",
            "detail": f"Categoria {contract.asset_category.label}",
            "badge_class": "info",
        }
    return {
        "label": "Generale",
        "detail": "Copertura trasversale",
        "badge_class": "muted",
    }


def _anagrafica_employee_options() -> tuple[list[tuple[str, str]], dict[str, dict[str, str]]]:
    try:
        rows = list(
            AnagraficaDipendente.objects.all()
            .values(
                "id",
                "nome",
                "cognome",
                "aliasusername",
                "reparto",
                "email",
                "email_notifica",
                "utente_id",
            )
        )
    except DatabaseError:
        return [], {}

    options: list[tuple[str, str]] = []
    details: dict[str, dict[str, str]] = {}
    for row in rows:
        anagrafica_id = int(row.get("id") or 0)
        if anagrafica_id <= 0:
            continue
        nome = _clean_string(row.get("nome"))
        cognome = _clean_string(row.get("cognome"))
        alias = _clean_string(row.get("aliasusername"))
        display_name = " ".join([value for value in [cognome, nome] if value]).strip() or alias
        email = _clean_string(row.get("email"))
        notification_email = _clean_string(row.get("email_notifica"))
        label_email = notification_email or email
        label = f"{display_name} - {label_email}" if label_email else display_name or f"Dipendente #{anagrafica_id}"
        options.append((str(anagrafica_id), label))
        details[str(anagrafica_id)] = {
            "display_name": display_name or f"Dipendente #{anagrafica_id}",
            "email": email,
            "notification_email": notification_email,
            "reparto": _clean_string(row.get("reparto")),
            "legacy_user_id": str(row.get("utente_id") or "").strip(),
        }
    options.sort(key=lambda item: item[1].casefold())
    return options, details


def _deadline_completion_rows(
    *,
    deadline_id: int,
    cutoff_date: "date | None" = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    qs = (
        AssetAdministrativeDeadlineCompletion.objects.select_related("completed_by")
        .prefetch_related("attachments")
        .filter(deadline_id=int(deadline_id))
    )
    if cutoff_date is not None:
        qs = qs.filter(completed_on__gte=cutoff_date)
    qs = qs.order_by("-completed_on", "-id")[: max(1, int(limit))]
    rows: list[dict[str, object]] = []
    for completion in qs:
        attachment_rows: list[dict[str, object]] = []
        for attachment in completion.attachments.all():
            attachment_rows.append(
                {
                    "id": attachment.id,
                    "name": attachment.original_name or Path(attachment.file.name).name,
                    "url": reverse("assets:admin_deadline_attachment_download", args=[attachment.id]),
                }
            )
        rows.append(
            {
                "completion": completion,
                "completed_on": completion.completed_on,
                "completed_by": completion.completed_by,
                "completed_by_label": (
                    completion.completed_by.get_full_name() or completion.completed_by.username
                    if completion.completed_by_id
                    else ""
                ),
                "duration_minutes": completion.duration_minutes,
                "cost_eur": completion.cost_eur,
                "notes": completion.notes,
                "next_due_date": completion.next_due_date,
                "attachment_rows": attachment_rows,
            }
        )
    return rows


def _deadline_list_redirect_from_request(request: HttpRequest) -> str:
    url = _asset_administrative_deadline_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        component_id=_as_int(request.POST.get("filter_component"), default=0),
        deadline_type=_clean_string(request.POST.get("filter_deadline_type")),
        status=_clean_string(request.POST.get("filter_status")),
        q=_clean_string(request.POST.get("filter_q")),
    )
    # Famiglia e mese della vista da cui si e' registrato.
    extra = []
    category_id = _as_int(request.POST.get("filter_category"), default=0)
    if category_id:
        extra.append(f"category={category_id}")
    month = _clean_string(request.POST.get("filter_month"))
    if month == "overdue" or re.fullmatch(r"\d{4}-\d{2}", month or ""):
        extra.append(f"month={month}")
    if not extra:
        return url
    return f"{url}{'&' if '?' in url else '?'}{'&'.join(extra)}"


def _assistance_contract_redirect_from_request(request: HttpRequest) -> str:
    return _assistance_contracts_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        supplier_filter=_as_int(request.POST.get("filter_supplier"), default=0),
        state=_clean_string(request.POST.get("filter_state")),
        scope=_clean_string(request.POST.get("filter_scope")),
        q=_clean_string(request.POST.get("filter_q")),
    )


def _build_deadline_outlook_event_payload(
    *,
    request: HttpRequest,
    deadline: AssetAdministrativeDeadline,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    asset = deadline.asset
    component_label = (
        f"{deadline.component.name} ({deadline.component.code})"
        if deadline.component_id and deadline.component and deadline.component.code
        else getattr(deadline.component, "name", "")
    )
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    edit_url = request.build_absolute_uri(reverse("assets:asset_administrative_deadline_edit", kwargs={"id": deadline.id}))
    body_html = (
        "<p>Promemoria scadenza amministrativa/tecnica generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Scadenza:</strong> {escape(deadline.title)}<br>"
        f"<strong>Tipo:</strong> {escape(deadline.get_deadline_type_display())}<br>"
        f"<strong>Data:</strong> {deadline.due_date:%d-%m-%Y}<br>"
        f"<strong>Preavviso:</strong> {int(deadline.warning_days or 0)} gg<br>"
        f"<strong>Riferimento:</strong> {escape(_clean_string(deadline.reference_code) or '-')}<br>"
        f"<strong>Ente/Rilasciato da:</strong> {escape(_clean_string(deadline.issuer) or '-')}<br>"
        f"<strong>Componente:</strong> {escape(_clean_string(component_label) or '-')}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(edit_url)}\">Apri scadenza amministrativa</a></p>"
    )
    subject = f"Scadenza {asset.asset_tag} - {deadline.title}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Scadenza asset",
        due_date=deadline.due_date,
        transaction_id=transaction_id,
    )


def _build_assistance_contract_outlook_event_payload(
    *,
    request: HttpRequest,
    asset: Asset,
    contract: AssistanceContract,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    if not isinstance(contract.end_date, date):
        raise RuntimeError("Il contratto selezionato non ha una data scadenza calendarizzabile.")
    supplier_label = _clean_string(str(getattr(contract, "supplier", "") or "")) or "Fornitore non impostato"
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    contracts_url = request.build_absolute_uri(_assistance_contracts_page_url(asset_id=asset.id, edit_id=contract.id))
    scope_payload = _contract_scope_payload(contract)
    body_html = (
        "<p>Promemoria scadenza contratto assistenza generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset di contesto:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Contratto:</strong> {escape(contract.title)}<br>"
        f"<strong>Fornitore:</strong> {escape(supplier_label)}<br>"
        f"<strong>Codice:</strong> {escape(_clean_string(contract.code) or '-')}<br>"
        f"<strong>Scadenza:</strong> {contract.end_date:%d-%m-%Y}<br>"
        f"<strong>Ambito:</strong> {escape(scope_payload.get('label') or '-')}<br>"
        f"<strong>Dettaglio:</strong> {escape(scope_payload.get('detail') or '-')}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(contracts_url)}\">Apri contratti assistenza</a></p>"
    )
    subject = f"Scadenza contratto {asset.asset_tag} - {contract.title}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Contratto assistenza",
        due_date=contract.end_date,
        transaction_id=transaction_id,
    )


def _create_asset_deadline_calendar_event(
    *,
    request: HttpRequest,
    deadline: AssetAdministrativeDeadline,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    due_date = deadline.due_date
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
        asset_id=deadline.asset_id,
        source_id=deadline.id,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_deadline_outlook_event_payload(
        request=request,
        deadline=deadline,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=deadline.asset,
        event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
        source_key=source_key,
        due_date=due_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        administrative_deadline=deadline,
    )


def _create_asset_assistance_contract_calendar_event(
    *,
    request: HttpRequest,
    asset: Asset,
    contract: AssistanceContract,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    if not isinstance(contract.end_date, date):
        raise RuntimeError("Il contratto selezionato non ha una data scadenza impostata.")
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
        asset_id=asset.id,
        source_id=contract.id,
        due_date=contract.end_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_assistance_contract_outlook_event_payload(
        request=request,
        asset=asset,
        contract=contract,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=asset,
        event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
        source_key=source_key,
        due_date=contract.end_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        assistance_contract=contract,
    )


_DEADLINE_STATUS_TABS = (
    ("todo", "Da gestire"),
    ("next90", "Prossimi 90 giorni"),
    ("active", "Tutte attive"),
    ("inactive", "Chiuse"),
)
_DEADLINE_STATUS_FILTERS = {key for key, _label in _DEADLINE_STATUS_TABS} | {"all", "overdue", "warning", "upcoming"}
_MONTH_SHORT = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_MONTH_LONG = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
               "settembre", "ottobre", "novembre", "dicembre")


def _deadline_row_matches(row: dict, status_filter: str, today: date) -> bool:
    """Una riga dell'elenco scadenze amministrative rientra nella scheda scelta?"""
    status = row["state"]["status"]
    deadline = row["deadline"]
    if status_filter == "all":
        return True
    if status_filter == "active":
        return deadline.is_active
    if status_filter == "todo":
        return status in {"overdue", "warning"}
    if status_filter == "next90":
        return deadline.is_active and today <= deadline.due_date <= today + timedelta(days=90)
    return status == status_filter


def _deadline_month_strip(rows: list[dict], *, today: date) -> list[dict]:
    """Scadute + i prossimi 12 mesi: quante scadenze attive per mese."""
    counts: dict[str, int] = {}
    overdue = 0
    for row in rows:
        deadline = row["deadline"]
        if not deadline.is_active:
            continue
        if row["state"]["status"] == "overdue":
            overdue += 1
        else:
            key = deadline.due_date.strftime("%Y-%m")
            counts[key] = counts.get(key, 0) + 1
    months = [{"key": "overdue", "label": "Scadute", "label_long": "scadute", "count": overdue, "is_late": True}]
    year, month = today.year, today.month
    for _ in range(12):
        key = f"{year:04d}-{month:02d}"
        months.append({
            "key": key,
            "label": f"{_MONTH_SHORT[month - 1]} {str(year)[2:]}",
            "label_long": f"{_MONTH_LONG[month - 1]} {year}",
            "count": counts.get(key, 0),
            "is_late": False,
        })
        month += 1
        if month > 12:
            year, month = year + 1, 1
    peak = max((m["count"] for m in months), default=0)
    for m in months:
        m["pct"] = round(100 * m["count"] / peak) if peak else 0
    return months


def _group_deadline_series(rows: list[dict]) -> list[dict]:
    """Stesso asset, componente e titolo = una serie: resta la prima data (le righe
    sono gia' in ordine di scadenza), le altre finiscono in ``row["series"]``."""
    grouped: list[dict] = []
    by_key: dict[tuple, dict] = {}
    for row in rows:
        deadline = row["deadline"]
        key = (deadline.asset_id, deadline.component_id, (deadline.title or "").strip().lower(), deadline.is_active)
        lead = by_key.get(key)
        if lead is None:
            row["series"] = []
            by_key[key] = row
            grouped.append(row)
        else:
            lead["series"].append(row)
    return grouped


def _deadline_category_choices() -> list[tuple[str, str]]:
    from ..forms_maintenance import category_filter_choices

    return category_filter_choices()


@login_required
def asset_administrative_deadline_list(request: HttpRequest) -> HttpResponse:
    can_manage_outlook_calendar = _is_assets_admin(request)
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _deadline_list_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)

            deadline_id = _as_int(request.POST.get("deadline_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            deadline = (
                AssetAdministrativeDeadline.objects.select_related("asset", "component")
                .filter(pk=deadline_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if deadline is None:
                messages.error(request, "Scadenza amministrativa non trovata.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_deadline_calendar_event(
                    request=request,
                    deadline=deadline,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_deadline_calendar_event",
                        "assets",
                        {
                            "deadline_id": deadline.id,
                            "asset_id": deadline.asset_id,
                            "component_id": deadline.component_id,
                            "due_date": str(deadline.due_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                        oggetto_tipo=AUDIT_OGGETTO_ASSET,
                        oggetto_id=deadline.asset_id,
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d-%m-%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

        if action == "complete_administrative_deadline":
            redirect_url = _deadline_list_redirect_from_request(request)
            if not _is_assets_admin(request):
                messages.error(request, "Solo admin puo completare scadenze amministrative.")
                return redirect(redirect_url)
            deadline_id = _as_int(request.POST.get("deadline_id"), default=0)
            deadline = (
                AssetAdministrativeDeadline.objects.select_related("asset", "component")
                .filter(pk=deadline_id)
                .first()
            )
            if deadline is None:
                messages.error(request, "Scadenza amministrativa non trovata.")
                return redirect(redirect_url)
            today_local = timezone.localdate()
            executed_on_raw = _clean_string(request.POST.get("execution_date"))
            if executed_on_raw:
                try:
                    completed_on = date.fromisoformat(executed_on_raw)
                except ValueError:
                    messages.error(request, "Data di completamento non valida.")
                    return redirect(redirect_url)
            else:
                completed_on = today_local
            if completed_on > today_local:
                messages.error(request, "La data di completamento non puo essere futura.")
                return redirect(redirect_url)
            next_due_raw = _clean_string(request.POST.get("execution_next_due"))
            next_due_date = None
            if next_due_raw:
                try:
                    next_due_date = date.fromisoformat(next_due_raw)
                except ValueError:
                    messages.error(request, "Prossima scadenza non valida.")
                    return redirect(redirect_url)
                if next_due_date < completed_on:
                    messages.error(request, "La prossima scadenza non puo precedere la data di completamento.")
                    return redirect(redirect_url)
            duration_minutes = max(0, _as_int(request.POST.get("execution_duration_minutes"), default=0))
            try:
                cost_value = _parse_execution_cost_input(request.POST.get("execution_cost_eur"))
            except ValueError:
                messages.error(request, "Costo non valido: usa un numero non negativo (es. 120.50).")
                return redirect(redirect_url)
            notes_text = _clean_string(request.POST.get("execution_notes"))
            uploads, upload_errors = _validate_workorder_attachment_uploads(
                request, field_name="completion_files"
            )
            if upload_errors:
                for error in upload_errors:
                    messages.error(request, error)
                return redirect(redirect_url)
            attachments_total = 0
            try:
                with transaction.atomic():
                    completion = AssetAdministrativeDeadlineCompletion.objects.create(
                        deadline=deadline,
                        completed_on=completed_on,
                        completed_by=request.user if request.user.is_authenticated else None,
                        cost_eur=cost_value,
                        duration_minutes=duration_minutes,
                        notes=notes_text,
                        next_due_date=next_due_date,
                    )
                    for upload in uploads:
                        AssetAdministrativeDeadlineCompletionAttachment.objects.create(
                            completion=completion,
                            file=upload,
                            original_name=Path(getattr(upload, "name", "") or "").name[:255],
                            uploaded_by=request.user if request.user.is_authenticated else None,
                        )
                        attachments_total += 1
                    if next_due_date is not None:
                        deadline.due_date = next_due_date
                        deadline.is_active = True
                        deadline.save(update_fields=["due_date", "is_active", "updated_at"])
                    else:
                        deadline.is_active = False
                        deadline.save(update_fields=["is_active", "updated_at"])
            except ValidationError as exc:
                messages.error(request, f"Completamento non registrabile: {exc}")
                return redirect(redirect_url)
            except Exception as exc:
                messages.error(request, f"Errore registrazione completamento: {exc}")
                return redirect(redirect_url)
            log_action(
                request,
                "complete_administrative_deadline",
                "assets",
                {
                    "deadline_id": deadline.id,
                    "asset_id": deadline.asset_id,
                    "completion_id": completion.id,
                    "completed_on": str(completed_on),
                    "next_due_date": str(next_due_date) if next_due_date else None,
                    "cost_eur": str(cost_value) if cost_value is not None else None,
                    "duration_minutes": duration_minutes,
                    "attachments": attachments_total,
                },
                oggetto_tipo=AUDIT_OGGETTO_ASSET,
                oggetto_id=deadline.asset_id,
            )
            attach_suffix = f" ({attachments_total} allegati)" if attachments_total else ""
            if next_due_date is not None:
                messages.success(
                    request,
                    f"Completamento registrato. Nuova scadenza fissata al {next_due_date:%d-%m-%Y}{attach_suffix}.",
                )
            else:
                messages.success(
                    request,
                    f"Completamento registrato il {completed_on:%d-%m-%Y}. Scadenza chiusa{attach_suffix}.",
                )
            return redirect(redirect_url)

    today = timezone.localdate()
    selected_asset_id = _as_int(request.GET.get("asset"), default=0)
    selected_component_id = _as_int(request.GET.get("component"), default=0)
    selected_asset = None
    selected_component = None

    if selected_component_id:
        selected_component = (
            AssetComponent.objects.select_related("asset")
            .filter(pk=selected_component_id)
            .first()
        )
        if selected_component is not None and not selected_asset_id:
            selected_asset_id = selected_component.asset_id
    if selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )
    if selected_component is not None and selected_asset is None:
        selected_asset = selected_component.asset

    q = _clean_string(request.GET.get("q"))
    deadline_type = _clean_string(request.GET.get("deadline_type")).upper()
    valid_deadline_types = {code for code, _label in AssetAdministrativeDeadline.TYPE_CHOICES}
    if deadline_type not in valid_deadline_types:
        deadline_type = ""
    # Schede: "attive" di default (le chiuse sono storia); overdue/warning/upcoming
    # restano accettati per i link esistenti (cockpit, Panoramica).
    status_filter = _clean_string(request.GET.get("status")).lower() or "active"
    if status_filter not in _DEADLINE_STATUS_FILTERS:
        status_filter = "active"
    month_filter = _clean_string(request.GET.get("month"))
    if month_filter != "overdue" and not re.fullmatch(r"\d{4}-\d{2}", month_filter or ""):
        month_filter = ""
    category_id = _as_int(request.GET.get("category"), default=0)

    _DEADLINE_FAMILY_TYPES: dict[str, list[str]] = {
        "it":               ["PC", "NOTEBOOK", "SERVER", "VM", "FIREWALL", "STAMPANTE", "HW", "FONIA"],
        "produzione":       ["CNC", "WORK_MACHINE", "CARROPONTE"],
        "videosorveglianza": ["CCTV"],
        "altro":            ["OTHER"],
    }
    _DEADLINE_FAMILY_LABELS: dict[str, str] = {
        "it": "Asset IT", "produzione": "Produzione",
        "videosorveglianza": "Videosorveglianza", "altro": "Altro",
    }
    family_filter = _clean_string(request.GET.get("family")).lower()
    if family_filter not in _DEADLINE_FAMILY_TYPES:
        family_filter = ""
    family_label = _DEADLINE_FAMILY_LABELS.get(family_filter, "")

    deadline_qs = (
        AssetAdministrativeDeadline.objects.select_related("asset", "component")
        .order_by("due_date", "asset__name", "title", "id")
    )
    if selected_asset is not None:
        deadline_qs = deadline_qs.filter(asset_id=selected_asset.id)
    if selected_component is not None:
        deadline_qs = deadline_qs.filter(component_id=selected_component.id)
    if deadline_type:
        deadline_qs = deadline_qs.filter(deadline_type=deadline_type)
    if family_filter:
        deadline_qs = deadline_qs.filter(asset__asset_type__in=_DEADLINE_FAMILY_TYPES[family_filter])
    if category_id:
        from ..forms_maintenance import category_with_descendants

        deadline_qs = deadline_qs.filter(asset__asset_category_id__in=category_with_descendants(category_id))
    if q:
        deadline_qs = deadline_qs.filter(
            Q(title__icontains=q)
            | Q(reference_code__icontains=q)
            | Q(issuer__icontains=q)
            | Q(notes__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(component__name__icontains=q)
            | Q(component__code__icontains=q)
        )

    deadline_rows_all: list[dict[str, object]] = []
    for deadline in deadline_qs:
        state = _asset_administrative_deadline_state(deadline, today=today)
        deadline_rows_all.append(
            {
                "deadline": deadline,
                "state": state,
                "edit_url": reverse("assets:asset_administrative_deadline_edit", kwargs={"id": deadline.id}),
                "asset_url": reverse("assets:asset_view", kwargs={"id": deadline.asset_id}),
                "component_url": _asset_component_page_url(asset_id=deadline.asset_id),
            }
        )

    calendar_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    deadline_ids = [row["deadline"].id for row in deadline_rows_all]
    if deadline_ids:
        for entry in (
            AssetCalendarEvent.objects.select_related("administrative_deadline")
            .filter(
                event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
                administrative_deadline_id__in=deadline_ids,
            )
            .order_by("target_display_name", "target_email", "created_at", "id")
        ):
            if entry.administrative_deadline_id:
                calendar_event_map[entry.administrative_deadline_id].append(entry)

    status_counts = {key: sum(1 for row in deadline_rows_all if _deadline_row_matches(row, key, today))
                     for key, _label in _DEADLINE_STATUS_TABS}
    deadline_rows = [row for row in deadline_rows_all if _deadline_row_matches(row, status_filter, today)]
    months = _deadline_month_strip(deadline_rows_all, today=today)
    if month_filter == "overdue":
        deadline_rows = [row for row in deadline_rows if row["state"]["status"] == "overdue"]
    elif month_filter:
        deadline_rows = [row for row in deadline_rows if row["deadline"].due_date.strftime("%Y-%m") == month_filter]
    # Una stessa scadenza ripetuta (stesso asset e titolo, date diverse) e' una
    # riga sola: la prima data, le successive nel dettaglio.
    deadline_rows = _group_deadline_series(deadline_rows)

    deadline_completion_cutoff = _periodic_execution_window_cutoff(
        PERIODIC_EXECUTION_WINDOW_DEFAULT, today=today
    )
    for row in deadline_rows:
        deadline = row["deadline"]
        row["calendar_event_rows"] = list(calendar_event_map.get(deadline.id, []))
        row["default_calendar_user_id"] = _asset_calendar_default_user_id(deadline.asset, calendar_user_details)
        row["completion_rows"] = _deadline_completion_rows(
            deadline_id=deadline.id,
            cutoff_date=deadline_completion_cutoff,
            limit=10,
        )
        row["completion_count"] = len(row["completion_rows"])
        row["last_completion"] = row["completion_rows"][0] if row["completion_rows"] else None
        row["tone"] = {"overdue": "tone-red", "warning": "tone-amber", "upcoming": "tone-blue"}.get(
            row["state"]["status"], "tone-grey"
        )

    list_url = reverse("assets:asset_administrative_deadline_list")

    def _tab_url(**changes) -> str:
        query = request.GET.copy()
        query.pop("focus_deadline", None)
        for key, value in changes.items():
            if value:
                query[key] = value
            else:
                query.pop(key, None)
        encoded = query.urlencode()
        return f"{list_url}?{encoded}" if encoded else list_url

    status_tabs = [
        {"key": key, "label": label, "count": status_counts[key], "active": key == status_filter,
         "url": _tab_url(status=key, month="")}
        for key, label in _DEADLINE_STATUS_TABS
    ]
    for month in months:
        month["url"] = _tab_url(status="active", month=month["key"])
        month["active"] = month["key"] == month_filter

    component_options = []
    if selected_asset is not None:
        component_options = list(
            AssetComponent.objects.filter(asset_id=selected_asset.id)
            .order_by("-is_active", "name", "code", "id")
        )
    elif selected_component is not None:
        component_options = [selected_component]

    create_url = _asset_administrative_deadline_create_page_url(
        asset_id=selected_asset.id if selected_asset else 0,
        component_id=selected_component.id if selected_component else 0,
    )

    return render(
        request,
        "assets/pages/asset_admin_deadline_list.html",
        {
            "page_title": "Scadenze amministrative",
            "deadline_rows": deadline_rows,
            "deadline_total": len(deadline_rows),
            "deadline_dates_total": sum(1 + len(row["series"]) for row in deadline_rows),
            "status_tabs": status_tabs,
            "months": months,
            "month_filter": month_filter,
            "month_label": next((m["label_long"] for m in months if m["key"] == month_filter), ""),
            "month_clear_url": _tab_url(month=""),
            "category_id": str(category_id or ""),
            "category_choices": _deadline_category_choices(),
            "due_90_count": status_counts["next90"],
            "deadline_total_all": len(deadline_rows_all),
            "active_deadline_count": sum(1 for row in deadline_rows_all if row["deadline"].is_active),
            "overdue_deadline_count": sum(1 for row in deadline_rows_all if row["state"]["status"] == "overdue"),
            "warning_deadline_count": sum(1 for row in deadline_rows_all if row["state"]["status"] == "warning"),
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            # Solo gli asset che hanno scadenze: l'elenco di tutto l'inventario era inservibile.
            "asset_options": list(
                Asset.objects.filter(administrative_deadlines__isnull=False)
                .only("id", "asset_tag", "name").distinct().order_by("asset_tag", "name", "id")
            ),
            "component_options": component_options,
            "deadline_type_choices": AssetAdministrativeDeadline.TYPE_CHOICES,
            "selected_deadline_type": deadline_type,
            "status_filter": status_filter,
            "q": q,
            "create_url": create_url,
            "clear_filters_url": _asset_administrative_deadline_page_url(),
            "periodic_verification_url": (
                _periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0)
                if selected_asset
                else reverse("assets:periodic_verifications")
            ),
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "can_manage_assets": _is_assets_admin(request),
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            "today_iso": today.isoformat(),
            "family_filter": family_filter,
            "family_label": family_label,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=create_url,
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def asset_administrative_deadline_create(request: HttpRequest) -> HttpResponse:
    selected_asset_id = _as_int(request.GET.get("asset"), default=0)
    selected_component_id = _as_int(request.GET.get("component"), default=0)
    selected_component = None
    selected_asset = None

    if selected_component_id:
        selected_component = (
            AssetComponent.objects.select_related("asset")
            .filter(pk=selected_component_id)
            .first()
        )
        if selected_component is not None and not selected_asset_id:
            selected_asset_id = selected_component.asset_id
    if selected_asset_id:
        selected_asset = (
            Asset.objects.only("id", "asset_tag", "name", "reparto", "asset_type")
            .filter(pk=selected_asset_id)
            .first()
        )
    if selected_component is not None and selected_asset is None:
        selected_asset = selected_component.asset

    if request.method == "POST":
        form = AssetAdministrativeDeadlineForm(
            request.POST,
            locked_asset=selected_asset,
            preselected_component=selected_component,
        )
        if form.is_valid():
            deadline = form.save()
            log_action(
                request,
                "create_asset_deadline",
                "assets",
                {
                    "deadline_id": deadline.id,
                    "asset_id": deadline.asset_id,
                    "component_id": deadline.component_id,
                    "deadline_type": deadline.deadline_type,
                    "due_date": deadline.due_date.isoformat() if deadline.due_date else "",
                },
                oggetto_tipo=AUDIT_OGGETTO_ASSET,
                oggetto_id=deadline.asset_id,
            )
            messages.success(request, "Scadenza salvata correttamente.")
            return redirect(
                _asset_administrative_deadline_page_url(
                    asset_id=deadline.asset_id,
                    component_id=deadline.component_id or 0,
                )
            )
    else:
        initial = {}
        if selected_asset is not None:
            initial["asset"] = selected_asset.id
        if selected_component is not None:
            initial["component"] = selected_component.id
        form = AssetAdministrativeDeadlineForm(
            initial=initial,
            locked_asset=selected_asset,
            preselected_component=selected_component,
        )

    return render(
        request,
        "assets/pages/asset_admin_deadline_form.html",
        {
            "page_title": "Nuova scadenza amministrativa",
            "form": form,
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            "is_edit": False,
            "back_url": _asset_administrative_deadline_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                component_id=selected_component.id if selected_component else 0,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=_asset_administrative_deadline_create_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    component_id=selected_component.id if selected_component else 0,
                ),
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def asset_administrative_deadline_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_administrative_deadline_list")
    deadline = get_object_or_404(
        AssetAdministrativeDeadline.objects.select_related("asset", "component"),
        pk=id,
    )
    selected_asset = deadline.asset
    selected_component = deadline.component

    if request.method == "POST":
        form = AssetAdministrativeDeadlineForm(
            request.POST,
            instance=deadline,
            locked_asset=selected_asset,
        )
        if form.is_valid():
            deadline = form.save()
            log_action(
                request,
                "update_asset_deadline",
                "assets",
                {
                    "deadline_id": deadline.id,
                    "asset_id": deadline.asset_id,
                    "component_id": deadline.component_id,
                    "deadline_type": deadline.deadline_type,
                    "due_date": deadline.due_date.isoformat() if deadline.due_date else "",
                },
                oggetto_tipo=AUDIT_OGGETTO_ASSET,
                oggetto_id=deadline.asset_id,
            )
            messages.success(request, "Scadenza aggiornata.")
            return redirect(
                _asset_administrative_deadline_page_url(
                    asset_id=deadline.asset_id,
                    component_id=deadline.component_id or 0,
                )
            )
    else:
        form = AssetAdministrativeDeadlineForm(instance=deadline, locked_asset=selected_asset)

    return render(
        request,
        "assets/pages/asset_admin_deadline_form.html",
        {
            "page_title": f"Modifica scadenza {deadline.title}",
            "form": form,
            "deadline": deadline,
            "selected_asset": selected_asset,
            "selected_component": selected_component,
            "is_edit": True,
            "back_url": _asset_administrative_deadline_page_url(
                asset_id=selected_asset.id,
                component_id=selected_component.id if selected_component else 0,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:asset_administrative_deadline_list"),
                new_url=_asset_administrative_deadline_create_page_url(asset_id=selected_asset.id),
                new_label="+ Nuova scadenza",
                search_placeholder="Ricerca rapida per scadenza, riferimento, asset o componente",
            ),
        },
    )


@login_required
def assistance_contract_list(request: HttpRequest) -> HttpResponse:
    from anagrafica.models import Fornitore

    today = timezone.localdate()
    can_manage_contracts = _is_assets_admin(request)
    can_manage_outlook_calendar = can_manage_contracts
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    supplier_filter = _as_int(request.GET.get("supplier"), default=0)
    state_filter = _clean_string(request.GET.get("state")) or "all"
    scope_filter = _clean_string(request.GET.get("scope")) or "all"
    q = _clean_string(request.GET.get("q"))
    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.select_related("asset_category").filter(pk=selected_asset_id).first()

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_contract = None
    if edit_id:
        edit_contract = (
            AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document")
            .filter(pk=edit_id)
            .first()
        )

    form = AssistanceContractForm(
        instance=edit_contract,
        locked_asset=selected_asset if selected_asset is not None and edit_contract is None else None,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _assistance_contract_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)
            if selected_asset is None:
                messages.error(
                    request,
                    "Per i contratti assistenza seleziona prima un asset: l'evento Outlook viene creato sul contesto asset.",
                )
                return redirect(redirect_url)

            contract_id = _as_int(request.POST.get("contract_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            contract = (
                AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document")
                .filter(pk=contract_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if contract is None:
                messages.error(request, "Contratto assistenza non trovato.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)
            if not contract.applies_to_asset(selected_asset):
                messages.error(request, "Il contratto selezionato non si applica all'asset attualmente filtrato.")
                return redirect(redirect_url)
            if not isinstance(contract.end_date, date):
                messages.error(request, "Questo contratto non ha una scadenza calendarizzabile.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_assistance_contract_calendar_event(
                    request=request,
                    asset=selected_asset,
                    contract=contract,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_assistance_contract_calendar_event",
                        "assets",
                        {
                            "contract_id": contract.id,
                            "asset_id": selected_asset.id,
                            "due_date": str(contract.end_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d-%m-%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

        if action in {"create_assistance_contract", "update_assistance_contract", "delete_assistance_contract"} and not can_manage_contracts:
            messages.error(request, "Solo admin puo gestire i contratti assistenza.")
            return redirect(
                _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                )
            )

        if action in {"create_assistance_contract", "update_assistance_contract"}:
            instance = edit_contract if action == "update_assistance_contract" else None
            form = AssistanceContractForm(
                request.POST,
                instance=instance,
                locked_asset=selected_asset if selected_asset is not None and instance is None else None,
            )
            if form.is_valid():
                contract = form.save()
                log_action(
                    request,
                    "update_assistance_contract" if instance is not None else "create_assistance_contract",
                    "assets",
                    {
                        "contract_id": contract.id,
                        "supplier_id": contract.supplier_id,
                        "asset_id": contract.asset_id,
                        "asset_category_id": contract.asset_category_id,
                    },
                )
                messages.success(
                    request,
                    "Contratto assistenza aggiornato." if instance is not None else "Contratto assistenza creato.",
                )
                return redirect(
                    _assistance_contracts_page_url(
                        asset_id=selected_asset.id if selected_asset else 0,
                        supplier_filter=supplier_filter,
                        state=state_filter,
                        scope=scope_filter,
                        q=q,
                    )
                )
        elif action == "delete_assistance_contract":
            contract = AssistanceContract.objects.filter(
                pk=_as_int(request.POST.get("contract_id"), default=0)
            ).first()
            if contract is None:
                messages.error(request, "Contratto assistenza non trovato.")
            else:
                log_action(
                    request,
                    "delete_assistance_contract",
                    "assets",
                    {
                        "contract_id": contract.id,
                        "supplier_id": contract.supplier_id,
                    },
                )
                contract.delete()
                messages.success(request, "Contratto assistenza eliminato.")
            return redirect(
                _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                )
            )

    contract_rows: list[dict[str, object]] = []
    contract_qs = AssistanceContract.objects.select_related("supplier", "asset", "asset_category", "document").order_by(
        "-is_active",
        "end_date",
        "supplier__ragione_sociale",
        "title",
        "id",
    )
    if supplier_filter:
        contract_qs = contract_qs.filter(supplier_id=supplier_filter)
    if q:
        contract_qs = contract_qs.filter(
            Q(title__icontains=q)
            | Q(code__icontains=q)
            | Q(supplier__ragione_sociale__icontains=q)
            | Q(coverage_summary__icontains=q)
        )

    for contract in contract_qs:
        state = contract_state_payload(contract, today=today)
        scope = "asset" if contract.asset_id else "category" if contract.asset_category_id else "global"
        if selected_asset is not None and not contract.applies_to_asset(selected_asset):
            continue
        if state_filter != "all" and state["status"] != state_filter:
            continue
        if scope_filter != "all" and scope != scope_filter:
            continue
        scope_payload = _contract_scope_payload(contract)
        contract_rows.append(
            {
                "contract": contract,
                "state": state,
                "scope": scope,
                "scope_payload": scope_payload,
                "edit_url": _assistance_contracts_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    edit_id=contract.id,
                    supplier_filter=supplier_filter,
                    state=state_filter,
                    scope=scope_filter,
                    q=q,
                ),
                "supplier_url": reverse("fornitori:fornitore_detail", kwargs={"fornitore_id": contract.supplier_id}),
                "asset_url": (
                    reverse("assets:asset_view", kwargs={"id": contract.asset_id})
                    if contract.asset_id
                    else ""
                ),
            }
        )

    contract_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    if selected_asset is not None and contract_rows:
        contract_ids = [row["contract"].id for row in contract_rows if isinstance(row["contract"].end_date, date)]
        if contract_ids:
            for entry in (
                AssetCalendarEvent.objects.select_related("assistance_contract")
                .filter(
                    event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
                    asset_id=selected_asset.id,
                    assistance_contract_id__in=contract_ids,
                )
                .order_by("target_display_name", "target_email", "created_at", "id")
            ):
                if entry.assistance_contract_id:
                    contract_event_map[entry.assistance_contract_id].append(entry)

    default_calendar_user_id = _asset_calendar_default_user_id(selected_asset, calendar_user_details)
    for row in contract_rows:
        contract = row["contract"]
        row["can_create_calendar_event"] = bool(
            selected_asset is not None
            and isinstance(contract.end_date, date)
            and contract.applies_to_asset(selected_asset)
        )
        row["calendar_event_rows"] = list(contract_event_map.get(contract.id, []))
        row["default_calendar_user_id"] = default_calendar_user_id

    periodic_cost_total = Decimal("0")
    for row in contract_rows:
        if row["state"]["status"] in {"active", "expiring"} and row["contract"].periodic_cost_eur is not None:
            periodic_cost_total += row["contract"].periodic_cost_eur

    return render(
        request,
        "assets/pages/assistance_contract_list.html",
        {
            "page_title": "Contratti assistenza",
            "form": form,
            "contract_rows": contract_rows,
            "contract_total": len(contract_rows),
            "active_count": sum(1 for row in contract_rows if row["state"]["status"] == "active"),
            "expiring_count": sum(1 for row in contract_rows if row["state"]["status"] == "expiring"),
            "expired_count": sum(1 for row in contract_rows if row["state"]["status"] == "expired"),
            "periodic_cost_total": periodic_cost_total,
            "can_manage_contracts": can_manage_contracts,
            "is_edit": edit_contract is not None,
            "edit_contract": edit_contract,
            "selected_asset": selected_asset,
            "supplier_filter": supplier_filter,
            "state_filter": state_filter,
            "scope_filter": scope_filter,
            "q": q,
            "supplier_options": Fornitore.objects.filter(is_active=True).order_by("ragione_sociale", "id"),
            "state_choices": [
                ("all", "Tutti"),
                ("active", "Attivi"),
                ("expiring", "In scadenza"),
                ("expired", "Scaduti"),
                ("inactive", "Disattivi"),
                ("scheduled", "Non ancora attivi"),
            ],
            "scope_choices": [
                ("all", "Tutti"),
                ("global", "Generali"),
                ("category", "Per categoria"),
                ("asset", "Per asset"),
            ],
            "clear_filters_url": _assistance_contracts_page_url(asset_id=selected_asset.id if selected_asset else 0),
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_assistance_contracts_page_url(asset_id=selected_asset.id if selected_asset else 0),
                search_placeholder="Ricerca contratti per fornitore, codice o copertura",
            ),
        },
        )


def _active_supplier_options() -> list:
    """Fornitori attivi per il menu del rinnovo licenza (una sola query per tutta la pagina)."""
    from anagrafica.models import Fornitore

    try:
        return list(Fornitore.objects.filter(is_active=True).order_by("ragione_sociale", "id"))
    except DatabaseError:
        return []


@login_required
def software_license_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    can_manage_licenses = _is_assets_admin(request)

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    selected_anagrafica_id = _as_int(request.POST.get("anagrafica_id") or request.GET.get("anagrafica"), default=0)
    category_filter = _clean_string(request.GET.get("category")) or "all"
    status_filter = _clean_string(request.GET.get("status")) or "all"
    assignee_filter = _clean_string(request.GET.get("assignee")) or "all"
    q = _clean_string(request.GET.get("q"))

    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.select_related("asset_category").filter(pk=selected_asset_id).first()

    employee_choices, employee_details = _anagrafica_employee_options()
    selected_employee = None
    if selected_anagrafica_id:
        selected_employee = employee_details.get(str(selected_anagrafica_id))
        if selected_employee is None:
            try:
                row = (
                    AnagraficaDipendente.objects.filter(pk=selected_anagrafica_id)
                    .values(
                        "id",
                        "nome",
                        "cognome",
                        "aliasusername",
                        "reparto",
                        "email",
                        "email_notifica",
                        "utente_id",
                    )
                    .first()
                )
            except DatabaseError:
                row = None
            if row:
                display_name = " ".join(
                    [value for value in [_clean_string(row.get("cognome")), _clean_string(row.get("nome"))] if value]
                ).strip() or _clean_string(row.get("aliasusername")) or f"Dipendente #{selected_anagrafica_id}"
                selected_employee = {
                    "display_name": display_name,
                    "email": _clean_string(row.get("email")),
                    "notification_email": _clean_string(row.get("email_notifica")),
                    "reparto": _clean_string(row.get("reparto")),
                    "legacy_user_id": str(row.get("utente_id") or "").strip(),
                }
                if str(selected_anagrafica_id) not in employee_details:
                    employee_details[str(selected_anagrafica_id)] = dict(selected_employee)
                    employee_choices.append((str(selected_anagrafica_id), display_name))

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_license = None
    if edit_id:
        edit_license = (
            SoftwareLicense.objects.select_related("asset")
            .filter(pk=edit_id)
            .first()
        )

    form = SoftwareLicenseForm(
        instance=edit_license,
        locked_asset=selected_asset if selected_asset is not None and edit_license is None else None,
        locked_employee_id=str(selected_anagrafica_id) if selected_anagrafica_id and edit_license is None else "",
        employee_choices=employee_choices,
        employee_details=employee_details,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action in {
            "create_software_license",
            "update_software_license",
            "delete_software_license",
            "renew_software_license",
            "link_software_inventory",
        } and not can_manage_licenses:
            messages.error(request, "Solo admin puo gestire le licenze software.")
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )

        if action in {"create_software_license", "update_software_license"}:
            instance = edit_license if action == "update_software_license" else None
            form = SoftwareLicenseForm(
                request.POST,
                instance=instance,
                locked_asset=selected_asset if selected_asset is not None and instance is None else None,
                locked_employee_id=str(selected_anagrafica_id) if selected_anagrafica_id and instance is None else "",
                employee_choices=employee_choices,
                employee_details=employee_details,
            )
            # La scadenza va letta prima di is_valid(): il ModelForm scrive i nuovi valori sull'istanza.
            previous_expiry = instance.expiry_date if instance is not None else None
            if form.is_valid():
                auto_renewal = None
                with transaction.atomic():
                    license_row = form.save()
                    if instance is not None and license_row.expiry_date != previous_expiry:
                        # Storico automatico: anche un cambio di scadenza dalla scheda resta tracciato.
                        auto_renewal = SoftwareLicenseRenewal.objects.create(
                            license=license_row,
                            renewed_on=today,
                            period_end=license_row.expiry_date,
                            previous_expiry=previous_expiry,
                            notes="Scadenza modificata dalla scheda licenza",
                            created_by=request.user if request.user.is_authenticated else None,
                        )
                log_action(
                    request,
                    "update_software_license" if instance is not None else "create_software_license",
                    "assets",
                    {
                        "license_id": license_row.id,
                        "asset_id": license_row.asset_id,
                        "assigned_anagrafica_id": license_row.assigned_anagrafica_id,
                        "assigned_legacy_user_id": license_row.assigned_legacy_user_id,
                        "renewal_id": auto_renewal.id if auto_renewal is not None else None,
                    },
                )
                messages.success(
                    request,
                    "Licenza software aggiornata." if instance is not None else "Licenza software creata.",
                )
                return redirect(
                    _software_licenses_page_url(
                        asset_id=selected_asset.id if selected_asset else 0,
                        anagrafica_id=selected_anagrafica_id,
                        category=category_filter,
                        status=status_filter,
                        assignee=assignee_filter,
                        q=q,
                    )
                )
        elif action == "renew_software_license":
            license_row = SoftwareLicense.objects.filter(
                pk=_as_int(request.POST.get("license_id"), default=0)
            ).first()
            if license_row is None:
                messages.error(request, "Licenza software non trovata.")
            else:
                renewal_form = SoftwareLicenseRenewalForm(request.POST, prefix=f"renew-{license_row.id}")
                if renewal_form.is_valid():
                    data = renewal_form.cleaned_data
                    with transaction.atomic():
                        renewal = renewal_form.save(commit=False)
                        renewal.license = license_row
                        renewal.renewed_on = data["renewed_on"]
                        renewal.previous_expiry = license_row.expiry_date
                        renewal.created_by = request.user if request.user.is_authenticated else None
                        renewal.save()
                        license_row.expiry_date = data["period_end"]
                        license_row.renewal_date = data["renewed_on"]
                        if data.get("seats_total") is not None:
                            license_row.seats_total = data["seats_total"]
                        license_row.is_active = True
                        license_row.save(
                            update_fields=["expiry_date", "renewal_date", "seats_total", "is_active", "updated_at"]
                        )
                    log_action(
                        request,
                        "renew_software_license",
                        "assets",
                        {
                            "license_id": license_row.id,
                            "renewal_id": renewal.id,
                            "previous_expiry": str(renewal.previous_expiry or ""),
                            "new_expiry": str(renewal.period_end or ""),
                        },
                    )
                    messages.success(
                        request,
                        f"Licenza rinnovata: nuova scadenza {renewal.period_end:%d/%m/%Y}.",
                    )
                else:
                    error_text = " ".join(
                        str(error) for errors in renewal_form.errors.values() for error in errors
                    )
                    messages.error(request, f"Rinnovo non salvato. {error_text}".strip())
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )
        elif action == "link_software_inventory":
            from security.services.software_catalog import catalog as _inventory_catalog

            license_row = SoftwareLicense.objects.filter(
                pk=_as_int(request.POST.get("license_id"), default=0)
            ).first()
            key = _clean_string(request.POST.get("inventory_key"))
            if license_row is None or key not in {item["key"] for item in _inventory_catalog()}:
                messages.error(request, "Licenza o prodotto dell'inventario non validi.")
            else:
                license_row.inventory_key = key
                license_row.save(update_fields=["inventory_key", "updated_at"])
                log_action(
                    request,
                    "link_software_inventory",
                    "assets",
                    {"license_id": license_row.id, "inventory_key": key},
                )
                messages.success(request, f"Licenza «{license_row}» collegata al software installato.")
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )
        elif action == "delete_software_license":
            license_row = SoftwareLicense.objects.filter(
                pk=_as_int(request.POST.get("license_id"), default=0)
            ).first()
            if license_row is None:
                messages.error(request, "Licenza software non trovata.")
            else:
                log_action(
                    request,
                    "delete_software_license",
                    "assets",
                    {
                        "license_id": license_row.id,
                        "asset_id": license_row.asset_id,
                        "assigned_anagrafica_id": license_row.assigned_anagrafica_id,
                    },
                )
                license_row.delete()
                messages.success(request, "Licenza software eliminata.")
            return redirect(
                _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                )
            )

    license_qs = SoftwareLicense.objects.select_related("asset").prefetch_related(
        Prefetch(
            "renewals",
            queryset=SoftwareLicenseRenewal.objects.select_related("supplier", "created_by").order_by(
                "-renewed_on", "-id"
            ),
        )
    ).order_by(
        "category",
        "vendor",
        "product_name",
        "id",
    )
    if selected_asset is not None:
        license_qs = license_qs.filter(asset_id=selected_asset.id)
    if selected_anagrafica_id:
        legacy_user_id = 0
        if selected_employee is not None:
            try:
                legacy_user_id = int(selected_employee.get("legacy_user_id") or 0)
            except (TypeError, ValueError):
                legacy_user_id = 0
        if legacy_user_id:
            license_qs = license_qs.filter(
                Q(assigned_anagrafica_id=selected_anagrafica_id) | Q(assigned_legacy_user_id=legacy_user_id)
            )
        else:
            license_qs = license_qs.filter(assigned_anagrafica_id=selected_anagrafica_id)
    if category_filter != "all":
        license_qs = license_qs.filter(category=category_filter)
    if assignee_filter == "asset":
        license_qs = license_qs.filter(asset_id__isnull=False)
    elif assignee_filter == "user":
        license_qs = license_qs.filter(assigned_anagrafica_id__isnull=False)
    elif assignee_filter == "unassigned":
        license_qs = license_qs.filter(asset_id__isnull=True, assigned_anagrafica_id__isnull=True)

    if status_filter != "all":
        if status_filter == "inactive":
            license_qs = license_qs.filter(is_active=False)
        else:
            license_qs = license_qs.filter(is_active=True)
            if status_filter == "expired":
                license_qs = license_qs.filter(expiry_date__lt=today)
            elif status_filter == "expiring":
                license_qs = license_qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
            elif status_filter == "active":
                license_qs = license_qs.filter(
                    Q(expiry_date__isnull=True) | Q(expiry_date__gt=today + timedelta(days=30))
                )

    if q:
        license_qs = license_qs.filter(
            Q(product_name__icontains=q)
            | Q(vendor__icontains=q)
            | Q(edition__icontains=q)
            | Q(license_reference__icontains=q)
            | Q(account_email__icontains=q)
            | Q(assigned_to_display__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__name__icontains=q)
        )

    license_rows: list[dict[str, object]] = []
    for license_row in license_qs:
        state = _software_license_state_payload(license_row, today=today)
        renewals = list(license_row.renewals.all())
        renewal_costs = [renewal.cost_eur for renewal in renewals if renewal.cost_eur is not None]
        license_rows.append(
            {
                "license": license_row,
                "state": state,
                "renewals": renewals,
                "renewal_count": len(renewals),
                "renewal_total_cost": sum(renewal_costs, Decimal("0")) if renewal_costs else None,
                "renew_prefix": f"renew-{license_row.id}",
                "renew_default_start": (
                    license_row.expiry_date + timedelta(days=1) if license_row.expiry_date else None
                ),
                "asset_url": (
                    reverse("assets:asset_view", kwargs={"id": license_row.asset_id})
                    if license_row.asset_id
                    else ""
                ),
                "employee_url": (
                    reverse("anagrafica:dipendente_detail", args=[license_row.assigned_anagrafica_id])
                    if license_row.assigned_anagrafica_id
                    else ""
                ),
                "edit_url": _software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                    edit_id=license_row.id,
                    category=category_filter,
                    status=status_filter,
                    assignee=assignee_filter,
                    q=q,
                ),
            }
        )

    # PC che hanno davvero il software (inventario importato nel SOC), per le licenze collegate.
    try:
        from security.services.software_catalog import hosts_by_key

        installed_counts = hosts_by_key({row["license"].inventory_key for row in license_rows})
    except Exception:  # noqa: BLE001 - l'elenco licenze resta usabile anche senza inventario
        installed_counts = {}
    for row in license_rows:
        lic = row["license"]
        installed = installed_counts.get(lic.inventory_key, 0) if lic.inventory_key else None
        row["installed_on"] = installed
        row["over_seats"] = bool(installed and lic.seats_total and installed > lic.seats_total)
        row["expired_but_installed"] = bool(installed and row["state"]["status"] in {"expired", "inactive"})

    try:
        from assets.services.software_licenze import coverage_report

        coverage = coverage_report(today)
    except Exception:  # noqa: BLE001 - senza inventario l'elenco licenze resta usabile
        coverage = None

    return render(
        request,
        "assets/pages/software_license_list.html",
        {
            "page_title": "Licenze software",
            "coverage": coverage,
            "form": form,
            "license_rows": license_rows,
            "license_total": len(license_rows),
            "active_count": sum(1 for row in license_rows if row["state"]["status"] == "active"),
            "expiring_count": sum(1 for row in license_rows if row["state"]["status"] == "expiring"),
            "expired_count": sum(1 for row in license_rows if row["state"]["status"] == "expired"),
            "inactive_count": sum(1 for row in license_rows if row["state"]["status"] == "inactive"),
            "unassigned_count": sum(
                1
                for row in license_rows
                if row["license"].assignment_scope == "unassigned"
            ),
            "can_manage_licenses": can_manage_licenses,
            "renewal_supplier_options": (
                _active_supplier_options() if can_manage_licenses else []
            ),
            "today": today,
            "is_edit": edit_license is not None,
            "edit_license": edit_license,
            "selected_asset": selected_asset,
            "selected_employee": selected_employee,
            "selected_anagrafica_id": selected_anagrafica_id,
            "category_filter": category_filter,
            "status_filter": status_filter,
            "assignee_filter": assignee_filter,
            "q": q,
            "category_choices": [("all", "Tutte"), *SoftwareLicense.CATEGORY_CHOICES],
            "status_choices": [
                ("all", "Tutte"),
                ("active", "Attive"),
                ("expiring", "In scadenza"),
                ("expired", "Scadute"),
                ("inactive", "Disattive"),
            ],
            "assignee_choices": [
                ("all", "Tutte"),
                ("asset", "Assegnate a asset"),
                ("user", "Assegnate a dipendente"),
                ("unassigned", "Da assegnare"),
            ],
            "clear_filters_url": _software_licenses_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                anagrafica_id=selected_anagrafica_id,
            ),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_software_licenses_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    anagrafica_id=selected_anagrafica_id,
                ),
                search_placeholder="Ricerca per prodotto, vendor, codice o asset",
            ),
        },
    )
