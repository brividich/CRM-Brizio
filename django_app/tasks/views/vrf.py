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
    """Estrae i campi identificativi da MOD.073 VRF Rev.10 (Sheet 'VRF').
    Celle fisse: B3=P/N, I3=Descrizione, P3=Esp, O2=Preventivo n°, P2=Versione n°, B4=Cliente.
    Restituisce dict con chiavi stringa, mai None.
    """
    import io
    import openpyxl

    def _s(val):
        return str(val or "").strip()

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
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        # Preferenza sheet "VRF", altrimenti primo sheet
        ws = wb["VRF"] if "VRF" in wb.sheetnames else wb.active
        # Leggi le 4 righe di intestazione (1-indexed)
        rows = {}
        for r in ws.iter_rows(min_row=1, max_row=4, values_only=True):
            pass  # warming
        # iter_rows con read_only non supporta accesso per cella — rileggiamo
        wb.close()
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        ws = wb["VRF"] if "VRF" in wb.sheetnames else wb.active
        result["vrf_quote_number"] = _s(ws.cell(row=2, column=15).value)  # O2
        result["versione"]         = _s(ws.cell(row=2, column=16).value)  # P2
        result["part_number"]      = _s(ws.cell(row=3, column=2).value)   # B3
        result["vrf_description"]  = _s(ws.cell(row=3, column=9).value)   # I3
        result["vrf_esp"]          = _s(ws.cell(row=3, column=16).value)  # P3
        result["client_name"]      = _s(ws.cell(row=4, column=2).value)   # B4
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
# VRF compilazione online (matrice rischi MOD.073 Rev.10)
# ---------------------------------------------------------------------------

@task_permissions_required("tasks_view")
def project_vrf_compile(request, project_id: int):
    """Compila la matrice rischi VRF online e genera l'xlsx a conferma.

    GET: mostra la matrice (con eventuale bozza salvata su VRFRiskAssessment).
    POST action=save_draft: aggiorna la valutazione senza generare file.
    POST action=confirm: genera xlsx, salva su project.vrf_file, marca UPLOADED.
    """
    from .. import vrf_catalog
    from ..vrf_generator import build_vrf_xlsx, parse_vrf_xlsx, vrf_filename_for

    project_qs = scoped_projects_queryset(request)
    project = get_object_or_404(project_qs, pk=project_id)
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    if vrf_detail.get("is_blocked"):
        messages.error(request, "Compilazione VRF bloccata: periodo di blocco superato.")
        return redirect("tasks:project_gantt", project_id=project_id)

    assessment = getattr(project, "vrf_assessment", None)
    prefilled_from_xlsx = False
    if assessment is None:
        initial_data = vrf_catalog.default_scores()
        if request.method == "GET" and project.vrf_file and project.vrf_file.name:
            try:
                with project.vrf_file.open("rb") as fh:
                    initial_data = parse_vrf_xlsx(fh)
                prefilled_from_xlsx = True
            except Exception:
                initial_data = vrf_catalog.default_scores()
                prefilled_from_xlsx = False
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
        data = vrf_catalog.default_scores()

        for risk in vrf_catalog.RISKS:
            r_code = risk["code"]
            for ph in vrf_catalog.PHASES:
                k_raw = request.POST.get(f"k_{r_code}_{ph['key']}", "").strip()
                try:
                    k_val = int(k_raw)
                    k_val = max(vrf_catalog.K_RANGE[0], min(vrf_catalog.K_RANGE[1], k_val))
                except (TypeError, ValueError):
                    k_val = risk["k_default"][ph["key"]]
                data["risks"][r_code]["k"][ph["key"]] = k_val

                for sub in risk["sub_parameters"]:
                    raw = request.POST.get(f"score_{r_code}_{sub['code']}_{ph['key']}", "").strip()
                    if raw == "" or raw is None:
                        data["risks"][r_code]["subs"][sub["code"]][ph["key"]] = None
                    else:
                        try:
                            v = int(raw)
                            v = max(vrf_catalog.R_RANGE[0], min(vrf_catalog.R_RANGE[1], v))
                            data["risks"][r_code]["subs"][sub["code"]][ph["key"]] = v
                        except (TypeError, ValueError):
                            data["risks"][r_code]["subs"][sub["code"]][ph["key"]] = None

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
            messages.success(request, "Bozza VRF salvata. I totali sono aggiornati.")
            return redirect("tasks:project_vrf_compile", project_id=project_id)

        if action == "skip_with_reminder":
            log_action(request, "vrf_skipped_with_reminder", "tasks", {
                "project_id": project.id,
                "message": f"VRF rimandato per kickoff #{project.id}, bozza salvata, stato PENDING",
            })
            messages.info(
                request,
                "Bozza VRF salvata. Il sistema ti ricordera' di completare la scheda VRF "
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
                "total_p": assessment.total_p,
                "total_i": assessment.total_i,
                "total_c": assessment.total_c,
                "dig_triggered": assessment.dig_triggered,
                "message": f"VRF compilato online per kickoff #{project.id} - {project.name}",
            })
            if assessment.dig_triggered:
                messages.warning(request, "VRF salvato. Attenzione: TR >= 46 in almeno una fase - richiesto coinvolgimento DIG.")
            else:
                messages.success(request, "VRF compilato e salvato. Kickoff sbloccato.")
            return redirect("tasks:project_gantt", project_id=project_id)

        messages.error(request, "Azione non riconosciuta.")
        return redirect("tasks:project_vrf_compile", project_id=project_id)

    totals = vrf_catalog.compute_totals(assessment.data or {})
    risks_data = (assessment.data or {}).get("risks") or {}
    enriched_risks = []
    for risk in vrf_catalog.RISKS:
        r_data = risks_data.get(risk["code"]) or {}
        k_vals = r_data.get("k") or risk["k_default"]
        subs_data = r_data.get("subs") or {}
        enriched_subs = []
        for sub in risk["sub_parameters"]:
            sub_scores = subs_data.get(sub["code"]) or {}
            enriched_subs.append({
                "code": sub["code"],
                "row": sub["row"],
                "label": sub["label"],
                "score_p": "" if sub_scores.get("p") is None else str(sub_scores.get("p")),
                "score_i": "" if sub_scores.get("i") is None else str(sub_scores.get("i")),
                "score_c": "" if sub_scores.get("c") is None else str(sub_scores.get("c")),
            })
        enriched_risks.append({
            "code": risk["code"],
            "row": risk["row"],
            "title": risk["title"],
            "k_p": k_vals.get("p", risk["k_default"]["p"]),
            "k_i": k_vals.get("i", risk["k_default"]["i"]),
            "k_c": k_vals.get("c", risk["k_default"]["c"]),
            "sub_parameters": enriched_subs,
        })

    context = {
        **_tasks_shell_context(request, active="vrf", project=project),
        "page_title": f"Compila VRF - {project.name}",
        "project": project,
        "vrf_detail": vrf_detail,
        "assessment": assessment,
        "prefilled_from_xlsx": prefilled_from_xlsx,
        "risks": enriched_risks,
        "phases": vrf_catalog.PHASES,
        "totals": totals,
        "dig_threshold": vrf_catalog.DIG_THRESHOLD,
        "k_min": vrf_catalog.K_RANGE[0],
        "k_max": vrf_catalog.K_RANGE[1],
        "r_min": vrf_catalog.R_RANGE[0],
        "r_max": vrf_catalog.R_RANGE[1],
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
