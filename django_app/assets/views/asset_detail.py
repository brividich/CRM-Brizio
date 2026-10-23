"""Scheda asset e layout configurabile del dettaglio.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max, ProtectedError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify

from core.acl import user_can_modulo_action
from core.audit import log_action, storico_oggetto

from core.legacy_models import AnagraficaDipendente
from ..models import (
    Asset,
    AssetActionButton,
    AssetAdministrativeDeadlineCompletion,
    AssetCategory,
    AssetCategoryDocumentFolder,
    AssetCustomField,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetEndpoint,
    AssetMaintenanceBudget,
    AssetTimelineEntry,
    AssetTimelineHiddenEvent,
    MaintenanceRule,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
    WorkOrderLog,
)
from ..maintenance import (
    build_day_based_maintenance_schedule_rows,
    contract_state_payload,
    copy_template_checklist_to_workorder,
    get_primary_assistance_contract,
    resolve_asset_maintenance_rules,
)
from ..notifications import notify_workorder_assigned
from ..services.dashboard_kpi import (
    get_asset_maintenance_costs,
)
from ..services import storico_asset
from ..services.ciclo_vita_asset import blocchi_eliminazione
from ..models import AssetFieldHistory

from ._helpers import (  # noqa: F401
    ASSET_DOCUMENT_MAX_BYTES,
    AUDIT_OGGETTO_ASSET,
    DETAIL_FIELD_ACTIONS,
    PERIODIC_EXECUTION_WINDOW_DEFAULT,
    _apply_asset_document_changes,
    _as_int,
    _asset_administrative_deadline_create_page_url,
    _asset_administrative_deadline_page_url,
    _asset_administrative_deadline_state,
    _asset_component_create_page_url,
    _asset_component_page_url,
    _asset_document_folder_specs,
    _asset_maintenance_rule_list_page_url,
    _assistance_contracts_page_url,
    _build_asset_documents_by_category,
    _can_delete_asset,
    _can_retire_asset,
    _clean_string,
    _coalesce_str,
    _ensure_asset_plant_layout_marker,
    _is_assets_admin,
    _maintenance_schedule_page_url,
    _periodic_execution_rows_for_verification,
    _periodic_execution_window_cutoff,
    _periodic_verification_state,
    _resolve_asset_plant_layout,
    _asset_plant_layout_marker,
    _plant_layout_image_size,
    _software_license_state_payload,
    _software_licenses_page_url,
    _ui_choices,
    _validate_asset_document_uploads,
    _workorder_create_page_url,
)
from ._helpers_b import (  # noqa: F401
    _ensure_default_asset_detail_section_layouts,
    _format_asset_detail_value,
    _periodic_verifications_page_url,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _can_edit_asset,
    _handle_asset_category_request,
    _handle_detail_field_request,
    _workorder_attachment_accept_attr,
)
from .asset_detail_helpers import (  # noqa: F401
    DETAIL_LAYOUT_ACTIONS,
    _asset_deadlines_context,
    _asset_document_upload_count,
    _asset_maintenance_plans_context,
    _asset_report_pdf_url,
    _asset_status_payload,
    _asset_ticket_detail_url,
    _asset_timeline_entry_payload,
    _asset_timeline_hidden_keys,
    _asset_timeline_manual_enabled,
    _build_action_buttons_for_asset,
    _build_asset_category_detail_sections,
    _build_asset_detail_section_cards,
    _build_asset_primary_kpis,
    _build_asset_status_band,
    _build_configured_asset_detail_sections,
    _can_manage_asset_detail_layout,
    _can_manage_asset_document_folders,
    _can_manage_asset_timeline_entries,
    _can_manage_ticket_type_for_asset_view,
    _compute_ticket_kpi_for_asset,
    _contextual_maintenance_suggestions,
    _detail_grid_size_class,
    _handle_detail_section_layout_request,
    _is_empty_asset_detail_value,
    _maintenance_schedule_row_for_asset_rule,
    _preferred_asset_detail_metrics,
    _promote_asset_detail_actions,
)

@login_required
def asset_detail_layout_admin(request: HttpRequest) -> HttpResponse:
    if not _can_manage_asset_detail_layout(request):
        messages.error(request, "Non hai i permessi per configurare il layout del dettaglio asset.")
        return redirect("assets:asset_list")

    preview_asset_id = _as_int(request.POST.get("asset_id") if request.method == "POST" else request.GET.get("asset"), default=0)
    preview_asset = (
        Asset.objects.select_related("asset_category")
        .filter(pk=preview_asset_id)
        .first()
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action in DETAIL_LAYOUT_ACTIONS:
            ok, text = _handle_detail_section_layout_request(request)
        elif action in DETAIL_FIELD_ACTIONS:
            ok, text = _handle_detail_field_request(request)
        elif action == "update_asset_category_field":
            ok, text = _handle_asset_category_request(request)
        else:
            ok, text = False, "Azione layout dettaglio non riconosciuta."
        if ok:
            messages.success(request, text)
        else:
            messages.error(request, text)
        redirect_url = reverse("assets:asset_detail_layout_admin")
        if preview_asset_id:
            redirect_url = f"{redirect_url}?asset={preview_asset_id}"
        return redirect(redirect_url)

    section_layouts = _ensure_default_asset_detail_section_layouts()
    detail_fields = list(AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id"))
    asset_categories = list(
        AssetCategory.objects.prefetch_related("category_fields").order_by("sort_order", "label", "id")
    )
    detail_source_help = [
        "asset:manufacturer",
        "asset:model",
        "asset:serial_number",
        "it:cpu",
        "work_machine:x_mm",
        "custom:centro_costo",
        "computed:travel_xyz",
    ]

    return render(
        request,
        "assets/pages/asset_detail_layout_admin.html",
        {
            "page_title": "Configura dettaglio asset",
            "section_layouts": section_layouts,
            "detail_fields": detail_fields,
            "asset_categories": asset_categories,
            "detail_section_choices": _ui_choices(AssetDetailField.SECTION_CHOICES),
            "detail_scope_choices": _ui_choices(AssetDetailField.SCOPE_CHOICES),
            "detail_format_choices": _ui_choices(AssetDetailField.FORMAT_CHOICES),
            "detail_card_size_choices": _ui_choices(AssetDetailField.CARD_SIZE_CHOICES),
            "detail_section_layout_choices": _ui_choices(AssetDetailSectionLayout.SECTION_CHOICES),
            "detail_source_help": detail_source_help,
            "preview_asset": preview_asset,
            "preview_asset_url": reverse("assets:asset_view", kwargs={"id": preview_asset.id}) if preview_asset else "",
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def asset_detail(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:asset_list")
    asset = get_object_or_404(
        Asset.objects.select_related("asset_category", "it_details", "work_machine", "prodotto_chimico", "prodotto_chimico__reparto").prefetch_related(
            "components",
            "administrative_deadlines",
            "administrative_deadlines__component",
            "endpoints",
            "workorders",
            "documents",
            "tickets",
            "periodic_verifications",
            "periodic_verifications__supplier",
            "software_licenses",
        ),
        pk=id,
    )
    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "prepare_planned_maintenance_report":
            base_rule_id = _as_int(request.POST.get("base_rule_id"), default=0)
            schedule_row = _maintenance_schedule_row_for_asset_rule(
                asset=asset,
                base_rule_id=base_rule_id,
            )
            if schedule_row is None:
                messages.error(request, "La manutenzione pianificata selezionata non è disponibile per questo asset.")
                return redirect("assets:asset_view", id=asset.id)

            workorder = None
            created = False
            with transaction.atomic():
                # Serializza il fallback manuale sulla regola: due click ravvicinati
                # devono aprire lo stesso rapporto, non due OdL concorrenti.
                MaintenanceRule.objects.select_for_update().get(pk=base_rule_id)
                workorder = (
                    WorkOrder.objects.filter(
                        asset=asset,
                        maintenance_rule_id=base_rule_id,
                        status=WorkOrder.STATUS_OPEN,
                    )
                    .order_by("opened_at", "id")
                    .first()
                )
                if workorder is None:
                    rule = schedule_row["base_rule"]
                    template = schedule_row["effective_intervention_template"]
                    workorder = WorkOrder(
                        asset=asset,
                        maintenance_rule=rule,
                        origin=WorkOrder.ORIGIN_PERIODIC,
                        kind=getattr(template, "workorder_kind", WorkOrder.KIND_PREVENTIVE),
                        status=WorkOrder.STATUS_OPEN,
                        title=f"{template.label} — {asset.asset_tag}",
                        description=getattr(template, "description", "") or "",
                        assigned_to=rule.assigned_to,
                        supplier=rule.supplier,
                        reference_batch=f"asset-{timezone.localdate():%Y%m%d}",
                    )
                    workorder.full_clean()
                    workorder.save()
                    copied_steps = copy_template_checklist_to_workorder(
                        workorder,
                        template_id=getattr(template, "pk", None),
                    )
                    log_note = "Rapporto di manutenzione pianificata generato dalla scheda asset."
                    if copied_steps:
                        log_note = f"{log_note} Checklist precompilata: {copied_steps} attività."
                    WorkOrderLog.objects.create(
                        work_order=workorder,
                        note=log_note,
                        author=request.user if request.user.is_authenticated else None,
                    )
                    created = True

            if created:
                notify_workorder_assigned(
                    workorder,
                    actor=request.user if request.user.is_authenticated else None,
                )
                messages.success(request, f"Rapporto #{workorder.id} generato: completa i dati e chiudilo.")
            else:
                messages.info(request, f"Il rapporto #{workorder.id} era già aperto: completa i dati e chiudilo.")
            return redirect("assets:wo_close", id=workorder.id)
        if action == "add_asset_timeline_entry":
            if not _can_manage_asset_timeline_entries(request):
                messages.error(request, "Permessi insufficienti per inserire voci nella timeline di vita.")
                return redirect("assets:asset_view", id=asset.id)
            if not _asset_timeline_manual_enabled(asset):
                messages.error(request, "L'inserimento manuale in timeline e' disattivato per questa categoria di asset.")
                return redirect("assets:asset_view", id=asset.id)
            entry_payload, payload_error = _asset_timeline_entry_payload(request)
            if entry_payload is None:
                messages.error(request, payload_error)
            else:
                entry = AssetTimelineEntry.objects.create(
                    asset=asset,
                    created_by=request.user if request.user.is_authenticated else None,
                    **entry_payload,
                )
                log_action(
                    request,
                    "add_asset_timeline_entry",
                    "assets",
                    {
                        "asset_id": asset.id,
                        "entry_id": entry.id,
                        "event_date": entry.event_date.isoformat(),
                        "title": entry.title,
                    },
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
                messages.success(request, f"Voce \"{entry.title}\" aggiunta alla timeline di vita.")
            return redirect("assets:asset_view", id=asset.id)
        if action in {"update_asset_timeline_entry", "delete_asset_timeline_entry"}:
            # Correzione e rimozione non dipendono dal flag di categoria: se
            # l'inserimento manuale viene spento, le voci gia' registrate devono
            # restare sistemabili da chi ha il permesso.
            if not _can_manage_asset_timeline_entries(request):
                messages.error(request, "Permessi insufficienti per gestire le voci della timeline di vita.")
                return redirect("assets:asset_view", id=asset.id)
            entry_id = _as_int(request.POST.get("entry_id"), default=0)
            entry = asset.timeline_entries.filter(pk=entry_id).first() if entry_id > 0 else None
            if entry is None:
                messages.error(request, "Voce di timeline non trovata.")
                return redirect("assets:asset_view", id=asset.id)
            if action == "delete_asset_timeline_entry":
                entry_label = entry.title
                entry.delete()
                log_action(
                    request,
                    "delete_asset_timeline_entry",
                    "assets",
                    {"asset_id": asset.id, "entry_id": entry_id, "title": entry_label},
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
                messages.success(request, f"Voce \"{entry_label}\" rimossa dalla timeline di vita.")
                return redirect("assets:asset_view", id=asset.id)
            entry_payload, payload_error = _asset_timeline_entry_payload(request)
            if entry_payload is None:
                messages.error(request, payload_error)
            else:
                for field_name, field_value in entry_payload.items():
                    setattr(entry, field_name, field_value)
                entry.save(update_fields=[*entry_payload.keys(), "updated_at"])
                log_action(
                    request,
                    "update_asset_timeline_entry",
                    "assets",
                    {
                        "asset_id": asset.id,
                        "entry_id": entry.id,
                        "event_date": entry.event_date.isoformat(),
                        "title": entry.title,
                    },
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
                messages.success(request, f"Voce \"{entry.title}\" aggiornata.")
            return redirect("assets:asset_view", id=asset.id)
        if action == "link_soc_device":
            # Stessa regola della pagina dispositivi SOC: serve il permesso di
            # configurazione del Security Center, e si collega solo un dispositivo
            # che l'abbinatore assegna proprio a questo asset.
            from security.services.asset_signals import link as link_soc_device
            from security.services.configuration import can_manage_security_config
            from security.templatetags.security_asset import unlinked_candidates

            if not can_manage_security_config(request.user):
                messages.error(request, "Serve il permesso di configurazione del Security Center.")
                return redirect("assets:asset_view", id=asset.id)
            device_id = _as_int(request.POST.get("device"), default=0)
            row = next((r for r in unlinked_candidates(asset) if r["device"].pk == device_id), None)
            if row is None:
                messages.error(request, "Dispositivo SOC non più proponibile per questo asset.")
                return redirect("assets:asset_view", id=asset.id)
            link_soc_device(row["device"], asset, actor=request.user, request=request)
            messages.success(request, f"«{row['device'].hostname}» collegato a «{asset.name}».")
            return redirect(f"{reverse('assets:asset_view', args=[asset.id])}#tab-sicurezza")
        if action == "apply_snmp_identity":
            # Il valore deve essere uno di quelli letti via SNMP e mostrati in
            # scheda: niente testo libero dalla POST, e solo per chi puo' modificare l'asset.
            if not _can_edit_asset(request, asset.id):
                messages.error(request, "Permessi insufficienti per modificare l'asset.")
                return redirect("assets:asset_view", id=asset.id)
            from ..services.it_identity_diff import snmp_identity_diffs

            field = _clean_string(request.POST.get("field"))
            value = _clean_string(request.POST.get("value"))
            diff = next((row for row in snmp_identity_diffs(asset) if row["field"] == field and row["snmp_value"] == value), None)
            if diff is None:
                messages.error(request, "Dato SNMP non più disponibile o già allineato.")
                return redirect("assets:asset_view", id=asset.id)
            if field == "ip":
                # L'IP interrogato da Contatori IT diventa un punto rete in piu': quelli esistenti restano.
                endpoint = AssetEndpoint.objects.create(asset=asset, endpoint_name="Monitoraggio SNMP", ip=diff["snmp_value"])
                log_action(
                    request,
                    "apply_snmp_identity",
                    "assets",
                    {"asset_id": asset.id, "field": "ip", "endpoint_id": endpoint.id, "new_value": diff["snmp_value"],
                     "origin": diff["origin"]},
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
                messages.success(request, f"Punto rete «{diff['snmp_value']}» aggiunto dal monitoraggio.")
                return redirect("assets:asset_view", id=asset.id)
            old_value = getattr(asset, field) or ""
            setattr(asset, field, diff["snmp_value"])
            asset.save(update_fields=[field, "updated_at"])
            log_action(
                request,
                "apply_snmp_identity",
                "assets",
                {"asset_id": asset.id, "field": field, "old_value": old_value, "new_value": diff["snmp_value"], "origin": diff["origin"]},
                oggetto_tipo=AUDIT_OGGETTO_ASSET,
                oggetto_id=asset.id,
            )
            messages.success(request, f"{diff['label']} aggiornato dal monitoraggio: «{diff['snmp_value']}».")
            return redirect("assets:asset_view", id=asset.id)
        if action == "hide_asset_timeline_event":
            # Gli eventi automatici non sono righe di database: "eliminarli"
            # significa registrare che su questo asset non vanno piu' mostrati.
            if not _can_manage_asset_timeline_entries(request):
                messages.error(request, "Permessi insufficienti per gestire le voci della timeline di vita.")
                return redirect("assets:asset_view", id=asset.id)
            event_key = _clean_string(request.POST.get("event_key"))[:40]
            event_labels = dict(AssetTimelineHiddenEvent.KEY_CHOICES)
            if event_key not in event_labels:
                messages.error(request, "Voce di timeline non trovata.")
                return redirect("assets:asset_view", id=asset.id)
            _, hidden_created = AssetTimelineHiddenEvent.objects.get_or_create(
                asset=asset,
                event_key=event_key,
                defaults={"hidden_by": request.user if request.user.is_authenticated else None},
            )
            if hidden_created:
                log_action(
                    request,
                    "hide_asset_timeline_event",
                    "assets",
                    {"asset_id": asset.id, "event_key": event_key},
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
            messages.success(request, f"Voce \"{event_labels[event_key]}\" rimossa dalla timeline di vita.")
            return redirect("assets:asset_view", id=asset.id)
        if action in {"retire_asset", "reactivate_asset"}:
            if not _can_retire_asset(request):
                messages.error(request, "Permessi insufficienti per dismettere o riattivare l'asset.")
                return redirect("assets:asset_view", id=asset.id)
            target_status = Asset.STATUS_RETIRED if action == "retire_asset" else Asset.STATUS_IN_USE
            old_status = asset.status
            if old_status != target_status:
                with storico_asset.traccia([asset.id], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                           dettaglio="Dismissione" if action == "retire_asset" else "Riattivazione"):
                    Asset.objects.filter(pk=asset.pk).update(status=target_status, updated_at=timezone.now())
                log_action(
                    request,
                    action,
                    "assets",
                    {"asset_id": asset.id, "old_status": old_status, "new_status": target_status},
                    oggetto_tipo=AUDIT_OGGETTO_ASSET,
                    oggetto_id=asset.id,
                )
            if action == "retire_asset":
                messages.success(request, f"«{asset.name}» dismesso: non compare piu' negli elenchi operativi.")
            else:
                messages.success(request, f"«{asset.name}» riportato in uso.")
            return redirect("assets:asset_view", id=asset.id)
        if action == "delete_asset":
            if not _can_delete_asset(request):
                messages.error(request, "Permessi insufficienti per eliminare l'asset.")
                return redirect("assets:asset_view", id=asset.id)
            blocks = blocchi_eliminazione(asset)
            if blocks:
                messages.error(
                    request,
                    f"«{asset.name}» ha gia' uno storico ({', '.join(blocks)}): non si elimina, usa «Dismetti».",
                )
                return redirect("assets:asset_view", id=asset.id)
            snapshot = {
                "asset_id": asset.id,
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "status": asset.status,
                "serial_number": asset.serial_number,
            }
            try:
                with transaction.atomic():
                    asset.delete()
            except ProtectedError:
                messages.error(request, f"«{snapshot['name']}» e' collegato ad altri moduli: non si elimina, usa «Dismetti».")
                return redirect("assets:asset_view", id=snapshot["asset_id"])
            log_action(
                request,
                "delete_asset",
                "assets",
                snapshot,
                oggetto_tipo=AUDIT_OGGETTO_ASSET,
                oggetto_id=snapshot["asset_id"],
            )
            messages.success(request, f"Asset «{snapshot['name']}» eliminato.")
            return redirect("assets:asset_list")
        if action == "upload_asset_documents":
            # Una cartella con molti file non si perde per un file non ammesso: i
            # validi entrano, gli scartati sono elencati. Il caricamento a lotti della
            # scheda (fetch) chiede JSON e compone lui il riepilogo finale.
            uploads, upload_errors = _validate_asset_document_uploads(request, asset)
            upload_count = _asset_document_upload_count(uploads)
            if upload_count > 0:
                _apply_asset_document_changes(
                    asset,
                    uploads=uploads,
                    remove_ids=set(),
                    actor=request.user,
                )
            if request.headers.get("Accept", "").startswith("application/json"):
                return JsonResponse({"ok": True, "saved": upload_count, "errors": upload_errors})
            if upload_count > 0:
                messages.success(request, f"{upload_count} file caricato/i in archivio.")
            if upload_errors:
                shown = upload_errors[:10]
                more = len(upload_errors) - len(shown)
                messages.error(
                    request,
                    f"{len(upload_errors)} file non caricato/i: " + "; ".join(shown) + (f"; e altri {more}." if more else "."),
                )
            if not upload_errors and upload_count <= 0:
                messages.error(request, "Seleziona almeno un file da caricare.")
            return redirect("assets:asset_view", id=asset.id)
        if action == "delete_asset_document":
            document_id = _as_int(request.POST.get("document_id"), default=0)
            document = asset.documents.filter(id=document_id).first() if document_id > 0 else None
            if document is None:
                messages.error(request, "Documento non trovato.")
            else:
                doc_label = document.original_name or Path(document.file.name).name
                doc_category = document.category
                _apply_asset_document_changes(
                    asset,
                    uploads={},
                    remove_ids={document.id},
                    actor=request.user,
                )
                log_action(
                    request,
                    "delete_asset_document",
                    "assets",
                    {
                        "document_id": document_id,
                        "asset_id": asset.id,
                        "category": doc_category,
                        "filename": doc_label,
                    },
                )
                messages.success(request, f"Documento \"{doc_label}\" eliminato.")
            return redirect("assets:asset_view", id=asset.id)
        if action == "add_asset_document_folder":
            if not _can_manage_asset_document_folders(request):
                messages.error(request, "Permessi insufficienti per gestire le cartelle documento.")
                return redirect("assets:asset_view", id=asset.id)
            category = asset.asset_category
            if category is None:
                messages.error(request, "Assegna prima una categoria all'asset per aggiungere cartelle documento.")
                return redirect("assets:asset_view", id=asset.id)
            raw_name = _clean_string(request.POST.get("folder_name"))[:120]
            slug = slugify(raw_name)[:60]
            base_codes = {code.lower() for code, _ in AssetDocument.CATEGORY_CHOICES}
            if not raw_name or not slug:
                messages.error(request, "Nome cartella non valido.")
            elif slug in base_codes:
                messages.error(request, "Esiste gia una cartella di base con questo nome.")
            elif category.document_folders.filter(slug=slug).exists():
                messages.error(request, "Esiste gia una cartella documento con questo nome per la categoria.")
            else:
                next_order = (category.document_folders.aggregate(m=Max("order"))["m"] or 0) + 1
                AssetCategoryDocumentFolder.objects.create(
                    category=category, name=raw_name, slug=slug, order=next_order
                )
                log_action(
                    request,
                    "add_asset_document_folder",
                    "assets",
                    {"asset_id": asset.id, "category_id": category.id, "slug": slug, "name": raw_name},
                )
                messages.success(
                    request,
                    f"Cartella documento \"{raw_name}\" aggiunta alla categoria {category.label}.",
                )
            return redirect("assets:asset_view", id=asset.id)
        if action == "deactivate_asset_document_folder":
            if not _can_manage_asset_document_folders(request):
                messages.error(request, "Permessi insufficienti per gestire le cartelle documento.")
                return redirect("assets:asset_view", id=asset.id)
            folder_id = _as_int(request.POST.get("folder_id"), default=0)
            folder = None
            if folder_id > 0 and asset.asset_category is not None:
                folder = asset.asset_category.document_folders.filter(id=folder_id, is_active=True).first()
            if folder is None:
                messages.error(request, "Cartella documento non trovata.")
            elif AssetDocument.objects.filter(
                asset__asset_category=folder.category, category=folder.slug
            ).exists():
                messages.error(request, "Impossibile disattivare: la cartella contiene ancora documenti.")
            else:
                folder.is_active = False
                folder.save(update_fields=["is_active"])
                log_action(
                    request,
                    "deactivate_asset_document_folder",
                    "assets",
                    {"asset_id": asset.id, "folder_id": folder.id, "slug": folder.slug},
                )
                messages.success(request, f"Cartella documento \"{folder.name}\" disattivata.")
            return redirect("assets:asset_view", id=asset.id)

    recent_workorders = asset.workorders.select_related("asset").all()[:10]
    component_rows = list(asset.components.all())
    administrative_deadlines = list(
        asset.administrative_deadlines.all().order_by("due_date", "title", "id")
    )
    custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
    custom_fields_by_code = {field.code: field for field in custom_fields}
    extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
    mapped_keys = {field.code for field in custom_fields} | {field.label for field in custom_fields}
    unmapped_extra = [(k, v) for k, v in extra.items() if k not in mapped_keys]

    now = timezone.now()
    today = timezone.localdate()
    age = max(0, int((now - asset.updated_at).total_seconds() // 60)) if asset.updated_at else 0
    if age < 1:
        sync_text = "Ultimo sync: adesso"
    elif age < 60:
        sync_text = f"Ultimo sync: {age} minuti fa"
    else:
        hours = age // 60
        sync_text = f"Ultimo sync: {hours} ore fa"

    it_details = getattr(asset, "it_details", None)
    work_machine = getattr(asset, "work_machine", None)
    travel_xyz = "N/D"
    machine_flags: list[str] = []
    if isinstance(work_machine, WorkMachine):
        travel_parts = [str(value) for value in [work_machine.x_mm, work_machine.y_mm, work_machine.z_mm] if value is not None]
        travel_xyz = " x ".join(travel_parts) + " mm" if travel_parts else "N/D"
        if work_machine.tcr_enabled:
            machine_flags.append("TCR")
        if work_machine.cnc_controlled:
            machine_flags.append("CNC")
        if work_machine.five_axes:
            machine_flags.append("5 assi")

    if isinstance(work_machine, WorkMachine):
        default_detail_metrics = [
            {"label": "Corse XYZ", "value": travel_xyz, "size": AssetDetailField.CARD_THIRD},
            {"label": "Anno macchina", "value": _coalesce_str(work_machine.year, "N/D"), "size": AssetDetailField.CARD_THIRD},
            {
                "label": "Configurazione",
                "value": ", ".join(machine_flags) if machine_flags else "Standard",
                "size": AssetDetailField.CARD_THIRD,
            },
        ]
        default_spec_pairs = [
            # Identità (produttore/modello/seriale/reparto) spostata nella card
            # "Anagrafica e assegnazione"; qui restano solo le caratteristiche tecniche.
            ("Corsa X", _format_asset_detail_value(work_machine.x_mm, AssetDetailField.FORMAT_MM)),
            ("Corsa Y", _format_asset_detail_value(work_machine.y_mm, AssetDetailField.FORMAT_MM)),
            ("Corsa Z", _format_asset_detail_value(work_machine.z_mm, AssetDetailField.FORMAT_MM)),
            ("Diametro", _format_asset_detail_value(work_machine.diameter_mm, AssetDetailField.FORMAT_MM)),
            ("Mandrino", _format_asset_detail_value(work_machine.spindle_mm, AssetDetailField.FORMAT_MM)),
            ("Anno", _coalesce_str(work_machine.year, "N/D")),
            ("TMC", _coalesce_str(work_machine.tmc, "N/D")),
            ("TCR", _format_asset_detail_value(work_machine.tcr_enabled, AssetDetailField.FORMAT_BOOL)),
            ("Pressione", _format_asset_detail_value(work_machine.pressure_bar, AssetDetailField.FORMAT_BAR)),
            ("CNC", _format_asset_detail_value(work_machine.cnc_controlled, AssetDetailField.FORMAT_BOOL)),
            ("5 assi", _format_asset_detail_value(work_machine.five_axes, AssetDetailField.FORMAT_BOOL)),
            ("Accuracy from", _coalesce_str(work_machine.accuracy_from, "N/D")),
            ("Prossima manutenzione", _format_asset_detail_value(work_machine.next_maintenance_date, AssetDetailField.FORMAT_DATE)),
            ("Soglia reminder", f"{work_machine.maintenance_reminder_days} gg"),
        ]
        # Solo identità: i campi tecnici (TCR/CNC/5 assi/manutenzione/accuracy)
        # restano nella card "Caratteristiche tecniche" per evitare duplicazione.
        default_profile_rows = [
            {"label": "Tag asset", "value": asset.asset_tag},
            {"label": "Produttore", "value": _coalesce_str(asset.manufacturer, "-")},
            {"label": "Modello", "value": _coalesce_str(asset.model, asset.name, "-")},
            {"label": "Numero seriale", "value": _coalesce_str(asset.serial_number, "-")},
            {"label": "Reparto macchina", "value": _coalesce_str(asset.reparto, "-")},
        ]
        profile_card_title = "Anagrafica e assegnazione"
    else:
        metric_battery = _coalesce_str(extra.get("battery_health"), extra.get("batteria"), "N/D")
        metric_cpu = _coalesce_str(extra.get("avg_cpu_load"), extra.get("cpu_load"), "N/D")
        metric_storage = _coalesce_str(extra.get("storage_free"), extra.get("free_storage"), it_details.disco if it_details else "", "N/D")
        default_detail_metrics = [
            {"label": "Salute batteria", "value": metric_battery, "size": AssetDetailField.CARD_THIRD},
            {"label": "Carico medio CPU", "value": metric_cpu, "size": AssetDetailField.CARD_THIRD},
            {"label": "Spazio libero", "value": metric_storage, "size": AssetDetailField.CARD_THIRD},
        ]
        default_spec_pairs = [
            ("Processore", _coalesce_str(it_details.cpu if it_details else "", asset.model, "N/D")),
            ("Numero seriale", _coalesce_str(asset.serial_number, "N/D")),
            ("Memoria", _coalesce_str(it_details.ram if it_details else "", "N/D")),
            ("Sistema operativo", _coalesce_str(it_details.os if it_details else "", "N/D")),
            ("Archiviazione", _coalesce_str(it_details.disco if it_details else "", "N/D")),
            ("Grafica", _coalesce_str(extra.get("graphics"), "N/D")),
            ("Schermo", _coalesce_str(extra.get("display"), "N/D")),
            ("Data acquisto", _coalesce_str(asset.purchase_date.strftime("%d-%m-%Y") if asset.purchase_date else "", extra.get("purchase_date"), asset.created_at.strftime("%d-%m-%Y") if asset.created_at else "", "N/D")),
            ("Data produzione", _coalesce_str(asset.production_date.strftime("%d-%m-%Y") if asset.production_date else "", extra.get("production_date"), "N/D")),
        ]
        default_profile_rows = [
            {"label": "Tag asset", "value": asset.asset_tag},
            {"label": "Produttore", "value": _coalesce_str(asset.manufacturer, "-")},
            {"label": "Modello", "value": _coalesce_str(asset.model, "-")},
            {"label": "Ultimo sync", "value": sync_text},
        ]
        profile_card_title = "Anagrafica e assegnazione"

    from ..services.it_presentation import it_context

    it_presentation = it_context(asset)
    it_ticket_create_url = ""
    if it_presentation is not None:
        from tickets.views import _can_open_tickets
        if _can_open_tickets(request, "IT"):
            it_ticket_create_url = f"{reverse('tickets:nuovo')}?tipo=IT&asset={asset.pk}"
        # Keep configured fields intact; only replace the generic fallback defaults.
        default_detail_metrics = []
        default_spec_pairs = [
            ("Processore", it_details.cpu if it_details else ""),
            ("Memoria", it_details.ram if it_details else ""),
            ("Sistema operativo", it_details.os if it_details else ""),
            ("Capacità disco", it_details.disco if it_details else ""),
            ("Grafica", extra.get("graphics", "")),
            ("Schermo", extra.get("display", "")),
            ("Data acquisto", asset.purchase_date.strftime("%d-%m-%Y") if asset.purchase_date else extra.get("purchase_date", "")),
        ]
        if it_presentation["profile"] in ("server", "vm"):
            default_spec_pairs = [(label, value) for label, value in default_spec_pairs if label not in ("Grafica", "Schermo")]
        elif it_presentation["profile"] == "printer":
            default_spec_pairs = [("Numero seriale", asset.serial_number or ""), ("Data acquisto", asset.purchase_date.strftime("%d-%m-%Y") if asset.purchase_date else "")]

    default_assignment_rows = [
        {"label": "Reparto", "value": _coalesce_str(asset.assignment_reparto, "-")},
        {"label": "Posizione", "value": _coalesce_str(asset.assignment_location, "-")},
        {"label": "Assegnato a", "value": _coalesce_str(asset.assignment_to, "Non assegnato")},
        {"label": "Assegnato dal", "value": asset.updated_at.strftime("%d-%m-%Y") if asset.updated_at else "-"},
    ]
    category_detail_sections = _build_asset_category_detail_sections(asset, extra)

    configured_sections, has_matching_detail_layout = _build_configured_asset_detail_sections(
        asset=asset,
        it_details=it_details,
        work_machine=work_machine,
        extra=extra,
        custom_fields_by_code=custom_fields_by_code,
        sync_text=sync_text,
    )
    if has_matching_detail_layout:
        detail_metrics = configured_sections.get(AssetDetailField.SECTION_METRICS, [])
        spec_rows = configured_sections.get(AssetDetailField.SECTION_SPECS, [])
        profile_rows = configured_sections.get(AssetDetailField.SECTION_PROFILE, [])
        assignment_rows = configured_sections.get(AssetDetailField.SECTION_ASSIGNMENT, [])
    else:
        detail_metrics = default_detail_metrics
        spec_rows = [
            {"label": key, "value": value}
            for key, value in default_spec_pairs
            if not _is_empty_asset_detail_value(value)
        ]
        profile_rows = default_profile_rows
        assignment_rows = default_assignment_rows
    detail_metrics = [*detail_metrics, *category_detail_sections.get(AssetDetailField.SECTION_METRICS, [])]
    spec_rows = [*spec_rows, *category_detail_sections.get(AssetDetailField.SECTION_SPECS, [])]
    profile_rows = [*profile_rows, *category_detail_sections.get(AssetDetailField.SECTION_PROFILE, [])]
    assignment_rows = [*assignment_rows, *category_detail_sections.get(AssetDetailField.SECTION_ASSIGNMENT, [])]
    for metric in detail_metrics:
        metric["size_class"] = _detail_grid_size_class(str(metric.get("size") or ""))
    spec_pairs = [(row["label"], row["value"]) for row in spec_rows]
    detail_specs_title = _coalesce_str(getattr(asset.asset_category, "detail_specs_title", ""), "Specifiche tecniche")
    profile_card_title = _coalesce_str(getattr(asset.asset_category, "detail_profile_title", ""), profile_card_title)
    detail_assignment_title = _coalesce_str(getattr(asset.asset_category, "detail_assignment_title", ""), "Responsabile attuale")
    detail_timeline_title = _coalesce_str(getattr(asset.asset_category, "detail_timeline_title", ""), "Timeline ciclo di vita")
    detail_maintenance_title = _coalesce_str(
        getattr(asset.asset_category, "detail_maintenance_title", ""),
        "Registro manutenzione",
    )
    detail_tickets_title = "Ticket collegati"

    timeline_events: list[dict] = []
    if asset.assignment_to:
        timeline_events.append(
            {
                "title": f"Assegnato a {asset.assignment_to}",
                "tag": "ASSEGNAZIONE",
                "auto_key": AssetTimelineHiddenEvent.KEY_ASSIGNMENT,
                "description": _coalesce_str(asset.assignment_location, "Asset in uso"),
                "date": asset.updated_at,
                "meta": _coalesce_str(asset.assignment_reparto, "Inventario"),
                "color": "green",
            }
        )
    timeline_events.append(
        {
            "title": "Registrazione inventario",
            "tag": "AMMINISTRAZIONE",
            "auto_key": AssetTimelineHiddenEvent.KEY_INVENTORY,
            "description": _coalesce_str(asset.source_key, "Asset aggiunto al sistema."),
            "date": asset.created_at,
            "meta": "Sistema",
            "color": "blue",
        }
    )
    if asset.created_at:
        timeline_events.append(
            {
                "title": "Acquisto / Provisioning",
                "tag": "APPROVVIGIONAMENTO",
                "auto_key": AssetTimelineHiddenEvent.KEY_PROVISIONING,
                "description": _coalesce_str(extra.get("po_ref"), "Asset provisionato"),
                "date": asset.created_at - timedelta(days=3),
                "meta": _coalesce_str(extra.get("owner_dept"), "Approvvigionamenti"),
                "color": "amber",
            }
        )
    if isinstance(work_machine, WorkMachine) and work_machine.year:
        try:
            machine_start = timezone.make_aware(datetime(int(work_machine.year), 1, 1, 8, 0, 0), timezone.get_current_timezone())
        except (TypeError, ValueError):
            machine_start = None
        if machine_start is not None:
            timeline_events.append(
                {
                    "title": "Messa in servizio macchina",
                    "tag": "OFFICINA",
                    "auto_key": AssetTimelineHiddenEvent.KEY_MACHINE_START,
                    "description": _coalesce_str(asset.reparto, "Macchina operativa"),
                    "date": machine_start,
                    "meta": _coalesce_str(asset.manufacturer, "Produzione"),
                    "color": "blue",
                }
            )
    # Voci inserite a mano: eventi reali che non passano dal portale (fermi,
    # traslochi, collaudi del fornitore) e che qui si mescolano agli automatici.
    for entry in asset.timeline_entries.all()[:200]:
        try:
            entry_at = timezone.make_aware(
                datetime(entry.event_date.year, entry.event_date.month, entry.event_date.day, 12, 0),
                timezone.get_current_timezone(),
            )
        except (TypeError, ValueError, OverflowError):
            entry_at = None
        timeline_events.append(
            {
                "title": entry.title,
                "tag": entry.tag or "MANUALE",
                "description": entry.description,
                "date": entry_at,
                "meta": _coalesce_str(entry.meta, "Inserimento manuale"),
                "color": entry.color,
                "manual": True,
                "entry_id": entry.id,
                "entry_date_iso": entry.event_date.isoformat(),
                "entry_tag": entry.tag,
                "entry_meta": entry.meta,
                "entry_description": entry.description,
            }
        )
    # Fatti dal monitoraggio SNMP e dal SOC (dispositivo muto, alert gravi,
    # vulnerabilita' critiche): ricalcolati, mai salvati, nel rispetto dei permessi.
    from ..services.it_timeline import monitoring_timeline_events

    timeline_events.extend(monitoring_timeline_events(request, asset))
    hidden_auto_keys = _asset_timeline_hidden_keys(asset)
    if hidden_auto_keys:
        # Gli eventi automatici rimossi restano fuori dalla timeline: la riga di
        # AssetTimelineHiddenEvent e' l'unica traccia, i dati dell'asset no.
        timeline_events = [event for event in timeline_events if event.get("auto_key") not in hidden_auto_keys]
    timeline_events.sort(key=lambda item: item.get("date") or now, reverse=True)

    # Aggiungi ticket MAN inclusi nel registro manutenzione
    from assets.services.maintenance_register import collect_asset_maintenance_register
    maintenance_register = collect_asset_maintenance_register(asset, include_tickets=True)
    # Converti le righe del registro in formato compatibile con il template
    maintenance_rows_from_register = []
    for row in maintenance_register:
        if row["source"] == "TICKET":
            maintenance_rows_from_register.append({
                "id": row["ticket"].id,
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "executed_at": row["executed_at"],
                "created_at": row["created_at"],
                "source": "TICKET",
                "ticket_number": row["ticket_number"],
                "url": row["url"],
                "technician": row["technician"],
                "priority": row["priority"],
                "category": row["category"],
            })
        elif row["source"] == "WORKORDER":
            maintenance_rows_from_register.append({
                "id": row["workorder"].id,
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "executed_at": row["executed_at"],
                "created_at": row["created_at"],
                "source": "WORKORDER",
                "url": row["url"],
                "technician": row["technician"],
                "get_status_display": row["workorder"].get_status_display,
                "get_kind_display": row["workorder"].get_kind_display,
                "supplier": row["workorder"].supplier,
            })
    # Ordina per data decrescente
    maintenance_rows_from_register.sort(key=lambda x: (x["executed_at"] or x["created_at"] or timezone.now()), reverse=True)
    # Limita a 10 righe
    maintenance_rows = maintenance_rows_from_register[:10]

    # Timeline P1.2: completamenti scadenze amministrative per questo asset
    deadline_completion_history = list(
        AssetAdministrativeDeadlineCompletion.objects
        .filter(deadline__asset=asset)
        .select_related("deadline", "completed_by")
        .order_by("-completed_on", "-id")[:20]
    )

    # P3.4: analisi costi manutenzione per asset
    try:
        asset_maintenance_costs = get_asset_maintenance_costs(asset.id, today=today)
    except Exception:
        asset_maintenance_costs = {"has_data": False}

    # AS3: budget manutenzione per categoria asset (anno corrente e precedente)
    asset_budget_rows: list[dict] = []
    if asset.asset_category_id:
        from decimal import Decimal as _Dec
        _zero = _Dec("0")
        _year = today.year
        for _y in (_year, _year - 1):
            try:
                _budget_obj = AssetMaintenanceBudget.objects.filter(
                    asset_category_id=asset.asset_category_id, year=_y
                ).first()
                if _budget_obj is None:
                    continue
                _budget = _budget_obj.budget_eur
                _spent = asset_maintenance_costs.get("cost_year" if _y == _year else "cost_prev_year", _zero) or _zero
                _pct = round(float(_spent / _budget * 100), 1) if _budget else 0.0
                _residual = _budget - _spent
                asset_budget_rows.append({
                    "year": _y,
                    "budget": _budget,
                    "spent": _spent,
                    "residual": _residual,
                    "pct": min(_pct, 100.0),
                    "over_budget": _spent > _budget,
                })
            except Exception:
                pass

    # AS4: timeline storico tecnico (OdL + verifiche + incidenti)
    timeline_tech_rows: list[dict] = []
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente as _RI
        _incidents = list(
            _RI.objects.filter(asset_id=asset.id)
            .order_by("-data_segnalazione")[:50]
        )
        for _inc in _incidents:
            timeline_tech_rows.append({
                "tipo": "incidente",
                "tipo_label": _inc.tipologia_scheda,
                "data": _inc.data_segnalazione,
                "titolo": _inc.tipologia_scheda,
                "dettaglio": _inc.descrizione_avvenimento or _inc.nominativo,
                "id": _inc.id,
            })
    except Exception:
        pass
    try:
        _wo_all = list(
            asset.workorders.order_by("-opened_at")
            .values("id", "title", "kind", "status", "opened_at", "closed_at")[:50]
        )
        _kind_label = {
            WorkOrder.KIND_PREVENTIVE: "Preventiva",
            WorkOrder.KIND_CORRECTIVE: "Correttiva",
            WorkOrder.KIND_SAFETY: "Sicurezza",
            WorkOrder.KIND_CALIBRATION: "Taratura",
            WorkOrder.KIND_OTHER: "Altro",
        }
        for _wo in _wo_all:
            timeline_tech_rows.append({
                "tipo": "workorder",
                "tipo_label": f"OdL — {_kind_label.get(_wo['kind'], _wo['kind'])}",
                "data": _wo["closed_at"] or _wo["opened_at"],
                "titolo": _wo["title"],
                "dettaglio": f"#{_wo['id']} · {WorkOrder.STATUS_CHOICES and dict(WorkOrder.STATUS_CHOICES).get(_wo['status'], _wo['status'])}",
                "id": _wo["id"],
            })
    except Exception:
        pass
    try:
        for _pv in asset.periodic_verifications.all().order_by("name")[:20]:
            _pv_wos = list(
                _pv.workorders.filter(asset_id=asset.id).order_by("-opened_at")
                .values("id", "title", "opened_at", "closed_at", "status")[:5]
            )
            for _wo in _pv_wos:
                timeline_tech_rows.append({
                    "tipo": "verifica",
                    "tipo_label": f"Verifica — {_pv.name}",
                    "data": _wo["closed_at"] or _wo["opened_at"],
                    "titolo": _pv.name,
                    "dettaglio": f"#{_wo['id']} · {_wo['status']}",
                    "id": _wo["id"],
                })
    except Exception:
        pass
    timeline_tech_rows.sort(key=lambda r: r["data"] if r["data"] else timezone.datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    timeline_tech_rows = timeline_tech_rows[:40]

    from tickets.models import TipoTicket
    manageable_ticket_types = {
        ticket_type
        for ticket_type in (TipoTicket.IT, TipoTicket.MAN)
        if _can_manage_ticket_type_for_asset_view(request, ticket_type)
    }
    ticket_rows = [
        {
            "numero_ticket": ticket.numero_ticket,
            "tipo_label": ticket.label_tipo,
            "titolo": ticket.titolo,
            "stato_label": ticket.label_stato,
            "priorita_label": ticket.label_priorita,
            "componente": ticket.componente,
            "created_at": ticket.created_at,
            "closed_at": ticket.closed_at,
            "detail_url": _asset_ticket_detail_url(request, ticket, manageable_ticket_types),
        }
        for ticket in asset.tickets.all()
    ]
    ticket_kpi = _compute_ticket_kpi_for_asset(asset)
    doc_category_labels, documents_by_category = _build_asset_documents_by_category(asset)
    doc_category_specs = _asset_document_folder_specs(asset)
    doc_upload_field_map = {spec["code"]: spec["field"] for spec in doc_category_specs}
    can_manage_doc_folders = _can_manage_asset_document_folders(request)
    can_manage_asset_timeline = _can_manage_asset_timeline_entries(request)
    asset_timeline_manual_enabled = _asset_timeline_manual_enabled(asset)
    periodic_verification_rows = []
    asset_execution_cutoff = _periodic_execution_window_cutoff(PERIODIC_EXECUTION_WINDOW_DEFAULT, today=today)
    for verification in asset.periodic_verifications.all().order_by("name", "id"):
        execution_rows = _periodic_execution_rows_for_verification(
            verification_id=verification.id,
            asset_id=asset.id,
            cutoff_date=asset_execution_cutoff,
            limit=10,
        )
        periodic_verification_rows.append(
            {
                "verification": verification,
                "state": _periodic_verification_state(verification, today=today),
                "execution_rows": execution_rows,
                "execution_count": len(execution_rows),
            }
        )
    active_component_count = sum(1 for component in component_rows if component.is_active)
    active_deadline_rows = [deadline for deadline in administrative_deadlines if deadline.is_active]
    deadline_state_rows = [
        {"deadline": deadline, "state": _asset_administrative_deadline_state(deadline, today=today)}
        for deadline in administrative_deadlines
    ]
    overdue_deadline_count = sum(1 for row in deadline_state_rows if row["state"]["status"] == "overdue")
    warning_deadline_count = sum(1 for row in deadline_state_rows if row["state"]["status"] == "warning")
    next_deadline_row = next(
        (row for row in deadline_state_rows if row["deadline"].is_active),
        None,
    )
    resolved_maintenance_rule_rows = resolve_asset_maintenance_rules(asset)
    asset_schedule_rows = build_day_based_maintenance_schedule_rows(
        asset_queryset=Asset.objects.filter(pk=asset.id).select_related("asset_category"),
        today=today,
    )
    open_workorders_by_rule: dict[int, WorkOrder] = {}
    rule_ids = [row["base_rule"].id for row in asset_schedule_rows]
    for workorder in (
        WorkOrder.objects.filter(
            asset=asset,
            maintenance_rule_id__in=rule_ids,
            status=WorkOrder.STATUS_OPEN,
        )
        .select_related("maintenance_rule")
        .order_by("opened_at", "id")
    ):
        open_workorders_by_rule.setdefault(workorder.maintenance_rule_id, workorder)
    for row in asset_schedule_rows:
        open_workorder = open_workorders_by_rule.get(row["base_rule"].id)
        row["open_workorder"] = open_workorder
        row["workorder_close_url"] = (
            reverse("assets:wo_close", kwargs={"id": open_workorder.id})
            if open_workorder is not None
            else ""
        )
    next_maintenance_row = next(
        (
            row
            for row in asset_schedule_rows
            if row["schedule_status"] in {"overdue", "warning", "upcoming", "missing"}
        ),
        None,
    )
    primary_contract = get_primary_assistance_contract(asset, today=today)
    primary_contract_state = contract_state_payload(primary_contract, today=today) if primary_contract is not None else None
    asset_license_rows = [
        {
            "license": license_row,
            "state": _software_license_state_payload(license_row, today=today),
            "asset_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
            "employee_url": (
                reverse("anagrafica:dipendente_detail", args=[license_row.assigned_anagrafica_id])
                if license_row.assigned_anagrafica_id
                else ""
            ),
        }
        for license_row in asset.software_licenses.all().order_by("category", "vendor", "product_name", "id")
    ]
    asset_create_workorder_url = _workorder_create_page_url(
        asset_id=asset.id,
        rule_id=getattr(next_maintenance_row.get("base_rule"), "id", 0) if next_maintenance_row else 0,
        source="asset_detail",
    )
    maintenance_suggestions = _contextual_maintenance_suggestions(
        asset=asset,
        schedule_row=next_maintenance_row,
        contract=primary_contract,
        source="asset_detail",
    )
    asset_status = _asset_status_payload(asset)
    can_manage_asset_maintenance_rules = _is_assets_admin(request)
    # «Dismetti»/«Riattiva» ed «Elimina»: admin del modulo e ruoli della manutenzione.
    can_retire_asset = _can_retire_asset(request)
    can_delete_asset = _can_delete_asset(request)
    asset_delete_blocks = blocchi_eliminazione(asset) if can_delete_asset else []
    asset_assign_url = reverse("assets:asset_assign", kwargs={"id": asset.id})

    buttons_by_zone = _build_action_buttons_for_asset(asset, create_workorder_url=asset_create_workorder_url)
    buttons_by_zone = _promote_asset_detail_actions(
        buttons_by_zone,
        assign_url=asset_assign_url,
        qr_url=reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
    )
    quick_action_buttons = [
        button
        for button in buttons_by_zone.get(AssetActionButton.ZONE_QUICK, [])
        if _clean_string(button.get("label")) not in {"Riassegna", "Crea intervento", "Etichetta QR"}
    ]

    assigned_user_admin_url = ""
    if asset.assigned_legacy_user_id:
        try:
            anag = AnagraficaDipendente.objects.filter(
                utente_id=int(asset.assigned_legacy_user_id)
            ).values_list("id", flat=True).first()
            if anag:
                assigned_user_admin_url = reverse(
                    "anagrafica:dipendente_detail",
                    kwargs={"legacy_id": anag},
                )
        except (NoReverseMatch, ValueError, TypeError):
            assigned_user_admin_url = ""
    collection_url = reverse("assets:work_machine_list") if asset.asset_type == Asset.TYPE_WORK_MACHINE else reverse("assets:asset_list")
    collection_label = "Macchine di lavoro" if asset.asset_type == Asset.TYPE_WORK_MACHINE else "Inventario"

    # Planimetria della scheda: mostra quella COERENTE COL REPARTO dell'asset,
    # non un marker qualunque. Gli asset con marker su una planimetria non
    # coerente (storici / creati prima del riallineamento al reparto) vengono
    # auto-riparati qui, spostando il marker sul layout corretto (idempotente).
    resolved_layout, layout_is_specific = _resolve_asset_plant_layout(asset)
    if resolved_layout is not None and layout_is_specific:
        has_marker = PlantLayoutMarker.objects.filter(asset=asset, layout__is_active=True).exists()
        on_resolved = PlantLayoutMarker.objects.filter(asset=asset, layout=resolved_layout).exists()
        if has_marker and not on_resolved:
            _ensure_asset_plant_layout_marker(asset)
    map_marker = _asset_plant_layout_marker(asset)
    map_card = _asset_plant_map_card(request, asset, map_marker, resolved_layout)
    map_url = map_card["map_url"] if map_card else ""

    shell_kwargs = {}
    if asset.asset_type == Asset.TYPE_WORK_MACHINE:
        shell_kwargs = {
            "search_action": reverse("assets:work_machine_list"),
            "new_url": reverse("assets:work_machine_create"),
            "new_label": "+ Nuova macchina",
            "search_placeholder": "Ricerca rapida per macchina, tag, reparto o seriale",
        }

    linked_task_rows: list[dict] = []
    upcoming_task_rows: list[dict] = []
    try:
        from tasks.models import TaskExtraRef, TaskStatus
        refs = (
            TaskExtraRef.objects.filter(asset=asset)
            .select_related("task", "task__category", "task__project", "task__assigned_to")
            .order_by("-task__updated_at", "-task_id")[:50]
        )
        today = timezone.localdate()
        seen_task_ids = set()
        for ref in refs:
            if not ref.task_id or ref.task_id in seen_task_ids:
                continue
            seen_task_ids.add(ref.task_id)
            t = ref.task
            cat_field_label = ""
            if t.category_id:
                cat_field = next((f for f in t.category.fields.all() if f.code == ref.field_code), None)
                if cat_field:
                    cat_field_label = cat_field.label
            base_row = {
                "id": t.id,
                "title": t.title,
                "status": t.get_status_display(),
                "status_code": t.status,
                "due_date": t.due_date,
                "start_date": getattr(t, "next_step_due", None),
                "assignee": (t.assigned_to.get_full_name() or t.assigned_to.username) if t.assigned_to_id else "",
                "category_name": t.category.name if t.category_id else "",
                "field_label": cat_field_label or ref.field_code,
                "project_name": t.project.name if t.project_id else "",
                "url": reverse("tasks:detail", args=[t.id]),
            }
            linked_task_rows.append(base_row)
            # "AdL previste": solo task attive con finestra temporale rilevante (in corso oppure futura)
            if t.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
                start = base_row["start_date"]
                end = base_row["due_date"]
                effective_end = end or start
                if effective_end and effective_end >= today:
                    upcoming_task_rows.append(base_row)
        upcoming_task_rows.sort(
            key=lambda r: (
                r.get("start_date") or r.get("due_date") or today,
                r.get("due_date") or today,
                r.get("id") or 0,
            )
        )
    except Exception:
        linked_task_rows = []
        upcoming_task_rows = []
    detail_section_cards = _build_asset_detail_section_cards(
        detail_specs_title=detail_specs_title,
        detail_timeline_title=detail_timeline_title,
        detail_maintenance_title=detail_maintenance_title,
        detail_tickets_title=detail_tickets_title,
        profile_card_title=profile_card_title,
        detail_assignment_title=detail_assignment_title,
        quick_action_buttons=quick_action_buttons,
        map_marker=map_card,
        doc_category_labels=doc_category_labels,
        spec_pairs=spec_pairs,
        profile_rows=profile_rows,
        license_rows=asset_license_rows,
        ticket_rows=ticket_rows,
    )
    asset_primary_kpis = _build_asset_primary_kpis(
        asset=asset,
        asset_status=asset_status,
        assignment_rows=assignment_rows,
        primary_contract=primary_contract,
        primary_contract_state=primary_contract_state,
        next_maintenance_row=next_maintenance_row,
        next_deadline_row=next_deadline_row,
        preferred_detail_metrics=_preferred_asset_detail_metrics(detail_metrics),
        detail_metrics=detail_metrics,
        asset_assign_url=asset_assign_url,
        asset_assistance_contracts_url=_assistance_contracts_page_url(asset_id=asset.id),
        asset_maintenance_schedule_url=_maintenance_schedule_page_url(asset_id=asset.id),
        asset_administrative_deadline_list_url=_asset_administrative_deadline_page_url(asset_id=asset.id),
    )
    if it_presentation is not None:
        it_presentation["show_specs"] = not AssetDetailSectionLayout.objects.filter(
            code=AssetDetailSectionLayout.SECTION_PROFILE, is_visible=False,
        ).exists()
    asset_status_band = _build_asset_status_band(
        primary_contract=primary_contract,
        primary_contract_state=primary_contract_state,
        next_deadline_row=next_deadline_row,
        asset_assistance_contracts_url=_assistance_contracts_page_url(asset_id=asset.id),
        asset_administrative_deadline_list_url=_asset_administrative_deadline_page_url(asset_id=asset.id),
    )
    # Import in-funzione: assets non deve dipendere staticamente da
    # schede_sicurezza, che resta la fonte unica dei dati chimici.
    from schede_sicurezza import pittogrammi as ghs

    scheda_chimica = asset.prodotto_chimico.scheda_corrente() if asset.prodotto_chimico_id else None
    it_monitoring = None
    from ..services.it_monitoring import has_snmp_monitoring, monitoring_for_asset

    if it_presentation is not None:
        it_monitoring = monitoring_for_asset(
            request,
            asset,
            printer=it_presentation.get("profile") == "printer",
            endpoint_ips=[e.ip for e in it_presentation.get("endpoints", []) if e.ip],
        )
    elif has_snmp_monitoring(asset):
        # Videosorveglianza, UPS, switch, NAS…: stesso riquadro degli asset IT, con gli stessi
        # permessi di Contatori IT (prima qui si vedevano host ed errori SNMP senza controllo ACL).
        it_monitoring = monitoring_for_asset(request, asset)
    if it_monitoring is not None:
        from ..services.it_identity_diff import snmp_identity_diffs

        it_monitoring["identity_diffs"] = snmp_identity_diffs(asset)
        it_monitoring["can_apply_identity"] = _can_edit_asset(request, asset.id)
    it_intune = []
    if it_presentation is not None:
        from ..services.intune import per_asset as _intune_per_asset

        it_intune = _intune_per_asset(asset)
    it_fonti = []
    if it_presentation is not None:
        from security.permissions import can_view_security_center

        from ..services.fonti_dispositivo import per_asset as _fonti_per_asset

        it_fonti = _fonti_per_asset(asset, profilo=it_presentation.get("profile"), soc=can_view_security_center(request.user))
    from ..services.asset_kpis import device_kpis as _device_kpis

    device_kpis = _device_kpis(request, asset, it_presentation)
    from ..services.costi_asset import costi_asset as _costi_asset

    asset_costi = _costi_asset(asset)
    stato_cnc = None
    if asset.asset_type in (Asset.TYPE_CNC, Asset.TYPE_WORK_MACHINE):
        from ..services.mtconnect import per_scheda

        stato_cnc = per_scheda(asset.pk)
    from ..views_asset_rete import rete_context, switch_context

    can_edit_asset = _can_edit_asset(request, asset.id)
    rete_ctx = rete_context(request, asset, can_edit=can_edit_asset) if it_presentation is not None else {}
    switch_mappa = switch_context(request, asset, can_edit=can_edit_asset)
    return render(
        request,
        "assets/pages/asset_detail.html",
        {
            "asset_costi": asset_costi,
            "stato_cnc": stato_cnc,
            "page_title": f"Dettaglio asset {asset.asset_tag}",
            "asset": asset,
            "prodotto_chimico": asset.prodotto_chimico,
            "scheda_corrente": scheda_chimica,
            # Senza SDS restano i pittogrammi dichiarati sul prodotto.
            "pittogrammi_clp": (
                ghs.dettaglio(asset.prodotto_chimico.pittogrammi_effettivi(scheda_chimica))
                if asset.prodotto_chimico_id else []
            ),
            "asset_completeness": asset.completeness(),
            "asset_status": asset_status,
            # Chi ha toccato QUESTO asset, e quando. Vedi core.audit.storico_oggetto:
            # compaiono le voci agganciate all'asset, non tutte quelle del modulo.
            "storico_audit": storico_oggetto(
                oggetto_tipo=AUDIT_OGGETTO_ASSET, oggetto_id=asset.id, limit=25,
            ),
            "recent_workorders": recent_workorders,
            "custom_fields": custom_fields,
            "unmapped_extra": unmapped_extra,
            "assigned_user_admin_url": assigned_user_admin_url,
            "sync_text": sync_text,
            "detail_metrics": detail_metrics,
            "asset_primary_kpis": asset_primary_kpis,
            "it_presentation": it_presentation,
            **rete_ctx,
            "switch_mappa": switch_mappa,
            "processi_qualificati_asset": _processi_qualificati(asset),
            "operatori_abilitati": _operatori_abilitati(request, asset),
            "it_monitoring": it_monitoring,
            "it_intune": it_intune,
            "it_fonti": it_fonti,
            "device_kpis": device_kpis,
            "it_ticket_create_url": it_ticket_create_url,
            "asset_status_band": asset_status_band,
            "detail_specs_title": detail_specs_title,
            "spec_pairs": spec_pairs,
            "profile_rows": profile_rows,
            "profile_card_title": profile_card_title,
            "assignment_rows": assignment_rows,
            "detail_assignment_title": detail_assignment_title,
            "timeline_events": timeline_events,
            "detail_timeline_title": detail_timeline_title,
            "can_manage_asset_timeline": can_manage_asset_timeline,
            "can_edit_asset_image": _can_edit_asset(request, asset.id),
            "asset_timeline_manual_enabled": asset_timeline_manual_enabled,
            "asset_timeline_color_choices": _ui_choices(AssetTimelineEntry.COLOR_CHOICES),
            "maintenance_rows": maintenance_rows,
            "deadline_completion_history": deadline_completion_history,
            "asset_maintenance_costs": asset_maintenance_costs,
            "asset_budget_rows": asset_budget_rows,
            "timeline_tech_rows": timeline_tech_rows,
            "detail_maintenance_title": detail_maintenance_title,
            "ticket_rows": ticket_rows,
            "ticket_kpi": ticket_kpi,
            "detail_tickets_title": detail_tickets_title,
            "work_machine": work_machine,
            "collection_url": collection_url,
            "collection_label": collection_label,
            "asset_license_rows": asset_license_rows,
            "asset_license_manage_url": _software_licenses_page_url(asset_id=asset.id),
            "doc_category_labels": doc_category_labels,
            "doc_category_specs": doc_category_specs,
            "documents_by_category": dict(documents_by_category),
            "document_upload_field_map": doc_upload_field_map,
            "can_manage_doc_folders": can_manage_doc_folders,
            "asset_report_pdf_url": _asset_report_pdf_url(asset.id),
            "asset_qr_url": reverse("assets:asset_qr_label", kwargs={"id": asset.id}),
            "asset_label_designer_url": (
                reverse("assets:asset_label_designer") + f"?scope=asset&asset_id={asset.id}"
                if _is_assets_admin(request)
                else ""
            ),
            "periodic_verification_rows": periodic_verification_rows,
            "periodic_verification_manage_url": _periodic_verifications_page_url(asset_id=asset.id),
            "asset_component_count": len(component_rows),
            "asset_active_component_count": active_component_count,
            "asset_component_list_url": _asset_component_page_url(asset_id=asset.id),
            "asset_component_create_url": _asset_component_create_page_url(asset_id=asset.id),
            "asset_administrative_deadline_count": len(administrative_deadlines),
            "asset_active_administrative_deadline_count": len(active_deadline_rows),
            "asset_overdue_administrative_deadline_count": overdue_deadline_count,
            "asset_warning_administrative_deadline_count": warning_deadline_count,
            "asset_next_administrative_deadline": next_deadline_row["deadline"] if next_deadline_row else None,
            "asset_next_administrative_deadline_state": next_deadline_row["state"] if next_deadline_row else None,
            "asset_administrative_deadline_list_url": _asset_administrative_deadline_page_url(asset_id=asset.id),
            "asset_administrative_deadline_create_url": _asset_administrative_deadline_create_page_url(asset_id=asset.id),
            "asset_maintenance_rule_count": len(resolved_maintenance_rule_rows),
            "asset_overridden_maintenance_rule_count": sum(
                1 for row in resolved_maintenance_rule_rows if row["status"] == "overridden"
            ),
            "asset_disabled_maintenance_rule_count": sum(
                1 for row in resolved_maintenance_rule_rows if row["status"] == "disabled"
            ),
            "asset_maintenance_rule_list_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            # Piani del nuovo dominio (Piano -> Applicazione -> Occorrenza).
            **_asset_maintenance_plans_context(asset),
            **_asset_deadlines_context(request, asset),
            "can_manage_asset_maintenance_rules": can_manage_asset_maintenance_rules,
            "asset_linked_task_rows": linked_task_rows,
            "asset_upcoming_task_rows": upcoming_task_rows,
            "asset_maintenance_schedule_url": _maintenance_schedule_page_url(asset_id=asset.id),
            "asset_assistance_contracts_url": _assistance_contracts_page_url(asset_id=asset.id),
            "asset_primary_contract": primary_contract,
            "asset_primary_contract_state": primary_contract_state,
            "asset_next_maintenance_row": next_maintenance_row,
            "asset_schedule_rows": asset_schedule_rows,
            "asset_create_workorder_url": asset_create_workorder_url,
            "maintenance_suggestions": maintenance_suggestions,
            "can_manage_licenses": _is_assets_admin(request),
            "asset_assign_url": asset_assign_url,
            "header_action_buttons": buttons_by_zone.get(AssetActionButton.ZONE_HEADER, []),
            "quick_action_buttons": quick_action_buttons,
            "detail_section_cards": detail_section_cards,
            "layout_manage_url": (
                reverse("assets:asset_detail_layout_admin") + f"?asset={asset.id}"
                if _can_manage_asset_detail_layout(request)
                else ""
            ),
            "map_marker": map_marker,
            "map_card": map_card,
            "map_url": map_url,
            "can_retire_asset": can_retire_asset,
            "can_delete_asset": can_delete_asset,
            "document_upload_accept": _workorder_attachment_accept_attr(),
            "document_upload_max_bytes": ASSET_DOCUMENT_MAX_BYTES,
            "asset_delete_blocks": asset_delete_blocks,
            "asset_is_retired": asset.status == Asset.STATUS_RETIRED,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25), **shell_kwargs),
        },
    )


def _operatori_abilitati(request, asset) -> dict | None:
    """Chi è abilitato sulla macchina (skill matrix); i nomi solo a chi legge la skill matrix. Fail-safe."""
    from anagrafica.services import struttura_macchina

    try:
        return struttura_macchina.operatori(asset, con_nomi=struttura_macchina.puo_vedere_nomi(request))
    except Exception:
        return None


def _processi_qualificati(asset) -> list:
    """Processi qualificati MOD.128 dell'asset (collegati o PART145 dal flag); fail-safe."""
    from ..services.part145 import processi_dell_asset

    try:
        return processi_dell_asset(asset)
    except Exception:
        return []


