"""Programmi CAM, programmi CMM e FAI di una commessa."""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.csv_export import csv_download_response

from ..access import (
    _detail_queryset,
    can_manage_project,
    can_manage_task,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..models import KickoffMeeting, ProgrammaFase, ProjectTechRef, TechRefKind
from ..services.fai import allinea_da_riga, esito_progetto
from ..services.notify import notify_user
from ..services.programmi import allinea_stato_riga, attivita_per_riga
from ..tech_paths import normalizza_percorso
from ._shared import _tasks_shell_context, _utenti_riga_rapida


def _puo_aggiungere(request, project) -> bool:
    return can_manage_project(request, project) or request.user.pk in project.team_user_ids


def _programmatore_id(project):
    """Per CAM e CMM si propone il programmatore, se la commessa ne ha uno solo."""
    programmatori = project.team_members("programmers")
    return programmatori[0].pk if len(programmatori) == 1 else ""


def tech_refs_context(request, project, meeting=None) -> dict:
    from ..services.programmi_fasi import azioni_possibili

    gestisce = can_manage_project(request, project)
    righe = [
        {
            "ref": ref,
            "can_edit": gestisce or ref.assigned_to_id == request.user.pk,
            "can_delete": gestisce,
            "azioni": azioni_possibili(ref),
        }
        for ref in project.tech_refs.select_related("assigned_to", "source_meeting", "task", "macchina", "fai_record__causale", "fai_record__stato")
    ]
    puo_aggiungere = gestisce or request.user.pk in project.team_user_ids
    righe_fai = [r for r in righe if r["ref"].kind == TechRefKind.FAI]
    return {
        "project": project,
        "tech_rows": righe,
        "tech_rows_programmi": [r for r in righe if r["ref"].kind != TechRefKind.FAI],
        "tech_rows_fai": righe_fai,
        "tech_open_count": sum(1 for r in righe if r["ref"].is_open),
        "tech_can_add": puo_aggiungere,
        "tech_show_form": puo_aggiungere or any(r["can_edit"] for r in righe),
        "tech_can_assign": gestisce,
        "tech_kinds": TechRefKind.choices,
        "tech_users": _utenti_riga_rapida(project),
        "tech_default_owner": _programmatore_id(project),
        "tech_meeting": meeting,
        "fai_esito": esito_progetto(project),
        # Se poi qualcuno apre comunque un FAI, vale il FAI.
        "fai_non_richiesto": project.fai_non_richiesto_il is not None and not righe_fai,
        "fai_puo_creare": puo_aggiungere,
        # Il FAI assegnato in riunione si completa, non se ne crea un altro.
        "fai_ref_libera": next((r["ref"] for r in righe_fai if getattr(r["ref"], "fai_record", None) is None), None),
    }


def _codice_scritto(ref, user) -> None:
    """Il codice c'è: il programma non è più «da scrivere»."""
    from ..services.programmi_fasi import registra

    if ref.is_programma and ref.code and ref.fase == ProgrammaFase.DA_SCRIVERE:
        ref.fase = ProgrammaFase.IN_SCRITTURA
        ref.revisione = ref.revisione or "A"
        ref.save(update_fields=["fase", "revisione", "updated_at"])
        registra(ref, user, "Codice inserito")


def _risposta(request, project, meeting=None, status: int = 200) -> JsonResponse:
    html = render_to_string("tasks/_tech_refs_body.html", tech_refs_context(request, project, meeting), request=request)
    return JsonResponse({"ok": True, "html": html}, status=status)


def _errore(motivo: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "reason": motivo}, status=status)


def _avvisa(ref, attore) -> None:
    """Chi riceve la voce lo sa subito, senza dover aprire la commessa."""
    assegnato = ref.assigned_to
    if assegnato is None or assegnato.pk == getattr(attore, "pk", None):
        return
    scadenza = f", entro il {ref.due_date:%d/%m/%Y}" if ref.due_date else ""
    url = reverse("tasks:project_tech_refs", args=[ref.project_id])
    notify_user(assegnato, f"Sei responsabile di «{ref.label}» [{ref.project.name}]{scadenza}.", url)


def _stato_programma(ref) -> tuple[str, str]:
    from ..services.programmi_fasi import CLASSE

    if ref.is_overdue:
        return f"{ref.get_fase_display()} · in ritardo", "danger"
    return ref.get_fase_display(), CLASSE.get(ref.fase, "")


