"""Parte di assets/views.py non ancora spezzata (refactor C4, transitorio)."""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models import Avg, Case, Count, IntegerField, Max, Prefetch, ProtectedError, Q, When
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import slugify
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from admin_portale.decorators import legacy_admin_or_acl_required, legacy_admin_required
from config.env_config import get_first_env_value, load_env_file_values, resolve_env_value, update_env_file_values
from core.acl import user_can_modulo_action
from core.public_headers import risposta_pubblica
from core.audit import log_action, storico_oggetto
from core.upload_limits import DOCUMENT_MAX_BYTES

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.graph_utils import acquire_graph_token, is_placeholder_value
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.models import AuditLog, SiteConfig, UserDashboardLayout, UserExtraInfo
from core.module_branding import (
    get_module_branding_context,
    handle_module_branding_post,
    resolve_module_logo,
)
from core.module_registry import resolve_module_label
from core.pdf import (
    PdfTheme,
    draw_canvas_footer,
    draw_canvas_header,
)
from core.table_pdf import render_table_pdf as _report_table_pdf
from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime
from ..forms import (
    AssistanceContractForm,
    AssetAdministrativeDeadlineForm,
    AssetAssignmentForm,
    AssetComponentForm,
    AssetFilterForm,
    AssetForm,
    AssetLabelTemplateForm,
    ChemicalAssetForm,
    MaintenanceChecklistStepFormSet,
    MaintenanceInterventionTemplateForm,
    MaintenanceRuleForm,
    MaintenanceRuleAssetOverrideForm,
    PeriodicVerificationForm,
    PlantLayoutForm,
    SoftwareLicenseForm,
    SoftwareLicenseRenewalForm,
    WorkMachineAssetForm,
    DeviceFilterForm,
    IT_DEVICE_TYPES,
    NON_IT_ASSET_TYPES,
    PRODUCTION_ASSET_TYPES,
    WorkMachineFilterForm,
    WorkOrderCloseForm,
    WorkOrderForm,
)
from ..models import _add_months
from ..models import (
    Asset,
    AssetActionButton,
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    AssetAdministrativeDeadlineCompletionAttachment,
    AssetCategory,
    AssetCategoryDocumentFolder,
    AssetCategoryField,
    AssetComponent,
    AssetCustomField,
    AssetDashboardConfig,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetHeaderTool,
    AssetLabelTemplate,
    AssetListLayout,
    AssetListOption,
    AssetMaintenanceBudget,
    AssetMaintenanceRuleState,
    AssetMeter,
    AssetMeterHistory,
    AssetCalendarEvent,
    AssistanceContract,
    AssetReportDefinition,
    AssetReportTemplate,
    AssetSidebarButton,
    AssetTimelineEntry,
    AssetTimelineHiddenEvent,
    SoftwareLicense,
    SoftwareLicenseRenewal,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderChecklist,
    WorkOrderExecutionDay,
    WorkOrderLog,
)
from ..maintenance import (
    build_workorder_prefill_payload,
    build_day_based_maintenance_schedule_rows,
    contract_state_payload,
    copy_template_checklist_to_workorder,
    distribute_campaign_due_dates,
    get_applicable_assistance_contracts,
    get_primary_assistance_contract,
    get_workorder_overdue_days,
    normalize_workorder_source,
    preview_maintenance_rule_impact,
    resolve_asset_maintenance_rules,
    upsert_asset_maintenance_rule_state,
)
from ..notifications import notify_workorder_assigned, notify_workorder_reassigned, notify_workorder_taken_over
from ..services.dashboard_kpi import (
    get_asset_maintenance_costs,
    get_downtime_by_family,
    get_families_distribution,
    get_family_dashboard_kpis,
    get_fire_safety_kpis,
    get_maintenance_by_family,
    get_maintenance_kpis_for_types,
    get_maintenance_performance_kpis,
)
from ..services.maintenance_kpi import build_maintenance_report_kpis
from ..services import storico_asset
from ..services.ciclo_vita_asset import blocchi_eliminazione
from ..models import AssetFieldHistory
from ..services.sidebar_categories import (
    category_sidebar_active_match as _service_category_sidebar_active_match,
    category_sidebar_target as _service_category_sidebar_target,
)

from ._helpers import (  # noqa: F401
    _as_int,
    _clean_string,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
)

def _default_man_category(categorie: list[tuple[str, str]]) -> str:
    """Categoria usata quando chi segnala non ne sceglie una.

    Nessuna impostazione nuova: «Generica» se e' fra le categorie MAN attive, poi
    «Altro Manutenzione», altrimenti la prima attiva (``get_categorie`` ripiega
    comunque sull'elenco predefinito, quindi un valore c'e' sempre).
    """
    codes = [code for code, _label in categorie]
    for preferred in ("GENERICA", "ALTRO_MAN"):
        if preferred in codes:
            return preferred
    return codes[0] if codes else "GENERICA"


# Priorita' proposte a chi segnala dal campo: tre scelte grandi, non quattro.
# «Urgente» resta accettata dal POST (link o form vecchi) ma non si propone: chi
# segnala da telefono dice quanto e' grave, l'urgenza la decide la manutenzione.
QUICK_REPORT_PRIORITIES = (("BASSA", "Bassa"), ("MEDIA", "Media"), ("ALTA", "Alta"))
QUICK_REPORT_MAX_PHOTOS = 3
QUICK_REPORT_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
QUICK_REPORT_PHOTO_MIMES = {"image/jpeg", "image/png"}


