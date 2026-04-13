from __future__ import annotations

import csv
import logging
import os
import re
from datetime import date
from urllib.parse import parse_qs, unquote, urlparse

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.legacy_utils import is_legacy_admin
from core.module_branding import get_module_branding_context, handle_module_branding_post

from .models import (
    AssignmentStatus,
    CampaignStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureDocument,
    ProcedureReadEvent,
    ProcedureRevision,
    ReadEventType,
    SourceType,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_manager(request) -> bool:
    from core.legacy_models import UtenteLegacy

    legacy_user = UtenteLegacy.objects.filter(id=request.user.id).first()
    return request.user.is_superuser or is_legacy_admin(legacy_user)


# ---------------------------------------------------------------------------
# User views
# ---------------------------------------------------------------------------

@login_required
def my_assignments(request):
    status_filter = request.GET.get("status", "")
    qs = (
        ProcedureAssignment.objects.filter(user=request.user)
        .select_related("campaign", "revision__document")
        .order_by("-assigned_at")
    )
    if status_filter:
        qs = qs.filter(status=status_filter)

    is_manager = _is_manager(request)

    return render(request, "procedure_refresh/pages/my_assignments.html", {
        "assignments": qs,
        "status_filter": status_filter,
        "AssignmentStatus": AssignmentStatus,
        "is_manager": is_manager,
    })


@login_required
def assignment_detail(request, pk: int):
    assignment = get_object_or_404(
        ProcedureAssignment.objects.select_related(
            "campaign", "revision__document", "user", "assigned_by"
        ),
        pk=pk,
        user=request.user,
    )

    if request.method == "POST":
        user_note = request.POST.get("user_note", "").strip()
        confirm = bool(request.POST.get("confirm_read"))

        updates = []
        if user_note != assignment.user_note:
            assignment.user_note = user_note
            updates.append("user_note")

        if confirm and not assignment.read_confirmed_flag:
            assignment.read_confirmed_flag = True
            assignment.read_confirmed_at = timezone.now()
            assignment.status = AssignmentStatus.READ_CONFIRMED
            updates += ["read_confirmed_flag", "read_confirmed_at", "status"]

            ProcedureReadEvent.objects.create(
                assignment=assignment,
                event_type=ReadEventType.CONFIRMED,
                event_by=request.user,
                notes=user_note,
            )
            log_action(
                request,
                "conferma",
                "procedure_refresh",
                f"Presa visione confermata: {assignment.revision}",
            )
            messages.success(request, "Presa visione confermata e registrata.")
        elif updates:
            messages.success(request, "Nota salvata.")

        if updates:
            updates.append("updated_at")
            assignment.save(update_fields=updates)

        return redirect("procedure_refresh:assignment_detail", pk=pk)

    # Track open
    now = timezone.now()
    open_updates = ["last_opened_at", "open_count", "updated_at"]
    assignment.last_opened_at = now
    assignment.open_count = (assignment.open_count or 0) + 1

    if not assignment.first_opened_at:
        assignment.first_opened_at = now
        open_updates.append("first_opened_at")

    if assignment.status == AssignmentStatus.ASSIGNED:
        assignment.status = AssignmentStatus.OPENED
        open_updates.append("status")

    assignment.save(update_fields=open_updates)

    # Record open event only on first open or every 5 opens
    if assignment.open_count == 1 or assignment.open_count % 5 == 0:
        try:
            ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
            if ip and "," in ip:
                ip = ip.split(",")[0].strip()
            ProcedureReadEvent.objects.create(
                assignment=assignment,
                event_type=ReadEventType.OPENED,
                event_by=request.user,
                meta_json=f'{{"open_count": {assignment.open_count}, "ip": "{ip}"}}',
            )
        except Exception:
            pass

    return render(request, "procedure_refresh/pages/assignment_detail.html", {
        "assignment": assignment,
        "revision": assignment.revision,
        "document": assignment.revision.document,
    })


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------

@login_required
def admin_dashboard(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="procedure_refresh",
            redirect_to="procedure_refresh:admin_dashboard",
            audit_module="procedure_refresh",
            fallback_label="Procedure Refresh",
        )
        if branding_response is not None:
            return branding_response

    n_documents = ProcedureDocument.objects.filter(is_active=True).count()
    n_campaigns = ProcedureCampaign.objects.count()
    n_published = ProcedureCampaign.objects.filter(status=CampaignStatus.PUBLISHED).count()
    n_assignments = ProcedureAssignment.objects.count()
    n_confirmed = ProcedureAssignment.objects.filter(
        status=AssignmentStatus.READ_CONFIRMED
    ).count()
    n_pending = ProcedureAssignment.objects.filter(
        status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]
    ).count()
    n_overdue = ProcedureAssignment.objects.filter(status=AssignmentStatus.OVERDUE).count()

    recent_campaigns = (
        ProcedureCampaign.objects.select_related("created_by").order_by("-created_at")[:5]
    )

    return render(request, "procedure_refresh/pages/admin_dashboard.html", {
        "n_documents": n_documents,
        "n_campaigns": n_campaigns,
        "n_published": n_published,
        "n_assignments": n_assignments,
        "n_confirmed": n_confirmed,
        "n_pending": n_pending,
        "n_overdue": n_overdue,
        "recent_campaigns": recent_campaigns,
        "CampaignStatus": CampaignStatus,
        **get_module_branding_context("procedure_refresh", fallback_label="Procedure Refresh"),
    })