def _esporta_programmi(righe):
    response, writer = csv_download_response("programmi.csv", delimiter=";")
    writer.writerow(["Tipo", "Codice", "Revisione", "Macchina", "Cartella o file", "Cliente", "P/N", "Kickoff", "Responsabile", "Entro il", "Stato"])
    for riga in righe:
        ref = riga["ref"]
        writer.writerow([
            ref.get_kind_display(), ref.code, ref.revisione, ref.macchina.asset_tag if ref.macchina_id else "",
            ref.path, ref.project.client_name, ref.project.part_number,
            ref.project.name,
            (ref.assigned_to.get_full_name() or ref.assigned_to.username) if ref.assigned_to else "",
            ref.due_date or "", riga["stato"],
        ])
    return response


@task_permissions_required("tasks_view")
def programmi_registro(request):
    """Tutti i programmi CAM e CMM delle commesse visibili."""
    tutte = [
        {"ref": ref, "stato": stato, "classe": classe}
        for ref in ProjectTechRef.objects.filter(
            kind__in=[TechRefKind.CAM, TechRefKind.CMM], project__in=scoped_projects_queryset(request)
        ).select_related("project", "assigned_to", "task", "fai_record", "macchina").order_by("project__part_number", "kind", "id")
        for stato, classe in [_stato_programma(ref)]
    ]
    from ..services.programmi_fasi import azioni_possibili

    for r in tutte:
        r["azioni"] = azioni_possibili(r["ref"])
    viste = (
        ("", "Tutti", lambda r: True),
        ("da_scrivere", "Da scrivere", lambda r: r["ref"].fase == ProgrammaFase.DA_SCRIVERE),
        ("in_scrittura", "In scrittura", lambda r: r["ref"].fase == ProgrammaFase.IN_SCRITTURA),
        ("da_provare", "Da provare", lambda r: r["ref"].fase == ProgrammaFase.DA_PROVARE),
        ("validati", "Validati", lambda r: r["ref"].fase == ProgrammaFase.VALIDATO),
        ("ritardo", "In ritardo", lambda r: r["ref"].is_overdue),
    )
    vista = request.GET.get("vista", "")
    filtro = next((v[2] for v in viste if v[0] == vista), None)
    if filtro is None:
        vista, filtro = "", viste[0][2]
    righe = [r for r in tutte if filtro(r)]
    tipo = request.GET.get("tipo", "")
    if tipo in (TechRefKind.CAM, TechRefKind.CMM):
        righe = [r for r in righe if r["ref"].kind == tipo]
    macchina = request.GET.get("macchina", "")
    if macchina.isdigit():
        righe = [r for r in righe if r["ref"].macchina_id == int(macchina)]
    q = (request.GET.get("q") or "").strip()
    if q:
        testo = q.lower()
        righe = [
            r for r in righe
            if testo in " ".join((
                r["ref"].code, r["ref"].path, r["ref"].project.name,
                r["ref"].project.client_name, r["ref"].project.part_number,
            )).lower()
        ]
    if request.GET.get("formato") == "csv":
        log_action(request, "kickoff_programmi_esporta", "tasks", {"vista": vista, "righe": len(righe)})
        return _esporta_programmi(righe)
    return render(request, "tasks/programmi_registro.html", {
        **_tasks_shell_context(request, active="programmi"),
        "page_title": "Programmi",
        "righe": righe,
        "viste": [
            {"codice": codice, "etichetta": etichetta, "conta": sum(1 for r in tutte if regola(r))}
            for codice, etichetta, regola in viste
        ],
        "vista": vista,
        "q": q,
        "tipo": tipo,
        "macchina": macchina,
        "macchine": sorted({r["ref"].macchina for r in tutte if r["ref"].macchina_id}, key=lambda a: a.asset_tag),
    })


@require_POST
@task_permissions_required("tasks_view")
def task_programma(request, task_id: int):
    """Codice e cartella scritti direttamente dall'attività che deve produrli."""
    task = get_object_or_404(_detail_queryset(request), pk=task_id)
    ref = get_object_or_404(ProjectTechRef, task=task)
    if not (can_manage_task(request, task) or task.assigned_to_id == request.user.pk):
        raise PermissionDenied
    try:
        path = normalizza_percorso(request.POST.get("path"))
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("tasks:detail", task_id=task.pk)
    if len(path) > 500:
        messages.error(request, "Il percorso è troppo lungo: massimo 500 caratteri.")
        return redirect("tasks:detail", task_id=task.pk)
    ref.code = (request.POST.get("code") or "").strip()[:120]
    ref.path = path
    ref.save(update_fields=["code", "path", "updated_at"])
    _codice_scritto(ref, request.user)
    allinea_da_riga(ref)
    allinea_stato_riga(ref, request.user)
    log_action(request, "kickoff_programma_da_attivita", "tasks", {"id": ref.pk, "task_id": task.pk})
    messages.success(request, f"{ref.get_kind_display()} salvato.")
    return redirect("tasks:detail", task_id=task.pk)