@login_required
def asset_quick_report(request: HttpRequest) -> HttpResponse:
    """P3.2 — Segnalazione guasto per operatori non-admin (anche da telefono, dal QR).

    Crea un Ticket MAN con asset, descrizione, priorita' e fino a tre foto. Con
    ``?asset=<id>`` l'asset e' fissato (intestazione, niente elenco); con
    ``?from=qr`` la pagina e' quella minimale della landing QR, senza la shell del
    modulo. Il login resta obbligatorio anche arrivando dal QR pubblico.
    """
    from tickets.allegati import AllegatoError, carica_allegato, qr_rate_limited, registra_caricamento
    from tickets.models import TipoTicket, PrioritaTicket, Ticket, get_categorie

    from_qr = _clean_string(request.GET.get("from") or request.POST.get("from")).lower() == "qr"
    raw_asset = request.GET.get("asset") or request.POST.get("fixed_asset")
    fixed_asset = None
    if raw_asset:
        # Stessa regola della landing QR: un asset inesistente non si segnala.
        fixed_asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=_as_int(raw_asset, default=0))

    asset_choices = []
    if fixed_asset is None:
        # Asset selezionabili: macchine e asset di produzione (no IT puro)
        asset_choices = list(
            Asset.objects
            .filter(status=Asset.STATUS_IN_USE)
            .exclude(asset_type__in=IT_DEVICE_TYPES)
            .order_by("reparto", "name", "asset_tag")
            .values("id", "asset_tag", "name", "reparto")
        )

    categorie_man = get_categorie(TipoTicket.MAN)
    default_categoria = _default_man_category(categorie_man)
    valid_priorities = dict(PrioritaTicket.choices)

    error: str = ""
    success_ticket = None
    photo_notes: list[str] = []

    if request.method == "POST":
        asset_id = fixed_asset.id if fixed_asset is not None else _as_int(request.POST.get("asset_id"), default=0)
        asset_libera = "" if fixed_asset is not None else _clean_string(request.POST.get("asset_descrizione_libera"))
        categoria = _clean_string(request.POST.get("categoria"))
        titolo = _clean_string(request.POST.get("titolo"))
        descrizione = _clean_string(request.POST.get("descrizione"))
        priorita = _clean_string(request.POST.get("priorita")) or PrioritaTicket.MEDIA
        incide_sicurezza = request.POST.get("incide_sicurezza") == "1"
        photos = request.FILES.getlist("foto")

        if not titolo or not descrizione:
            error = "Titolo e descrizione sono obbligatori."
        elif not asset_id and not asset_libera:
            error = "Seleziona un asset o descrivi il punto di intervento."
        elif len(photos) > QUICK_REPORT_MAX_PHOTOS:
            error = f"Puoi allegare al massimo {QUICK_REPORT_MAX_PHOTOS} foto."
        else:
            if priorita not in valid_priorities:
                priorita = PrioritaTicket.MEDIA
            if categoria not in {code for code, _label in categorie_man}:
                categoria = default_categoria

            asset_obj = fixed_asset
            if asset_obj is None and asset_id:
                asset_obj = Asset.objects.filter(pk=asset_id).only("id").first()

            # Identità richiedente dal legacy user o dall'utente Django. UserExtraInfo e'
            # in core.models (importato in testa): l'import da anagrafica.models falliva
            # e ogni invio rispondeva 500.
            legacy_user = getattr(request, "legacy_user", None)
            if legacy_user is None:
                try:
                    extra = UserExtraInfo.objects.filter(user=request.user).select_related("user").first()
                    legacy_user = extra
                except Exception:
                    legacy_user = None

            if legacy_user and hasattr(legacy_user, "nome"):
                req_name = (_clean_string(getattr(legacy_user, "nome", "")) or request.user.get_full_name() or request.user.get_username())
                req_email = (_clean_string(getattr(legacy_user, "email", "")) or request.user.email or "").lower()
                req_legacy_id = getattr(legacy_user, "id", None)
            else:
                req_name = request.user.get_full_name() or request.user.get_username()
                req_email = (request.user.email or "").lower()
                req_legacy_id = None

            ticket = Ticket(
                tipo=TipoTicket.MAN,
                titolo=titolo,
                descrizione=descrizione,
                categoria=categoria,
                priorita=priorita,
                incide_sicurezza=incide_sicurezza,
                asset=asset_obj,
                asset_descrizione_libera=asset_libera if not asset_obj else "",
                richiedente_nome=req_name,
                richiedente_email=req_email,
                richiedente_legacy_user_id=req_legacy_id,
                include_in_maintenance_register=True,
            )
            try:
                ticket.save()
            except Exception as exc:
                error = f"Errore nella creazione del ticket: {exc}"
            else:
                # Foto: il ticket esiste gia'. Una foto rifiutata (formato, peso) si
                # scarta e si dice quale, senza perdere la segnalazione.
                saved_photos = []
                if photos and asset_obj is not None and qr_rate_limited(request, asset_obj.id):
                    photo_notes.append("Troppi invii ravvicinati: le foto non sono state salvate, la segnalazione si'.")
                    photos = []
                for photo in photos:
                    try:
                        saved_photos.append(
                            carica_allegato(
                                ticket,
                                photo,
                                caricato_da_nome=req_name,
                                caricato_da_email=req_email,
                                descrizione="Foto della segnalazione",
                                allowed_extensions=QUICK_REPORT_PHOTO_EXTENSIONS,
                                allowed_mimes=QUICK_REPORT_PHOTO_MIMES,
                            )
                        )
                    except AllegatoError as exc:
                        photo_notes.append(f"Foto «{getattr(photo, 'name', 'senza nome')}» scartata: {exc}")
                if saved_photos:
                    registra_caricamento(ticket, saved_photos)
                log_action(
                    request,
                    "asset_quick_report_create",
                    "assets",
                    {
                        "ticket_id": ticket.id,
                        "ticket_numero": ticket.numero_ticket,
                        "asset_id": asset_id,
                        "categoria": categoria,
                        "priorita": priorita,
                        "foto": len(saved_photos),
                        "da_qr": from_qr,
                    },
                )
                success_ticket = ticket

    landing_url = (
        reverse("assets:asset_qr_landing", kwargs={"asset_tag": fixed_asset.asset_tag}) if fixed_asset is not None else ""
    )
    again_url = reverse("assets:asset_quick_report")
    if fixed_asset is not None:
        again_url += f"?asset={fixed_asset.id}" + ("&from=qr" if from_qr else "")
    context = {
        "page_title": "Segnala un problema",
        "fixed_asset": fixed_asset,
        "asset_choices": asset_choices,
        "categorie_man": categorie_man,
        "default_categoria": default_categoria,
        "priorita_choices": QUICK_REPORT_PRIORITIES,
        "max_photos": QUICK_REPORT_MAX_PHOTOS,
        "error": error,
        "success_ticket": success_ticket,
        "success_ticket_id": success_ticket.id if success_ticket is not None else None,
        "photo_notes": photo_notes,
        "from_qr": from_qr,
        "landing_url": landing_url,
        "again_url": again_url,
    }
    if from_qr:
        # Come la landing QR: pagina minimale, niente sidebar/shell del modulo.
        return render(request, "assets/pages/asset_quick_report_qr.html", context)
    return render(
        request,
        "assets/pages/asset_quick_report.html",
        {**context, **_assets_shell_context(request, rows=25)},
    )


