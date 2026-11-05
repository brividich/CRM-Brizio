"""Documento VRF: caricamento, compilazione, download."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action
from core.upload_mime import (
    UploadMimeValidationError,
    safe_filename,
    validate_extension_and_mime,
)

from ..models import (
    TaskImpostazioni,
    VRFDocStatus,
    VRFRiskAssessment,
)
from ..access import (
    can_manage_project,
    scoped_projects_queryset,
    task_permissions_required,
)
from ._shared import (
    _tasks_shell_context,
    _vrf_status_detail,
)

logger = logging.getLogger(__name__)


def _parse_vrf_excel(file_obj) -> dict:
    """Estrae i campi identificativi da un MOD.073 VRF caricato.

    Celle in vrf_catalog.HEADER_CELLS (J2 preventivo, R2 versione, C3 P/N,
    F3 descrizione, H3 esp, N3 cliente). Restituisce stringhe, mai None.
    """
    import io
    import openpyxl

    from ..vrf_generator import read_header, select_sheet

    result = {
        "part_number": "",
        "vrf_description": "",
        "vrf_esp": "",
        "vrf_quote_number": "",
        "versione": "",
        "client_name": "",
    }
    try:
        data = file_obj.read() if hasattr(file_obj, "read") else file_obj
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        try:
            result.update(read_header(select_sheet(wb)))
        finally:
            wb.close()
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# VRF Document upload / management
# ---------------------------------------------------------------------------

@task_permissions_required("tasks_view")
def project_vrf_upload(request, project_id: int):
    """Upload documento VRF per un progetto: GET mostra form, POST gestisce upload/confirm/later/not_required."""
    project_qs = scoped_projects_queryset(request)
    project = get_object_or_404(project_qs, pk=project_id)
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    # SEC (audit B4): "//evil.example" inizia con "/" ma porta fuori dal portale:
    # controllo sull'host come nel resto del codice.
    from core.redirects import safe_next

    next_url = safe_next(
        request,
        request.GET.get("next") or request.POST.get("next"),
        reverse("tasks:project_gantt", kwargs={"project_id": project_id}),
    )

    session_key = f"tasks_vrf_preview_{project_id}"

    if request.method == "GET":
        request.session.pop(session_key, None)
        return render(request, "tasks/project_vrf_upload.html", {
            **_tasks_shell_context(request, active="vrf", project=project),
            "page_title": f"Documento VRF - {project.name}",
            "project": project,
            "vrf_detail": vrf_detail,
            "preview": None,
            "next_url": next_url,
        })

    if not can_manage_project(request, project):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )

    action = request.POST.get("action", "")

    # --- action: upload → parse e mostra preview ---
    if action == "upload":
        uploaded = request.FILES.get("vrf_file")
        if not uploaded:
            messages.error(request, "Nessun file selezionato.")
            return redirect(request.get_full_path())

        try:
            validate_extension_and_mime(
                uploaded,
                allowed_extensions={".xlsx", ".xls"},
                allowed_mimes={
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel",
                    "application/octet-stream",
                    "application/zip",  # xlsx e' uno zip
                    "application/x-zip-compressed",
                },
                max_bytes=20 * 1024 * 1024,
                label=safe_filename(uploaded.name) or "Documento VRF",
                allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            messages.error(request, str(exc))
            return redirect(request.get_full_path())

        try:
            file_bytes = uploaded.read()
            extracted = _parse_vrf_excel(file_bytes)
        except Exception:
            messages.error(request, "Impossibile leggere il file Excel. Verifica che sia un MOD.073 valido.")
            return redirect(request.get_full_path())

        request.session[session_key] = {
            "filename": uploaded.name,
            "file_bytes_b64": __import__("base64").b64encode(file_bytes).decode(),
            "extracted": extracted,
        }

        return render(request, "tasks/project_vrf_upload.html", {
            **_tasks_shell_context(request, active="vrf", project=project),
            "page_title": f"Documento VRF - {project.name}",
            "project": project,
            "vrf_detail": vrf_detail,
            "preview": extracted,
            "filename": uploaded.name,
            "next_url": next_url,
        })

    # --- action: confirm → salva file e aggiorna progetto ---
    if action == "confirm":
        session_data = request.session.pop(session_key, None)
        if not session_data:
            messages.error(request, "Sessione scaduta. Ricarica il file.")
            return redirect(request.get_full_path())

        import base64
        from django.core.files.base import ContentFile
        from django.utils import timezone as tz

        extracted = session_data["extracted"]
        filename = session_data["filename"]
        file_bytes = base64.b64decode(session_data["file_bytes_b64"])

        project.vrf_file.save(filename, ContentFile(file_bytes), save=False)
        project.vrf_original_name = filename
        project.vrf_uploaded_at = tz.now()
        project.vrf_status = VRFDocStatus.UPLOADED

        if extracted.get("client_name"):
            project.client_name = extracted["client_name"]
        if extracted.get("part_number"):
            project.part_number = extracted["part_number"]
        if extracted.get("versione"):
            project.versione = extracted["versione"]
        if extracted.get("vrf_quote_number"):
            project.vrf_quote_number = extracted["vrf_quote_number"]
        if extracted.get("vrf_description"):
            project.vrf_description = extracted["vrf_description"]
        if extracted.get("vrf_esp"):
            project.vrf_esp = extracted["vrf_esp"]

        project.save()
        log_action(
            request,
            "upload_vrf",
            "tasks",
            {
                "message": f"Caricato documento VRF '{filename}' per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
                "filename": filename,
            },
        )
        messages.success(request, f"Documento VRF caricato correttamente. Dati del kickoff aggiornati da '{filename}'.")
        return redirect(next_url)

    # --- action: discard → torna al form upload ---
    if action == "discard":
        request.session.pop(session_key, None)
        return redirect(request.get_full_path())

    # --- action: later → resta PENDING ---
    if action == "later":
        request.session.pop(session_key, None)
        log_action(
            request,
            "vrf_remind_skipped",
            "tasks",
            {
                "message": f"VRF rimandato per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
            },
        )
        messages.info(request, "Documento VRF rimandato. Ricordati di caricarlo al piu presto.")
        return redirect(next_url)

    # --- action: not_required ---
    if action == "not_required":
        request.session.pop(session_key, None)
        project.vrf_status = VRFDocStatus.NOT_REQUIRED
        project.save(update_fields=["vrf_status"])
        log_action(
            request,
            "vrf_not_required",
            "tasks",
            {
                "message": f"VRF marcato come 'non richiesto' per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
            },
        )
        messages.success(request, "Kickoff marcato come 'VRF non richiesto'.")
        return redirect(next_url)

    return redirect(request.get_full_path())


# ---------------------------------------------------------------------------
# VRF compilazione online (MOD.073 «Scheda valutazione rischi e fornitura»)
# ---------------------------------------------------------------------------

def _vrf_data_from_post(post, vrf_catalog) -> dict:
    """Scheda (schema 2) dai campi del form: P per rischio, azioni, firme."""
    data = vrf_catalog.default_scores()
    for risk in vrf_catalog.RISKS:
        data["risks"][risk["code"]]["p"] = vrf_catalog.clamp_p(post.get(f"p_{risk['code']}", "").strip())
    data["azioni"] = [
        post.get(f"azione_{idx}", "").strip()[:500] for idx in range(len(vrf_catalog.AZIONI_CELLS))
    ]
    data["firme"] = {
        key: post.get(f"firma_{key}", "").strip()[:120]
        for key in ("in1", "in1_data", "em", "em_data")
    }
    return data


@task_permissions_required("tasks_view")
def project_vrf_compile(request, project_id: int):
    """Compila la scheda VRF online e genera l'xlsx a conferma.

    GET: mostra la scheda (con eventuale bozza salvata su VRFRiskAssessment).
    POST action=save_draft: aggiorna la valutazione senza generare file.
    POST action=skip_with_reminder: salva la bozza e torna al Gantt (VRF resta da fare).
    POST action=confirm: richiede la P di tutti i 9 rischi, genera l'xlsx,
    lo salva su project.vrf_file e marca UPLOADED.
    """
    from .. import vrf_catalog
    from ..vrf_generator import build_vrf_xlsx, parse_vrf_xlsx, vrf_filename_for

    project_qs = scoped_projects_queryset(request)
    project = get_object_or_404(project_qs, pk=project_id)
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    assessment = getattr(project, "vrf_assessment", None)
    prefilled_from_xlsx = False
    if assessment is None:
        initial_data = vrf_catalog.default_scores()
        if request.method == "GET" and project.vrf_file and project.vrf_file.name:
            try:
                with project.vrf_file.open("rb") as fh:
                    parsed = parse_vrf_xlsx(fh)
                prefilled_from_xlsx = parsed != vrf_catalog.default_scores()
                initial_data = parsed
            except Exception:
                initial_data = vrf_catalog.default_scores()
        assessment = VRFRiskAssessment(project=project, data=initial_data)

    if request.method == "POST":
        if not can_manage_project(request, project):
            return render(
                request,
                "core/pages/forbidden.html",
                {"page_title": "Accesso negato"},
                status=403,
            )
        action = request.POST.get("action", "")
        data = _vrf_data_from_post(request.POST, vrf_catalog)
        totals = vrf_catalog.compute_totals(data)

        if action == "confirm" and not totals["compiled"]:
            assessment.data = data
            assessment.recompute_totals()
            assessment.save()
            messages.error(
                request,
                "Per confermare scegli la Probabilità di tutti i rischi (N/A se non si applica). "
                f"Mancano: {', '.join(totals['missing'])}.",
            )
            return redirect("tasks:project_vrf_compile", project_id=project_id)

        assessment.data = data
        assessment.recompute_totals()
        assessment.compiled_by = request.user if getattr(request.user, "is_authenticated", False) else None
        assessment.compiled_at = timezone.now()
        assessment.save()

        if action == "save_draft":
            log_action(request, "vrf_compiled_draft", "tasks", {
                "project_id": project.id,
                "message": f"Bozza VRF online salvata per kickoff #{project.id}",
            })
            messages.success(request, "Bozza VRF salvata. Il Totale Rischio è aggiornato.")
            return redirect("tasks:project_vrf_compile", project_id=project_id)

        if action == "skip_with_reminder":
            log_action(request, "vrf_skipped_with_reminder", "tasks", {
                "project_id": project.id,
                "message": f"VRF rimandato per kickoff #{project.id}, bozza salvata, stato PENDING",
            })
            messages.info(
                request,
                "Bozza VRF salvata. Il sistema ti ricorderà di completare la scheda VRF "
                "secondo le impostazioni del modulo (promemoria e blocco progressivo).",
            )
            return redirect("tasks:project_gantt", project_id=project_id)

        if action == "confirm":
            from django.core.files.base import ContentFile
            try:
                xlsx_bytes = build_vrf_xlsx(project, assessment)
            except FileNotFoundError:
                messages.error(request, "Template VRF non disponibile sul server. Contattare l'amministratore.")
                return redirect("tasks:project_vrf_compile", project_id=project_id)

            filename = vrf_filename_for(project)
            project.vrf_file.save(filename, ContentFile(xlsx_bytes), save=False)
            project.vrf_original_name = filename
            project.vrf_uploaded_at = timezone.now()
            project.vrf_status = VRFDocStatus.UPLOADED
            project.save()

            log_action(request, "vrf_compiled_inline", "tasks", {
                "project_id": project.id,
                "filename": filename,
                "total_tr": assessment.total_tr,
                "livello": assessment.livello,
                "ceo_required": assessment.ceo_required,
                "message": f"VRF compilato online per kickoff #{project.id} - {project.name}",
            })
            if assessment.ceo_required:
                messages.warning(
                    request,
                    f"VRF salvato. Totale Rischio {assessment.total_tr:.0f} ≥ {vrf_catalog.TR_ALTO_MIN} (Alto): "
                    "richiesto il coinvolgimento del CEO.",
                )
            else:
                messages.success(request, "VRF compilato e salvato. Kickoff sbloccato.")
            return redirect("tasks:project_gantt", project_id=project_id)

        messages.error(request, "Azione non riconosciuta.")
        return redirect("tasks:project_vrf_compile", project_id=project_id)

    data = assessment.data or vrf_catalog.default_scores()
    totals = vrf_catalog.compute_totals(data)
    risks_view = []
    for risk in vrf_catalog.RISKS:
        info = totals["per_risk"][risk["code"]]
        risks_view.append({
            "code": risk["code"],
            "title": risk["title"],
            "d": risk["d"],
            "p": "" if info["p"] is None else str(info["p"]),
            "r": info["r"],
            "level": info["level"],
            "checklist": risk["checklist"],
        })
    azioni = list(data.get("azioni") or [])
    azioni += [""] * (len(vrf_catalog.AZIONI_CELLS) - len(azioni))
    firme = {"in1": "", "in1_data": "", "em": "", "em_data": "", **(data.get("firme") or {})}

    context = {
        **_tasks_shell_context(request, active="vrf", project=project),
        "page_title": f"Compila VRF - {project.name}",
        "project": project,
        "vrf_detail": vrf_detail,
        "assessment": assessment,
        "prefilled_from_xlsx": prefilled_from_xlsx,
        "risks": risks_view,
        "p_choices": [(str(v), lbl) for v, lbl in vrf_catalog.P_CHOICES],
        "totals": totals,
        "azioni": azioni[: len(vrf_catalog.AZIONI_CELLS)],
        "firme": firme,
        "tr_basso_max": vrf_catalog.TR_BASSO_MAX,
        "tr_alto_min": vrf_catalog.TR_ALTO_MIN,
        "tr_max": vrf_catalog.TR_MAX,
    }
    return render(request, "tasks/project_vrf_compile.html", context)


@task_permissions_required("tasks_view")
def project_vrf_download(request, project_id: int):
    """Scarica l'xlsx corrente (da vrf_file) oppure rigenera dal template+assessment."""
    from django.http import FileResponse, HttpResponse
    from ..vrf_generator import build_vrf_xlsx, vrf_filename_for

    project_qs = scoped_projects_queryset(request)
    project = get_object_or_404(project_qs, pk=project_id)

    if project.vrf_file and project.vrf_file.name:
        try:
            return FileResponse(
                project.vrf_file.open("rb"),
                as_attachment=True,
                filename=project.vrf_original_name or vrf_filename_for(project),
            )
        except FileNotFoundError:
            pass

    assessment = getattr(project, "vrf_assessment", None)
    try:
        xlsx_bytes = build_vrf_xlsx(project, assessment)
    except FileNotFoundError:
        return HttpResponse("Template VRF non disponibile sul server.", status=500)
    response = HttpResponse(
        xlsx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{vrf_filename_for(project)}"'
    return response