@task_permissions_required("tasks_view")
def project_tech_refs(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    return render(
        request,
        "tasks/project_tech_refs.html",
        {
            **_tasks_shell_context(request, active="tech_refs", project=project),
            **tech_refs_context(request, project),
            "page_title": f"Programmi e FAI - {project.name}",
        },
    )


@require_POST
@task_permissions_required("tasks_view", api=True)
def tech_ref_save(request, project_id: int):
    """Aggiunge una riga o, con ``ref_id``, corregge quella esistente."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    gestisce = can_manage_project(request, project)
    post = request.POST

    meeting = None
    if (post.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(post["meeting_id"]), project=project).first()

    ref = None
    if (post.get("ref_id") or "").isdigit():
        ref = project.tech_refs.filter(pk=int(post["ref_id"])).select_related("assigned_to").first()
        if ref is None:
            return _errore("Riga non trovata in questa commessa.", 404)
        if not (gestisce or ref.assigned_to_id == request.user.pk):
            return _errore("Puoi correggere solo le righe di cui sei responsabile.", 403)
    elif not _puo_aggiungere(request, project):
        return _errore("Solo chi fa parte del team può aggiungere righe.", 403)

    kind = (post.get("kind") or "").strip()
    if kind not in TechRefKind.values:
        return _errore("Scegli il tipo: CAM, CMM o FAI.")
    code = (post.get("code") or "").strip()[:120]
    try:
        path = normalizza_percorso(post.get("path"))
    except ValueError as exc:
        return _errore(str(exc))
    if len(path) > 500:
        return _errore("Il percorso è troppo lungo: massimo 500 caratteri.")

    due_date = None
    testo_data = (post.get("due_date") or "").strip()
    if testo_data:
        try:
            due_date = date.fromisoformat(testo_data)
        except ValueError:
            return _errore("Data non valida.")

    # Chi ha solo la propria riga compila codice e percorso, ma non la passa ad altri.
    if ref is None or gestisce:
        assegnato_id = (post.get("assigned_to") or "").strip()
        assegnato = None
        if assegnato_id:
            from ..forms import task_active_users_queryset

            if not assegnato_id.isdigit():
                return _errore("Responsabile non valido.")
            assegnato = task_active_users_queryset().filter(pk=int(assegnato_id)).first()
            if assegnato is None:
                return _errore("Responsabile non valido.")
    else:
        assegnato = ref.assigned_to

    if not (code or path or assegnato or (ref is not None and ref.task_id)):
        return _errore("Scrivi il codice, il percorso o il responsabile.")

    # Tipo, responsabile e data di una riga nata da un'attività si decidono sull'attività.
    if ref is not None and ref.task_id:
        kind, assegnato, due_date = ref.kind, ref.assigned_to, ref.due_date

    if ref is not None and kind != TechRefKind.FAI and getattr(ref, "fai_record", None) is not None:
        return _errore("Questa riga ha una scheda FAI: resta di tipo FAI.")

    prima = ref.assigned_to_id if ref else None
    nuova = ref is None
    if nuova:
        ref = ProjectTechRef(project=project, created_by=request.user, source_meeting=meeting)
    ref.kind, ref.code, ref.path, ref.due_date, ref.assigned_to = kind, code, path, due_date, assegnato
    ref.save()
    _codice_scritto(ref, request.user)
    allinea_da_riga(ref)
    allinea_stato_riga(ref, request.user)
    log_action(request, "kickoff_tech_ref_salva", "tasks", {
        "id": ref.pk, "project_id": project.pk, "kind": kind, "nuova": nuova,
    })
    # Con un responsabile la riga diventa un'attività del kickoff: Gantt, stati e mail come le altre.
    attivita = attivita_per_riga(ref, request.user)
    if attivita is not None:
        log_action(request, "kickoff_tech_ref_attivita", "tasks", {
            "id": ref.pk, "project_id": project.pk, "task_id": attivita.pk,
        })
    elif ref.assigned_to_id != prima:
        _avvisa(ref, request.user)
    return _risposta(request, project, meeting)


@require_POST
@task_permissions_required("tasks_view", api=True)
def fai_non_richiesto(request, project_id: int):
    """Chi gestisce il kickoff segna che qui il FAI non serve, o torna indietro."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return _errore("Solo chi gestisce la commessa può deciderlo.", 403)

    meeting = None
    if (request.POST.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(request.POST["meeting_id"]), project=project).first()

    non_richiesto = request.POST.get("valore") == "1"
    if non_richiesto and project.tech_refs.filter(kind=TechRefKind.FAI).exists():
        return _errore("Questa commessa ha già una riga FAI: eliminala prima.")
    project.fai_non_richiesto_il = timezone.now() if non_richiesto else None
    project.fai_non_richiesto_da = request.user if non_richiesto else None
    project.save(update_fields=["fai_non_richiesto_il", "fai_non_richiesto_da"])
    log_action(request, "kickoff_fai_non_richiesto", "tasks", {
        "project_id": project.pk, "non_richiesto": non_richiesto,
    })
    return _risposta(request, project, meeting)


@require_POST
@task_permissions_required("tasks_view", api=True)
def tech_ref_action(request, project_id: int, ref_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    ref = get_object_or_404(ProjectTechRef, pk=ref_id, project=project)
    gestisce = can_manage_project(request, project)
    azione = (request.POST.get("action") or "").strip()

    meeting = None
    if (request.POST.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(request.POST["meeting_id"]), project=project).first()

    if azione.startswith("fase_") and ref.is_programma:
        # Passo del programma dalla tabella della commessa (anche dentro l'incontro).
        from ..services.programmi_fasi import PassaggioNonValido, avanza

        if not (gestisce or ref.assigned_to_id == request.user.pk):
            return _errore("Il programma lo aggiorna chi ne è responsabile o il capocommessa.", 403)
        try:
            avanza(ref, request.user, azione[5:])
        except PassaggioNonValido as exc:
            return _errore(str(exc))
        log_action(request, "kickoff_programma_fase", "tasks", {"id": ref.pk, "fase": ref.fase})
        return _risposta(request, project, meeting)
    if azione == "delete":
        if not gestisce:
            return _errore("Solo chi gestisce la commessa può eliminare.", 403)
        if ref.task_id:
            return _errore("Questa riga nasce da un'attività: si toglie cambiando il tipo dell'attività.")
        ref.delete()
    elif azione in ("done", "reopen"):
        if not (gestisce or ref.assigned_to_id == request.user.pk):
            return _errore("Puoi aggiornare solo le righe di cui sei responsabile.", 403)
        if ref.attivita_aperta:
            return _errore("Questa riga si chiude con la sua attività.")
        if azione == "done":
            ref.mark_done(user=request.user)
        else:
            ref.reopen()
        ref.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        allinea_da_riga(ref)
    else:
        return _errore("Azione non valida.")
    log_action(request, f"kickoff_tech_ref_{azione}", "tasks", {"id": ref_id, "project_id": project.pk})
    return _risposta(request, project, meeting)



@require_POST
@task_permissions_required("tasks_view")
def programma_fase(request, ref_id: int):
    """Un passo del programma (Inizia, Pronto da provare, Validato, Da correggere, Nuova revisione)."""
    from ..services.programmi_fasi import PassaggioNonValido, avanza

    ref = get_object_or_404(
        ProjectTechRef.objects.select_related("project", "task"), pk=ref_id, project__in=scoped_projects_queryset(request),
    )
    if not (can_manage_project(request, ref.project) or ref.assigned_to_id == request.user.pk):
        messages.error(request, "Il programma lo aggiorna chi ne è responsabile o il capocommessa.")
    else:
        if (request.POST.get("code") or "").strip() and not ref.code:
            ref.code = request.POST["code"].strip()[:120]
        try:
            avanza(ref, request.user, (request.POST.get("azione") or "").strip(), nota=request.POST.get("nota", ""))
            log_action(request, "kickoff_programma_fase", "tasks", {"id": ref.pk, "fase": ref.fase, "rev": ref.revisione})
            messages.success(request, f"{ref.get_kind_display()} {ref.etichetta_breve}: {ref.get_fase_display().lower()}.")
        except PassaggioNonValido as exc:
            messages.error(request, str(exc))
    nxt = request.POST.get("next") or ""
    if not nxt.startswith("/"):
        nxt = reverse("tasks:programmi_registro")
    return redirect(nxt)