# ---------------------------------------------------------------------------
# Dashboard Assets
# ---------------------------------------------------------------------------

_WIDGET_META: dict[str, dict] = {
    "totale_asset": {"label": "Totale asset", "icon": "package", "color": "blue"},
    "asset_in_uso": {"label": "In uso", "icon": "check-circle", "color": "green"},
    "asset_in_riparazione": {"label": "In riparazione", "icon": "wrench", "color": "orange"},
    "scadenze_scadute": {"label": "Scadenze scadute", "icon": "alert-triangle", "color": "red"},
    "scadenze_30gg": {"label": "Scadenze 30 gg", "icon": "clock", "color": "yellow"},
    "scadenze_90gg": {"label": "Scadenze 90 gg", "icon": "calendar", "color": "slate"},
    "wo_aperte": {"label": "OdL aperte", "icon": "clipboard-list", "color": "blue"},
    "wo_chiuse_mese": {"label": "OdL chiuse (mese)", "icon": "clipboard-check", "color": "green"},
    "verifiche_scadute": {"label": "Piani scaduti", "icon": "shield-alert", "color": "red"},
    "verifiche_30gg": {"label": "Piani in scadenza 30 gg", "icon": "shield-check", "color": "yellow"},
    "asset_per_stato": {"label": "Asset per stato", "icon": "bar-chart", "color": "slate"},
    "asset_per_categoria": {"label": "Asset per categoria", "icon": "layers", "color": "slate"},
}


def _compute_dashboard_kpis(today: date) -> dict:
    """Calcola tutti i valori KPI per la dashboard assets."""
    from django.db.models import Min

    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)
    first_day_month = today.replace(day=1)

    total = Asset.objects.exclude(status=Asset.STATUS_RETIRED).count()
    in_uso = Asset.objects.filter(status=Asset.STATUS_IN_USE).count()
    in_repair = Asset.objects.filter(status=Asset.STATUS_IN_REPAIR).count()

    # Scadenze amministrative: registro separato dai piani, senza le copie
    # migrate (``deadline_feed``).
    from ..services import deadline_feed as feed

    admin_dues = feed.administrative_dues(due_to=in_90, exclude_retired=False)
    dl_scadute = sum(1 for due in admin_dues if due.due_date < today)
    dl_30 = sum(1 for due in admin_dues if today <= due.due_date <= in_30)
    dl_90 = sum(1 for due in admin_dues if in_30 < due.due_date <= in_90)

    # OdL
    wo_aperte = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).count()
    wo_chiuse_mese = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_DONE, closed_at__date__gte=first_day_month
    ).count()

    # Verifiche periodiche
    pv_qs = PeriodicVerification.objects.filter(is_active=True, is_legacy=False, next_verification_date__isnull=False)
    pv_scadute = pv_qs.filter(next_verification_date__lt=today).count()
    pv_30 = pv_qs.filter(next_verification_date__gte=today, next_verification_date__lte=in_30).count()

    # Asset per stato
    status_map = dict(Asset.STATUS_CHOICES)
    per_stato_qs = Asset.objects.values("status").annotate(n=Count("id")).order_by("-n")
    per_stato = [
        {"status": r["status"], "label": status_map.get(r["status"], r["status"]), "count": r["n"]}
        for r in per_stato_qs
    ]

    # Asset per categoria (top 10 + "Altro")
    per_cat_qs = list(
        Asset.objects.values("asset_category__id", "asset_category__label")
        .annotate(n=Count("id"))
        .order_by("-n")[:12]
    )
    per_categoria = []
    for r in per_cat_qs:
        per_categoria.append({
            "id": r["asset_category__id"],
            "label": r["asset_category__label"] or "Senza categoria",
            "count": r["n"],
        })

    # Prossime scadenze (lista breve)
    prossime_scadenze = [due for due in admin_dues if today <= due.due_date <= in_30][:8]
    prossime_verifiche = list(
        PeriodicVerification.objects.filter(is_active=True, next_verification_date__gte=today, next_verification_date__lte=in_30)
        .order_by("next_verification_date")[:8]
    )
    scadenze_arretrate = [due for due in admin_dues if due.due_date < today][:8]

    return {
        "totale_asset": total,
        "asset_in_uso": in_uso,
        "asset_in_riparazione": in_repair,
        "scadenze_scadute": dl_scadute,
        "scadenze_30gg": dl_30,
        "scadenze_90gg": dl_90,
        "wo_aperte": wo_aperte,
        "wo_chiuse_mese": wo_chiuse_mese,
        "verifiche_scadute": pv_scadute,
        "verifiche_30gg": pv_30,
        "asset_per_stato": per_stato,
        "asset_per_categoria": per_categoria,
        # dati lista per le card detail
        "prossime_scadenze": prossime_scadenze,
        "prossime_verifiche": prossime_verifiche,
        "scadenze_arretrate": scadenze_arretrate,
    }