@login_required
def document_list(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    qs = (
        ProcedureDocument.objects.prefetch_related("revisions")
        .order_by("document_type", "code")
    )
    return render(request, "procedure_refresh/pages/document_list.html", {
        "documents": qs,
    })


@login_required
def document_form(request, pk: int | None = None):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    document = get_object_or_404(ProcedureDocument, pk=pk) if pk else None

    if request.method == "POST":
        code = request.POST.get("code", "").strip().upper()
        title = request.POST.get("title", "").strip()
        category = request.POST.get("category", "").strip()
        document_type = request.POST.get("document_type", "MT").strip()
        owner_department = request.POST.get("owner_department", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = bool(request.POST.get("is_active"))
        requires_acknowledgement = bool(request.POST.get("requires_acknowledgement"))

        # Campi prima revisione (solo creazione nuovo documento)
        is_new = pk is None
        rev_code = request.POST.get("revision_code", "").strip()
        rev_date = request.POST.get("revision_date", "").strip()
        eff_date = request.POST.get("effective_date", "").strip()
        source_type = request.POST.get("source_type", "sharepoint").strip()
        source_url = request.POST.get("source_url", "").strip()
        source_path = request.POST.get("source_path", "").strip()
        file_name = request.POST.get("file_name", "").strip()
        file_hash = request.POST.get("file_hash", "").strip()
        with_revision = is_new and bool(request.POST.get("with_revision"))

        errors = []
        if not code:
            errors.append("Il codice documento è obbligatorio.")
        if not title:
            errors.append("Il titolo è obbligatorio.")

        qs_check = ProcedureDocument.objects.filter(code=code)
        if pk:
            qs_check = qs_check.exclude(pk=pk)
        if qs_check.exists():
            errors.append(f"Esiste già un documento con codice '{code}'.")

        if with_revision:
            if not rev_code:
                errors.append("Codice revisione obbligatorio.")
            if not rev_date:
                errors.append("Data revisione obbligatoria.")
            if not eff_date:
                errors.append("Data efficacia obbligatoria.")
            if not file_name:
                errors.append("Nome file obbligatorio.")
            if source_type == "sharepoint" and not source_url:
                errors.append("URL SharePoint obbligatorio per sorgente SharePoint.")
            if source_type == "fileserver" and not source_path:
                errors.append("Path file server obbligatorio per sorgente File server.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            from django.db import transaction
            from datetime import date as _date
            if document is None:
                document = ProcedureDocument()
            document.code = code
            document.title = title
            document.category = category
            document.document_type = document_type
            document.owner_department = owner_department
            document.description = description
            document.is_active = is_active
            document.requires_acknowledgement = requires_acknowledgement
            with transaction.atomic():
                document.save()
                if with_revision:
                    ProcedureRevision.objects.create(
                        document=document,
                        revision_code=rev_code,
                        revision_date=_date.fromisoformat(rev_date),
                        effective_date=_date.fromisoformat(eff_date),
                        source_type=source_type,
                        source_url=source_url if source_type == "sharepoint" else "",
                        source_path=source_path if source_type == "fileserver" else "",
                        file_name=file_name,
                        file_hash=file_hash,
                        is_current=True,
                        published_by=request.user,
                    )
            action = "modifica" if pk else "crea"
            log_action(request, action, "procedure_refresh", f"Documento {document.code}")
            messages.success(request, "Documento salvato." if pk else "Documento e revisione creati.")
            return redirect("procedure_refresh:document_list")

    return render(request, "procedure_refresh/pages/document_form.html", {
        "document": document,
    })


@login_required
@require_POST
def document_delete(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    document = get_object_or_404(ProcedureDocument, pk=pk)
    code = document.code
    document.is_active = False
    document.save(update_fields=["is_active", "updated_at"])
    log_action(request, "disattiva", "procedure_refresh", f"Documento {code} disattivato")
    messages.success(request, f"Documento {code} disattivato.")
    return redirect("procedure_refresh:document_list")


@login_required
def revision_form(request, doc_pk: int, pk: int | None = None):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    document = get_object_or_404(ProcedureDocument, pk=doc_pk)
    revision = (
        get_object_or_404(ProcedureRevision, pk=pk, document=document) if pk else None
    )

    if request.method == "POST":
        revision_code = request.POST.get("revision_code", "").strip()
        revision_date_str = request.POST.get("revision_date", "").strip()
        effective_date_str = request.POST.get("effective_date", "").strip()
        source_type = request.POST.get("source_type", SourceType.SHAREPOINT).strip()
        source_url = request.POST.get("source_url", "").strip()
        source_path = request.POST.get("source_path", "").strip()
        file_name = request.POST.get("file_name", "").strip()
        file_hash = request.POST.get("file_hash", "").strip()
        is_current = bool(request.POST.get("is_current"))

        errors = []
        if not revision_code:
            errors.append("Il codice revisione è obbligatorio.")
        if not revision_date_str:
            errors.append("La data revisione è obbligatoria.")
        if not effective_date_str:
            errors.append("La data efficacia è obbligatoria.")
        if not file_name:
            errors.append("Il nome file è obbligatorio.")
        if source_type == SourceType.SHAREPOINT and not source_url:
            errors.append("URL SharePoint obbligatorio per sorgente SharePoint.")
        if source_type == SourceType.FILESERVER and not source_path:
            errors.append("Path obbligatorio per sorgente file server.")

        revision_date = None
        effective_date = None
        if revision_date_str:
            try:
                revision_date = date.fromisoformat(revision_date_str)
            except ValueError:
                errors.append("Data revisione non valida.")
        if effective_date_str:
            try:
                effective_date = date.fromisoformat(effective_date_str)
            except ValueError:
                errors.append("Data efficacia non valida.")

        qs_check = ProcedureRevision.objects.filter(
            document=document, revision_code=revision_code
        )
        if pk:
            qs_check = qs_check.exclude(pk=pk)
        if qs_check.exists():
            errors.append(f"Esiste già la revisione '{revision_code}' per questo documento.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            if revision is None:
                revision = ProcedureRevision(document=document, published_by=request.user)
            revision.revision_code = revision_code
            revision.revision_date = revision_date
            revision.effective_date = effective_date
            revision.source_type = source_type
            revision.source_url = source_url
            revision.source_path = source_path
            revision.file_name = file_name
            revision.file_hash = file_hash
            revision.is_current = is_current
            revision.save()
            action = "modifica" if pk else "crea"
            log_action(
                request, action, "procedure_refresh",
                f"Revisione {document.code} rev.{revision_code}"
            )
            messages.success(request, "Revisione salvata.")
            return redirect("procedure_refresh:document_list")

    return render(request, "procedure_refresh/pages/revision_form.html", {
        "document": document,
        "revision": revision,
        "SourceType": SourceType,
    })


@login_required
def campaign_list(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    qs = ProcedureCampaign.objects.select_related("created_by").order_by("-created_at")
    return render(request, "procedure_refresh/pages/campaign_list.html", {
        "campaigns": qs,
        "CampaignStatus": CampaignStatus,
    })


@login_required
def campaign_form(request, pk: int | None = None):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk) if pk else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        start_date_str = request.POST.get("start_date", "").strip()
        due_date_str = request.POST.get("due_date", "").strip()

        errors = []
        if not name:
            errors.append("Il nome campagna è obbligatorio.")
        if not start_date_str:
            errors.append("La data inizio è obbligatoria.")
        if not due_date_str:
            errors.append("La data scadenza è obbligatoria.")

        start_date = None
        due_date = None
        if start_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
            except ValueError:
                errors.append("Data inizio non valida.")
        if due_date_str:
            try:
                due_date = date.fromisoformat(due_date_str)
            except ValueError:
                errors.append("Data scadenza non valida.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            if campaign is None:
                campaign = ProcedureCampaign(
                    created_by=request.user, status=CampaignStatus.DRAFT
                )
            campaign.name = name
            campaign.description = description
            campaign.start_date = start_date
            campaign.due_date = due_date
            campaign.save()
            action = "modifica" if pk else "crea"
            log_action(request, action, "procedure_refresh", f"Campagna '{name}'")
            messages.success(request, "Campagna salvata.")
            return redirect("procedure_refresh:campaign_detail", pk=campaign.pk)

    return render(request, "procedure_refresh/pages/campaign_form.html", {
        "campaign": campaign,
    })


@login_required
def campaign_detail(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk)
    campaign_docs = campaign.campaign_documents.select_related(
        "revision__document"
    ).order_by("display_order")
    assignments = campaign.assignments.select_related(
        "user", "revision__document"
    ).order_by("user__last_name", "user__first_name")

    already_in = [cd.revision_id for cd in campaign_docs]
    available_revisions = (
        ProcedureRevision.objects.filter(document__is_active=True)
        .exclude(id__in=already_in)
        .select_related("document")
        .order_by("document__document_type", "document__code", "-revision_date")
    )

    users = User.objects.filter(is_active=True).order_by("last_name", "first_name")

    n_total = assignments.count()
    n_confirmed = assignments.filter(status=AssignmentStatus.READ_CONFIRMED).count()
    n_pending = assignments.filter(
        status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]
    ).count()

    return render(request, "procedure_refresh/pages/campaign_detail.html", {
        "campaign": campaign,
        "campaign_docs": campaign_docs,
        "assignments": assignments,
        "available_revisions": available_revisions,
        "users": users,
        "n_total": n_total,
        "n_confirmed": n_confirmed,
        "n_pending": n_pending,
        "CampaignStatus": CampaignStatus,
        "AssignmentStatus": AssignmentStatus,
    })


@login_required
@require_POST
def campaign_add_document(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk)
    revision_id = request.POST.get("revision_id", "").strip()

    if not revision_id:
        messages.error(request, "Seleziona una revisione.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    try:
        revision = ProcedureRevision.objects.select_related("document").get(
            pk=int(revision_id)
        )
    except (ProcedureRevision.DoesNotExist, ValueError):
        messages.error(request, "Revisione non trovata.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    is_mandatory = bool(request.POST.get("is_mandatory"))
    _, created = ProcedureCampaignDocument.objects.get_or_create(
        campaign=campaign,
        revision=revision,
        defaults={"is_mandatory": is_mandatory},
    )
    if created:
        log_action(
            request, "aggiungi", "procedure_refresh",
            f"Documento {revision} aggiunto a campagna '{campaign.name}'"
        )
        messages.success(request, "Documento aggiunto alla campagna.")
    else:
        messages.warning(request, "Documento già presente nella campagna.")
    return redirect("procedure_refresh:campaign_detail", pk=pk)


@login_required
@require_POST
def campaign_remove_document(request, pk: int, cd_pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    cd = get_object_or_404(ProcedureCampaignDocument, pk=cd_pk, campaign_id=pk)
    rev_str = str(cd.revision)
    cd.delete()
    log_action(
        request, "rimuovi", "procedure_refresh",
        f"Documento {rev_str} rimosso da campagna"
    )
    messages.success(request, "Documento rimosso dalla campagna.")
    return redirect("procedure_refresh:campaign_detail", pk=pk)


@login_required
@require_POST
def campaign_publish(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk)
    if campaign.status != CampaignStatus.DRAFT:
        messages.error(request, "Solo le campagne in bozza possono essere pubblicate.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    campaign.status = CampaignStatus.PUBLISHED
    campaign.published_at = timezone.now()
    campaign.save(update_fields=["status", "published_at", "updated_at"])
    log_action(request, "pubblica", "procedure_refresh", f"Campagna '{campaign.name}' pubblicata")
    messages.success(request, "Campagna pubblicata.")
    return redirect("procedure_refresh:campaign_detail", pk=pk)


@login_required
@require_POST
def campaign_close(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk)
    if campaign.status != CampaignStatus.PUBLISHED:
        messages.error(request, "Solo le campagne pubblicate possono essere chiuse.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    campaign.status = CampaignStatus.CLOSED
    campaign.closed_at = timezone.now()
    campaign.save(update_fields=["status", "closed_at", "updated_at"])
    log_action(request, "chiudi", "procedure_refresh", f"Campagna '{campaign.name}' chiusa")
    messages.success(request, "Campagna chiusa.")
    return redirect("procedure_refresh:campaign_detail", pk=pk)


@login_required
@require_POST
def assign_users(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    campaign = get_object_or_404(ProcedureCampaign, pk=pk)
    user_ids = request.POST.getlist("user_ids")
    revision_id = request.POST.get("revision_id", "").strip()
    due_date_str = request.POST.get("due_date", "").strip()

    if not user_ids or not revision_id:
        messages.error(request, "Seleziona almeno un utente e una revisione.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    try:
        revision = ProcedureRevision.objects.get(pk=int(revision_id))
    except (ProcedureRevision.DoesNotExist, ValueError):
        messages.error(request, "Revisione non trovata.")
        return redirect("procedure_refresh:campaign_detail", pk=pk)

    due_date = None
    if due_date_str:
        try:
            due_date = date.fromisoformat(due_date_str)
        except ValueError:
            pass

    created_count = 0
    for uid in user_ids:
        try:
            user = User.objects.get(pk=int(uid), is_active=True)
        except (User.DoesNotExist, ValueError):
            continue
        _, created = ProcedureAssignment.objects.get_or_create(
            campaign=campaign,
            revision=revision,
            user=user,
            defaults={
                "assigned_by": request.user,
                "due_date": due_date or campaign.due_date,
                "status": AssignmentStatus.ASSIGNED,
            },
        )
        if created:
            created_count += 1

    log_action(
        request, "assegna", "procedure_refresh",
        f"{created_count} assegnazioni create per campagna '{campaign.name}'"
    )
    messages.success(request, f"{created_count} assegnazioni create.")
    return redirect("procedure_refresh:campaign_detail", pk=pk)


@login_required
@require_POST
def cancel_assignment(request, pk: int):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    assignment = get_object_or_404(ProcedureAssignment, pk=pk)
    if assignment.status == AssignmentStatus.READ_CONFIRMED:
        messages.error(request, "Non è possibile annullare un'assegnazione già confermata.")
        return redirect("procedure_refresh:campaign_detail", pk=assignment.campaign_id)

    assignment.status = AssignmentStatus.CANCELLED
    assignment.save(update_fields=["status", "updated_at"])
    ProcedureReadEvent.objects.create(
        assignment=assignment,
        event_type=ReadEventType.REASSIGNED,
        event_by=request.user,
        notes="Annullata dal manager.",
    )
    log_action(
        request, "annulla", "procedure_refresh",
        f"Assegnazione {assignment.pk} annullata"
    )
    messages.success(request, "Assegnazione annullata.")
    return redirect("procedure_refresh:campaign_detail", pk=assignment.campaign_id)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@login_required
def report_user(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    user_id = request.GET.get("user_id", "")
    users = User.objects.filter(is_active=True).order_by("last_name", "first_name")

    assignments = []
    selected_user = None
    if user_id:
        try:
            selected_user = User.objects.get(pk=int(user_id))
            assignments = (
                ProcedureAssignment.objects.filter(user=selected_user)
                .select_related("campaign", "revision__document")
                .order_by("-assigned_at")
            )
        except (User.DoesNotExist, ValueError):
            pass

    return render(request, "procedure_refresh/pages/report_user.html", {
        "users": users,
        "selected_user": selected_user,
        "assignments": assignments,
        "AssignmentStatus": AssignmentStatus,
    })


@login_required
def report_document(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    doc_id = request.GET.get("doc_id", "")
    documents = ProcedureDocument.objects.filter(is_active=True).order_by("document_type", "code")

    assignments = []
    selected_doc = None
    if doc_id:
        try:
            selected_doc = ProcedureDocument.objects.get(pk=int(doc_id))
            assignments = (
                ProcedureAssignment.objects.filter(revision__document=selected_doc)
                .select_related("campaign", "revision", "user")
                .order_by("-assigned_at")
            )
        except (ProcedureDocument.DoesNotExist, ValueError):
            pass

    return render(request, "procedure_refresh/pages/report_document.html", {
        "documents": documents,
        "selected_doc": selected_doc,
        "assignments": assignments,
        "AssignmentStatus": AssignmentStatus,
    })


@login_required
def report_campaign(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    camp_id = request.GET.get("camp_id", "")
    campaigns = ProcedureCampaign.objects.order_by("-created_at")

    assignments = []
    selected_camp = None
    if camp_id:
        try:
            selected_camp = ProcedureCampaign.objects.get(pk=int(camp_id))
            assignments = (
                ProcedureAssignment.objects.filter(campaign=selected_camp)
                .select_related("revision__document", "user")
                .order_by("user__last_name", "user__first_name")
            )
        except (ProcedureCampaign.DoesNotExist, ValueError):
            pass

    return render(request, "procedure_refresh/pages/report_campaign.html", {
        "campaigns": campaigns,
        "selected_camp": selected_camp,
        "assignments": assignments,
        "AssignmentStatus": AssignmentStatus,
    })


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

class _Echo:
    def write(self, value):
        return value


@login_required
def export_csv(request):
    if not _is_manager(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("procedure_refresh:my_assignments")

    report_type = request.GET.get("type", "assignments")
    writer = csv.writer(_Echo())

    if report_type == "assignments":
        headers = [
            "ID", "Utente", "Email", "Campagna",
            "Documento", "Codice doc", "Tipo doc", "Revisione",
            "Stato", "Assegnato il", "Scadenza",
            "Prima apertura", "Ultima apertura", "Confermato il",
            "Nota utente",
        ]

        def rows():
            yield writer.writerow(headers)
            qs = ProcedureAssignment.objects.select_related(
                "user", "campaign", "revision__document"
            ).order_by("campaign__name", "user__last_name")
            for a in qs:
                yield writer.writerow([
                    a.pk,
                    a.user.get_full_name() or a.user.username,
                    a.user.email,
                    a.campaign.name,
                    a.revision.document.title,
                    a.revision.document.code,
                    a.revision.document.document_type,
                    a.revision.revision_code,
                    a.get_status_display(),
                    a.assigned_at.strftime("%d/%m/%Y %H:%M") if a.assigned_at else "",
                    a.due_date.strftime("%d/%m/%Y") if a.due_date else "",
                    a.first_opened_at.strftime("%d/%m/%Y %H:%M") if a.first_opened_at else "",
                    a.last_opened_at.strftime("%d/%m/%Y %H:%M") if a.last_opened_at else "",
                    a.read_confirmed_at.strftime("%d/%m/%Y %H:%M") if a.read_confirmed_at else "",
                    a.user_note,
                ])

    else:
        headers = [
            "ID", "Campagna", "Stato", "Inizio", "Scadenza",
            "Totale", "Confermati", "In attesa",
        ]

        def rows():
            yield writer.writerow(headers)
            for camp in ProcedureCampaign.objects.order_by("-created_at"):
                total = camp.assignments.count()
                confirmed = camp.assignments.filter(
                    status=AssignmentStatus.READ_CONFIRMED
                ).count()
                pending = camp.assignments.filter(
                    status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]
                ).count()
                yield writer.writerow([
                    camp.pk,
                    camp.name,
                    camp.get_status_display(),
                    camp.start_date.strftime("%d/%m/%Y"),
                    camp.due_date.strftime("%d/%m/%Y"),
                    total,
                    confirmed,
                    pending,
                ])

    resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = (
        f'attachment; filename="procedure_refresh_{report_type}.csv"'
    )
    log_action(request, "export", "procedure_refresh", f"Export CSV tipo={report_type}")
    return resp


# ---------------------------------------------------------------------------
# API — Parse SharePoint URL (auto-fill metadati revisione)
# ---------------------------------------------------------------------------

def _parse_sharepoint_url_local(url: str) -> dict:
    """Estrae metadati da un URL SharePoint tramite parsing locale (no API)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    file_path = unquote(params.get("id", [""])[0])
    file_name = file_path.rsplit("/", 1)[-1] if file_path else ""

    # Codice revisione: Rev.2, Rev2, Rev 2, r02, ecc.
    rev_match = re.search(r"[Rr]ev\.?\s*(\d+[a-zA-Z]?)", file_name)
    revision_code = f"Rev.{rev_match.group(1)}" if rev_match else ""

    # Codice documento: MOD.165, MT-001, MTSI.003, …
    code_match = re.match(r"^([A-Z]{2,}[.\-]\d+)", file_name)
    code_suggestion = code_match.group(1) if code_match else ""

    # Titolo suggerito: filename senza estensione e senza "Rev.X"
    title_suggestion = re.sub(r"\s*[-_]?\s*[Rr]ev\.?\s*\d+[a-zA-Z]?", "", file_name)
    title_suggestion = re.sub(r"\.[^.]+$", "", title_suggestion).strip(" -_")

    # Cartella padre (utile come categoria/reparto)
    parent_path = unquote(params.get("parent", [""])[0])
    folder = parent_path.rsplit("/", 1)[-1] if parent_path else ""

    # Dati per chiamata Graph
    hostname = parsed.hostname or ""
    site_match = re.match(r"(/sites/[^/]+)", parsed.path)
    site_path = site_match.group(1) if site_match else ""

    return {
        "file_name": file_name,
        "file_path": file_path,
        "revision_code": revision_code,
        "code_suggestion": code_suggestion,
        "title_suggestion": title_suggestion,
        "folder": folder,
        "hostname": hostname,
        "site_path": site_path,
        "graph_ok": False,
    }


def _enrich_with_graph(result: dict) -> None:
    """Arricchisce il risultato con metadati Graph API (best-effort, in-place)."""
    import requests as _requests
    from core.graph_utils import acquire_graph_token, is_placeholder_value

    tenant_id = os.environ.get("GRAPH_TENANT_ID", "")
    client_id = os.environ.get("GRAPH_CLIENT_ID", "")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET", "")

    if any(is_placeholder_value(v) for v in [tenant_id, client_id, client_secret]):
        return

    hostname = result.get("hostname", "")
    site_path = result.get("site_path", "")
    file_path = result.get("file_path", "")
    if not all([hostname, site_path, file_path]):
        return

    token = acquire_graph_token(tenant_id, client_id, client_secret)
    headers = {"Authorization": f"Bearer {token}"}

    # Risolve site ID
    site_resp = _requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}",
        headers=headers, timeout=10,
    )
    if not site_resp.ok:
        result["graph_error"] = f"Site lookup: {site_resp.status_code}"
        return
    site_id = site_resp.json().get("id", "")

    # Percorso relativo al root del sito (rimuove /sites/<nome>)
    relative_path = file_path
    if site_path and file_path.startswith(site_path):
        relative_path = file_path[len(site_path):]

    # Recupera metadati file
    item_resp = _requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:{relative_path}",
        headers=headers, timeout=10,
    )
    if not item_resp.ok:
        result["graph_error"] = f"Drive item: {item_resp.status_code}"
        return

    item = item_resp.json()

    # Date
    from datetime import datetime as _dt
    for key, field in [("lastModifiedDateTime", "revision_date"), ("createdDateTime", "created_date")]:
        if key in item:
            try:
                d = _dt.fromisoformat(item[key].replace("Z", "+00:00")).date().isoformat()
                result[field] = d
                if field == "revision_date":
                    result["effective_date"] = d
            except Exception:
                pass

    # Hash
    hashes = item.get("file", {}).get("hashes", {})
    result["file_hash"] = hashes.get("sha256Hash") or hashes.get("quickXorHash") or ""

    # Autore ultima modifica
    author = item.get("lastModifiedBy", {}).get("user", {}).get("displayName", "")
    if author:
        result["author"] = author

    # Dimensione
    if "size" in item:
        size = item["size"]
        result["file_size_bytes"] = size
        if size < 1024:
            result["file_size_label"] = f"{size} B"
        elif size < 1024 * 1024:
            result["file_size_label"] = f"{size / 1024:.1f} KB"
        else:
            result["file_size_label"] = f"{size / 1024 / 1024:.1f} MB"

    result["graph_ok"] = True


@login_required
def api_parse_sharepoint_url(request):
    """GET /procedure-refresh/api/parse-sharepoint-url/?url=...
    Restituisce metadati del documento SharePoint per auto-compilare il form revisione.
    """
    if not _is_manager(request):
        return JsonResponse({"ok": False, "error": "Non autorizzato."}, status=403)

    url_raw = request.GET.get("url", "").strip()
    if not url_raw:
        return JsonResponse({"ok": False, "error": "Parametro 'url' mancante."})

    if "sharepoint.com" not in url_raw.lower():
        return JsonResponse({"ok": False, "error": "URL non riconosciuto come SharePoint."})

    result = _parse_sharepoint_url_local(url_raw)

    try:
        _enrich_with_graph(result)
    except Exception as exc:
        logger.warning("Graph enrichment fallito per %s: %s", url_raw[:80], exc)
        result["graph_error"] = str(exc)

    # Rimuovi campi interni non utili al client
    result.pop("file_path", None)
    result.pop("hostname", None)
    result.pop("site_path", None)

    return JsonResponse({"ok": True, **result})