# Ingrandimento della vista «Zona» nella scheda: la planimetria intera in una
# card larga mezza pagina rende la macchina un puntino illeggibile.
_MAP_CARD_ZOOM = 3.0
_MAP_CARD_RATIO = 2.0  # aspect-ratio di .af-map-zone


def _map_card_background_position(x_percent: float, y_percent: float, width: int, height: int) -> tuple[float, float]:
    """``background-position`` (in %) che mette il punto al centro della card.

    Con ``background-size: Z*100% auto`` lo scostamento vale ``P*(C-S)``: si
    risolve ``P`` perché il punto cada a metà del contenitore, in entrambi gli assi.
    """
    def solve(point: float, ratio: float) -> float:
        if abs(ratio - 1) < 1e-6:
            return 50.0
        return round((0.5 - point * ratio) / (1 - ratio) * 100, 3)

    ratio_x = _MAP_CARD_ZOOM
    ratio_y = _MAP_CARD_ZOOM * _MAP_CARD_RATIO * (height / width) if width and height else _MAP_CARD_ZOOM
    return solve(x_percent / 100, ratio_x), solve(y_percent / 100, ratio_y)


def _asset_plant_map_card(request, asset, marker, resolved_layout) -> dict | None:
    """Dati della card «Posizione in officina»: zona ingrandita, reparto, stato."""
    from ..services.plant_layout_image import area_at_point, marker_is_unplaced

    can_manage = user_can_modulo_action(request, "assets", "admin_assets")
    editor_base = reverse("assets:plant_layout_editor")
    if marker is None:
        # Nessun marker: la card serve solo a chi può posizionare la macchina.
        if not (can_manage and resolved_layout is not None and asset.asset_type == Asset.TYPE_WORK_MACHINE):
            return None
        return {
            "layout": resolved_layout,
            "marker": None,
            "placed": False,
            "editor_url": f"{editor_base}?layout={resolved_layout.id}&asset={asset.id}",
            "map_url": "",
        }
    layout = marker.layout
    width, height = _plant_layout_image_size(layout)
    placed = not marker_is_unplaced(marker)
    area = area_at_point(list(layout.areas.all()), marker.x_percent, marker.y_percent) if placed else None
    bg_x, bg_y = _map_card_background_position(float(marker.x_percent), float(marker.y_percent), width, height)
    return {
        "layout": layout,
        "marker": marker,
        "placed": placed,
        "area_name": area.name if area else "",
        "area_color": area.color if area else "",
        "image_url": layout.image.url if layout.image else "",
        "ratio": f"{width}/{height}" if width and height else "4/3",
        "zoom_size": f"{_MAP_CARD_ZOOM * 100:g}%",
        "bg_x": f"{bg_x:g}%",
        "bg_y": f"{bg_y:g}%",
        "map_url": reverse("assets:plant_layout_map") + f"?asset={asset.id}&category={quote(layout.category)}",
        "editor_url": f"{editor_base}?layout={layout.id}&asset={asset.id}" if can_manage else "",
    }