def _legacy_asset_dashboard_list_redirect_url(request: HttpRequest) -> str:
    if request.method != "GET" or not request.GET:
        return ""
    legacy_list_query_keys = {"q", "asset_type", "reparto", "vlan", "ip", "rows", "page"}
    if not any(key in request.GET for key in legacy_list_query_keys):
        return ""
    query_string = request.GET.urlencode()
    target_url = reverse("assets:asset_list")
    return f"{target_url}?{query_string}" if query_string else target_url


def _dashboard_workorders(request: HttpRequest, today: date, limit: int = 6) -> dict:
    """OdL aperti per il centro "Da fare": urgenti e in ritardo in testa."""
    from assets.maintenance import get_workorder_overdue_days

    now = timezone.now()
    age_threshold = today - timedelta(days=get_workorder_overdue_days())
    qs = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN)
        .exclude(asset__status=Asset.STATUS_RETIRED)
        .select_related("asset", "assigned_to")
    )
    open_rows = list(qs.order_by("opened_at", "id")[:400])

    def _late(wo) -> bool:
        if wo.due_at and wo.due_at < now:
            return True
        return bool(wo.opened_at and wo.opened_at.date() <= age_threshold)

    def _sort_key(wo):
        return (
            0 if wo.priority == WorkOrder.PRIORITY_URGENT else 1,
            0 if _late(wo) else 1,
            wo.opened_at or now,
        )

    items = []
    for wo in sorted(open_rows, key=_sort_key)[:limit]:
        assignee = ""
        if wo.assigned_to_id:
            assignee = wo.assigned_to.get_full_name() or wo.assigned_to.get_username()
        opened = wo.opened_at.date() if wo.opened_at else None
        items.append({
            "id": wo.id,
            "title": wo.title,
            "asset_tag": wo.asset.asset_tag if wo.asset_id else "",
            "asset_name": wo.asset.name if wo.asset_id else "",
            "kind_label": wo.get_kind_display(),
            "is_urgent": wo.priority == WorkOrder.PRIORITY_URGENT,
            "is_late": _late(wo),
            "state_label": wo.operational_state_label,
            "state": wo.operational_state or "",
            "assignee": assignee,
            "is_mine": wo.assigned_to_id == request.user.id,
            "age_days": (today - opened).days if opened else None,
        })
    return {
        "items": items,
        "total": qs.count(),
        "urgent": sum(1 for wo in open_rows if wo.priority == WorkOrder.PRIORITY_URGENT),
        "late": sum(1 for wo in open_rows if _late(wo)),
        "unassigned": sum(1 for wo in open_rows if not wo.assigned_to_id),
        "mine": sum(1 for wo in open_rows if wo.assigned_to_id == request.user.id),
    }


def _dashboard_deadlines(request: HttpRequest, today: date, limit: int = 8) -> dict:
    """Scadenze (piani, amministrative, licenze, contratti) + verifiche periodiche
    entro 30 giorni o gia' scadute, in una lista sola. Sola lettura: le azioni
    puntano alle pagine che gia' le gestiscono."""
    from ..services import deadline_feed as feed

    horizon = today + timedelta(days=30)
    rows: list[dict] = []
    try:
        deadlines = feed.collect(
            start=None,
            end=horizon,
            filters=feed.FeedFilters(kinds=feed.allowed_kinds(request)),
            today=today,
        )
    except Exception:
        deadlines = []
    for dl in deadlines:
        if dl.state == feed.STATE_DONE:
            continue
        rows.append({
            "source": dl.kind,
            "source_label": dl.kind_label,
            "title": dl.title,
            "due_date": dl.due_date,
            "days": (dl.due_date - today).days,
            "is_overdue": dl.due_date < today,
            "asset_tag": dl.asset_tag,
            "asset_name": dl.asset_name or dl.target_label,
            "url": dl.detail_url,
            "action_label": (dl.actions[0]["label"] if dl.actions else "Apri"),
            "work_order_id": dl.work_order_id,
        })
    verifications = PeriodicVerification.objects.filter(
        is_active=True, is_legacy=False, next_verification_date__isnull=False,
        next_verification_date__lte=horizon,
    ).order_by("next_verification_date")[:200]
    pv_url = reverse("assets:periodic_verifications")
    for pv in verifications:
        rows.append({
            "source": "verification",
            "source_label": "Verifica",
            "title": pv.name,
            "due_date": pv.next_verification_date,
            "days": (pv.next_verification_date - today).days,
            "is_overdue": pv.next_verification_date < today,
            "asset_tag": "",
            "asset_name": "",
            "url": pv_url,
            "action_label": "Gestisci",
            "work_order_id": None,
        })
    rows.sort(key=lambda r: (r["due_date"], r["title"]))
    overdue = [r for r in rows if r["is_overdue"]]
    plan_sources = {feed.KIND_ORDINARY, "verification"}
    return {
        "items": rows[:limit],
        "total": len(rows),
        "overdue": len(overdue),
        "due_soon": len(rows) - len(overdue),
        "maintenance_overdue": sum(1 for r in overdue if r["source"] == feed.KIND_ORDINARY),
        "maintenance_due_soon": sum(
            1 for r in rows if r["source"] == feed.KIND_ORDINARY and not r["is_overdue"]
        ),
        # Scadenze dei piani (regole + eventuali piani periodici non ancora
        # convertiti): alimentano i riquadri "Verifiche" della dashboard.
        "plan_overdue": sum(1 for r in overdue if r["source"] in plan_sources),
        "plan_due_soon": sum(1 for r in rows if r["source"] in plan_sources and not r["is_overdue"]),
        "plan_upcoming": [r for r in rows if r["source"] in plan_sources and not r["is_overdue"]][:8],
    }


def _dashboard_launcher(request: HttpRequest, counters: dict) -> list[dict]:
    """Collegamenti alle parti principali del modulo, filtrati con la stessa
    decisione ACL del middleware (fail-closed): non si mostrano porte chiuse."""
    from core.middleware import acl_allows_path

    tiles = [
        ("inventory", "Inventario", "Tutti gli asset, filtri ed export", reverse("assets:asset_list"), counters.get("assets"), ""),
        ("hub", "Centro manutenzione", "Punto di partenza del manutentore", reverse("assets:maintenance_hub"), None, ""),
        ("todo", "Da fare", "Manutenzioni programmate aperte", reverse("assets:maintenance_da_fare"), counters.get("maintenance_overdue"), "red"),
        ("workorders", "Ordini di lavoro", "Interventi aperti e chiusi", reverse("assets:wo_list"), counters.get("wo_open"), "amber"),
        ("shift", "Il mio lavoro", "Le manutenzioni e gli interventi tuoi e di nessuno", f"{reverse('assets:maintenance_da_fare')}?mio=1", counters.get("wo_mine"), "blue"),
        ("deadlines", "Scadenzario", "Scadenze di piani, adempimenti e contratti", reverse("assets:maintenance_scadenze"), counters.get("deadlines_overdue"), "red"),
        ("plans", "Piani di manutenzione", "Cicli e frequenze per asset", reverse("assets:maintenance_plan_list"), None, ""),
        ("checks", "Verifiche impianti", "Luci di emergenza, estintori, impianti", reverse("assets:periodic_check_list"), None, ""),
        ("map", "Mappa officina", "Stato delle macchine in planimetria", reverse("assets:plant_layout_map"), None, ""),
        ("machines", "Macchine di lavoro", "Cruscotto del parco produttivo", reverse("assets:work_machine_dashboard"), None, ""),
        ("tickets", "Segnalazioni", "Ticket di manutenzione dagli operatori", f"{reverse('tickets:gestione_list')}?tipo=MAN", counters.get("tickets_new"), "amber"),
        ("history", "Storico", "Interventi eseguiti e registro", reverse("assets:maintenance_history"), None, ""),
        ("reports", "Report", "Report e analisi del modulo", reverse("assets:reports"), None, ""),
    ]
    user = getattr(request, "user", None)
    output = []
    for code, label, hint, url, count, tone in tiles:
        try:
            allowed = acl_allows_path(url.split("?", 1)[0], django_user=user, request=request)
        except Exception:
            allowed = False
        if not allowed:
            continue
        output.append({
            "code": code, "label": label, "hint": hint, "url": url,
            "count": count or 0, "tone": tone if count else "",
        })
    return output


@login_required
def asset_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard principale del modulo Assets con KPI personalizzabili."""
    legacy_list_redirect = _legacy_asset_dashboard_list_redirect_url(request)
    if legacy_list_redirect:
        return redirect(legacy_list_redirect)

    today = timezone.localdate()
    selected_family_id = None
    selected_family_label = ""
    raw_family_id = request.GET.get("family")
    if raw_family_id:
        try:
            candidate_family_id = int(raw_family_id)
        except (TypeError, ValueError):
            candidate_family_id = None
        if candidate_family_id:
            selected_family = AssetCategory.objects.filter(pk=candidate_family_id, is_active=True).first()
            if selected_family:
                selected_family_id = selected_family.id
                selected_family_label = selected_family.label

    # Configurazione widget utente
    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    enabled = cfg.get_enabled_widgets()

    kpis = _compute_dashboard_kpis(today)
    family_kpis = get_family_dashboard_kpis(selected_family_id, today=today)
    family_distribution = get_families_distribution(today=today)
    maintenance_by_family = get_maintenance_by_family(today=today)
    downtime_by_family = get_downtime_by_family(today=today)
    fire_safety_kpis = get_fire_safety_kpis(today=today)
    try:
        maintenance_perf = get_maintenance_performance_kpis(today=today)
    except Exception:
        maintenance_perf = {
            "mttr_hours": 0, "downtime_hours_month": 0, "maintenance_cost_month": 0,
            "wo_open_by_kind": {}, "wo_open_total": 0, "ticket_man_open": 0,
            "wo_closed_month": 0, "has_data": False,
        }

    # Cruscotto operativo (cose da fare + segnalazioni arrivate), condiviso con il Centro Manutenzione
    from assets.services.dashboard_kpi import get_cose_da_fare_overview, get_segnalazioni_overview
    cose_da_fare = get_cose_da_fare_overview(today=today)
    segnalazioni = get_segnalazioni_overview(today=today)

    # Centro "Da fare": interventi, segnalazioni e scadenze con le azioni rapide
    dash_wo = _dashboard_workorders(request, today)
    dash_deadlines = _dashboard_deadlines(request, today)
    from tickets.views import _can_manage_tickets
    from tickets.models import TipoTicket

    try:
        can_manage_man = _can_manage_tickets(request, TipoTicket.MAN)
    except Exception:
        can_manage_man = False
    attention_total = (
        dash_wo["urgent"] + dash_wo["late"] + segnalazioni["urgenti"] + dash_deadlines["overdue"]
    )
    launcher = _dashboard_launcher(request, {
        "assets": kpis["totale_asset"],
        "maintenance_overdue": dash_deadlines["maintenance_overdue"],
        "wo_open": dash_wo["total"],
        "wo_mine": dash_wo["mine"],
        "deadlines_overdue": dash_deadlines["overdue"],
        "tickets_new": segnalazioni["nuove"],
    })
    # I piani periodici sono convertiti in regole: le "Verifiche" della
    # dashboard contano le scadenze dei piani, non piu' la vecchia tabella.
    kpis["verifiche_scadute"] = dash_deadlines["plan_overdue"]
    kpis["verifiche_30gg"] = dash_deadlines["plan_due_soon"]
    kpis["prossime_verifiche"] = dash_deadlines["plan_upcoming"]
    status_rows = [row for row in kpis["asset_per_stato"] if row["status"] != Asset.STATUS_RETIRED]
    categories = list(AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label"))
    family_options = categories
    # Categorie per la barra "Inventario per categoria": le piu' popolose in vista,
    # le altre dietro "+ altre" (sono decine e coprivano la pagina).
    category_counts = dict(
        Asset.objects.exclude(status=Asset.STATUS_RETIRED)
        .values_list("asset_category_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    for cat in categories:
        cat.asset_count = int(category_counts.get(cat.id) or 0)
    by_count = sorted(categories, key=lambda c: (-c.asset_count, c.label.lower()))
    categories_top = [c for c in by_count if c.asset_count][:10]
    top_ids = {c.id for c in categories_top}
    categories_rest = [c for c in categories if c.id not in top_ids]


    # Metadati widget arricchiti con valore
    widgets_all = []
    for code, meta in _WIDGET_META.items():
        widgets_all.append({
            "code": code,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "enabled": code in enabled,
            "order": enabled.index(code) if code in enabled else 999,
        })
    widgets_all.sort(key=lambda w: (0 if w["enabled"] else 1, w["order"]))

    branding = get_module_branding_context("assets")

    ctx = _assets_shell_context(request, search_action=reverse("assets:asset_list"))
    ctx.update({
        "today": today,
        "kpis": kpis,
        "enabled_widgets": enabled,
        "enabled_widgets_json": json.dumps(enabled),
        "widgets_all": widgets_all,
        "categories": categories,
        "selected_family_id": selected_family_id,
        "selected_family_label": selected_family_label,
        "family_options": family_options,
        "family_kpis": family_kpis,
        "family_distribution": family_distribution,
        "maintenance_by_family": maintenance_by_family,
        "downtime_by_family": downtime_by_family,
        "fire_safety_kpis": fire_safety_kpis,
        "maintenance_perf": maintenance_perf,
        "cose_da_fare": cose_da_fare,
        "segnalazioni": segnalazioni,
        "dash_wo": dash_wo,
        "dash_deadlines": dash_deadlines,
        "can_manage_man": can_manage_man,
        "attention_total": attention_total,
        "launcher": launcher,
        "status_rows": status_rows,
        "categories_top": categories_top,
        "categories_rest": categories_rest,
        "now": timezone.localtime(),
        "branding": branding,
        "page_title": "Dashboard",
    })
    return render(request, "assets/pages/asset_dashboard.html", ctx)


@login_required
def api_asset_dashboard_save_config(request: HttpRequest) -> JsonResponse:
    """Salva la configurazione widget dashboard per l'utente corrente."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito"}, status=405)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Payload non valido"}, status=400)

    widgets = payload.get("widgets")
    if not isinstance(widgets, list):
        return JsonResponse({"ok": False, "error": "Campo widgets obbligatorio (lista)"}, status=400)

    valid = set(AssetDashboardConfig.DEFAULT_WIDGETS)
    clean = [w for w in widgets if isinstance(w, str) and w in valid]

    cfg, _ = AssetDashboardConfig.objects.get_or_create(user=request.user)
    cfg.enabled_widgets = clean
    cfg.save(update_fields=["enabled_widgets", "updated_at"])
    return JsonResponse({"ok": True, "saved": len(clean)})


# ---------------------------------------------------------------------------
# Calendario Asset (lavori macchina + manutenzioni)
# ---------------------------------------------------------------------------

def _asset_calendar_events(asset_id: int) -> list[dict]:
    """Ritorna tutti gli eventi (lavori + manutenzioni) per un singolo asset."""
    events: list[dict] = []
    today = timezone.localdate()

    # -- Lavori macchina (Task con categoria is_machine_work=True) --
    try:
        from tasks.models import TaskExtraRef, TaskStatus
        refs = (
            TaskExtraRef.objects
            .filter(asset_id=asset_id, task__category__is_machine_work=True)
            .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
            .select_related("task__category", "task__assigned_to", "task__project")
        )
        for ref in refs:
            t = ref.task
            start = t.next_step_due or t.due_date
            end = t.due_date or t.next_step_due
            if not start:
                continue
            assignee = ""
            if t.assigned_to_id:
                assignee = t.assigned_to.get_full_name() or t.assigned_to.get_username()
            events.append({
                "id": f"task-{t.pk}",
                "title": t.title,
                "start": str(start),
                "end": str(end) if end else str(start),
                "kind": "lavoro",
                "status": t.status,
                "assignee": assignee,
                "project": t.project.name if t.project_id else "",
                "url": f"/tasks/detail/{t.pk}/",
                "color": "#2563eb" if t.status == TaskStatus.IN_PROGRESS else "#93c5fd",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Manutenzioni (WorkOrder aperti) --
    try:
        wos = (
            WorkOrder.objects
            .filter(asset_id=asset_id, status=WorkOrder.STATUS_OPEN)
            .select_related("asset")
        )
        for wo in wos:
            opened = wo.opened_at.date() if wo.opened_at else today
            events.append({
                "id": f"wo-{wo.pk}",
                "title": f"OdL: {wo.title}",
                "start": str(opened),
                "end": str(opened),
                "kind": "manutenzione",
                "status": wo.status,
                "assignee": "",
                "project": "",
                "url": f"/assets/workorders/view/{wo.pk}/",
                "color": "#f59e0b",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Verifiche periodiche pianificate --
    try:
        verifications = (
            AssetCalendarEvent.objects
            .filter(asset_id=asset_id, due_date__gte=today)
            .order_by("due_date")
        )
        for v in verifications:
            events.append({
                "id": f"ace-{v.pk}",
                "title": v.source_object_label or v.subject or "Scadenza",
                "start": str(v.due_date),
                "end": str(v.due_date),
                "kind": "scadenza",
                "status": "",
                "assignee": v.target_display_name,
                "project": "",
                "url": "",
                "color": "#10b981",
                "textColor": "#fff",
            })
    except Exception:
        pass

    # -- Manutenzioni e adempimenti pianificati (occorrenze: stessa fonte del
    #    Calendario manutenzione; prima si leggeva il motore a regole) --
    try:
        from ..services import deadline_feed as feed

        _pm_colors = {
            feed.STATE_OVERDUE: "#dc2626", feed.STATE_DUE_SOON: "#f59e0b",
            feed.STATE_PLANNED: "#2563eb", feed.STATE_OPEN: "#10b981",
        }
        for row in feed.collect(
            start=None,
            end=today + timedelta(days=400),
            filters=feed.FeedFilters(
                kinds=frozenset({feed.KIND_ORDINARY, feed.KIND_ADMINISTRATIVE}), asset_id=asset_id
            ),
            today=today,
        ):
            # Riempimento = urgenza (stato); bordo viola + marcatore 🏢 = manutenzione esterna (ditta terza).
            pm_event = {
                "id": row.key,
                "title": f"{'🏢 ' if row.is_external else ''}Manut.: {row.title}",
                "start": str(row.due_date),
                "end": str(row.due_date),
                "kind": "manutenzione_prog",
                "status": row.state,
                "assignee": row.supplier if row.is_external else row.assignee,
                "project": "",
                "url": row.detail_url,
                "color": _pm_colors.get(row.state, "#10b981"),
                "textColor": "#fff",
            }
            if row.is_external:
                pm_event["borderColor"] = "#6d28d9"
                pm_event["external"] = True
            events.append(pm_event)
    except Exception:
        pass

    return events


@login_required
def asset_calendar_json(request: HttpRequest, id: int) -> JsonResponse:
    """JSON eventi calendario per un singolo asset (usato da FullCalendar)."""
    asset = get_object_or_404(Asset, pk=id)
    events = _asset_calendar_events(asset.pk)
    return JsonResponse({"ok": True, "asset_id": asset.pk, "events": events})


@login_required
def calendario_asset(request: HttpRequest) -> HttpResponse:
    """Calendario della manutenzione: ordinarie, amministrative, licenze e contratti.

    Legge dallo stesso servizio dello Scadenzario (``services.deadline_feed``): i
    numeri del calendario e della lista sono gli stessi. Viste mese, settimana,
    elenco e per asset; i filtri vanno al server, le tipologie si accendono e
    spengono senza ricaricare.
    """
    from ..forms_maintenance import category_filter_choices
    from ..models import AssetGroup
    from ..services import deadline_feed as feed

    allowed = feed.allowed_kinds(request)
    kinds = [
        {"value": kind, "label": label}
        for kind, label in feed.KIND_LABELS.items()
        if kind in allowed
    ]
    kinds.append({"value": "machine_work", "label": "Lavori macchina"})
    reparti = list(
        Asset.objects.exclude(reparto="").values_list("reparto", flat=True).order_by("reparto").distinct()
    )
    from ..forms_maintenance import WorkOrderFromOccurrencesForm
    from ..views_maintenance import can_execute_maintenance, can_plan_maintenance

    can_plan = can_plan_maintenance(request)
    return render(request, "assets/pages/calendario_asset.html", {
        "page_title": "Calendario manutenzione",
        "can_plan": can_plan,
        "can_execute": can_plan and can_execute_maintenance(request),
        "workorder_form": WorkOrderFromOccurrencesForm() if can_plan else None,
        "kinds": kinds,
        "categories": category_filter_choices(),
        "reparti": reparti,
        "groups": AssetGroup.objects.filter(is_active=True).order_by("sort_order", "label"),
        **_assets_shell_context(request),
    })


def _calendar_range_date(raw) -> date | None:
    """FullCalendar manda ``2026-09-28T00:00:00+02:00``: interessa solo la data."""
    value = _clean_string(raw)[:10]
    try:
        return parse_date(value) if value else None
    except ValueError:
        return None


def _machine_work_events(start: date, end: date, filters) -> list[dict]:
    """Lavori macchina (attivita' KICK-OFF di categoria "lavoro macchina") sugli
    asset filtrati: non sono scadenze di manutenzione ma occupano la macchina, e
    chi pianifica deve vederli accanto. Una query per tutto il periodo."""
    try:
        from tasks.models import TaskExtraRef, TaskStatus
    except Exception:
        return []
    refs = (
        TaskExtraRef.objects.filter(asset_id__isnull=False, task__category__is_machine_work=True)
        .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
        .select_related("task", "task__assigned_to", "asset", "asset__asset_category")
    )
    if filters.category_ids is not None:
        refs = refs.filter(asset__asset_category_id__in=filters.category_ids)
    if filters.reparto:
        refs = refs.filter(asset__reparto=filters.reparto)
    if filters.group_id:
        refs = refs.filter(asset__group_memberships__group_id=filters.group_id)
    events = []
    for ref in refs[:1000]:
        task = ref.task
        begin = task.next_step_due or task.due_date
        finish = task.due_date or task.next_step_due
        if not begin or begin > end or (finish or begin) < start:
            continue
        asset = ref.asset
        assignee = ""
        if task.assigned_to_id:
            assignee = task.assigned_to.get_full_name() or task.assigned_to.get_username()
        events.append({
            "id": f"task-{task.pk}",
            "kind": "machine_work",
            "kind_label": "Lavoro macchina",
            "title": task.title,
            "start": begin.isoformat(),
            # FullCalendar: fine esclusiva, quindi il giorno dopo l'ultimo.
            "end": (finish + timedelta(days=1)).isoformat() if finish and finish > begin else None,
            "state": "open",
            "state_label": "In corso" if task.status == TaskStatus.IN_PROGRESS else "Pianificato",
            "asset_id": asset.id,
            "asset_tag": asset.asset_tag or "",
            "asset_name": asset.name or "",
            "category": asset.asset_category.label if asset.asset_category_id else "",
            "reparto": asset.reparto or "",
            "assignee": assignee,
            "url": f"/tasks/detail/{task.pk}/",
            "actions": [{"label": "Apri attività", "url": f"/tasks/detail/{task.pk}/"}],
        })
    return events


@login_required
def calendario_asset_json(request: HttpRequest) -> JsonResponse:
    """Eventi del Calendario manutenzione per il periodo visibile (``start``/``end``)."""
    from ..forms_maintenance import category_with_descendants
    from ..services import deadline_feed as feed

    today = timezone.localdate()
    start = _calendar_range_date(request.GET.get("start")) or today.replace(day=1) - timedelta(days=7)
    end = _calendar_range_date(request.GET.get("end")) or start + timedelta(days=42)
    # Il calendario non chiede mai piu' di qualche settimana: un periodo enorme e'
    # un errore o un abuso, e si tronca.
    if end <= start or (end - start).days > 400:
        end = start + timedelta(days=42)

    requested = [kind for kind in _clean_string(request.GET.get("kinds")).split(",") if kind]
    allowed = feed.allowed_kinds(request)
    category_id = _as_int(request.GET.get("category"), default=0)
    execution = _clean_string(request.GET.get("execution")).upper()
    filters = feed.FeedFilters(
        kinds=feed.parse_kinds(requested, allowed),
        category_ids=frozenset(category_with_descendants(category_id)) if category_id else None,
        reparto=_clean_string(request.GET.get("reparto")),
        group_id=_as_int(request.GET.get("group"), default=0) or None,
        execution_mode=execution if execution in {"INTERNAL", "EXTERNAL"} else "",
        include_done=_clean_string(request.GET.get("include_done")) in {"1", "true", "on"},
    )
    last_day = end - timedelta(days=1)  # FullCalendar tratta ``end`` come esclusivo.
    include_forecast = _clean_string(request.GET.get("forecast")) != "0"
    rows = feed.collect(start=start, end=last_day, filters=filters, today=today, include_forecast=include_forecast)
    events = [row.as_json(today) for row in rows]
    if not requested or "machine_work" in requested:
        events += _machine_work_events(start, last_day, filters)
    return JsonResponse({"ok": True, "today": today.isoformat(), "events": events})
