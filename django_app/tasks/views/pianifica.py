"""Dopo la scheda VRF: «Attività e incontro» e la pianificazione rapida delle attività.

Il filo del kickoff: dati commessa -> VRF (compilata o rimandata) -> una pagina
sola per attività, incontro e ordine del giorno (`project_pianifica`). La
pagina a righe `project_attivita_pianifica` resta per aggiungere attività a un
kickoff già avviato.
"""
from __future__ import annotations

import json

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..forms import etichetta_utente, task_active_users_queryset
from ..models import TaskImpostazioni, TaskStatus
from ._shared import _tasks_shell_context, _vrf_status_detail


def _stato(project) -> dict:
    tasks = project.tasks.exclude(status=TaskStatus.CANCELED)
    return {
        "attivita_totali": tasks.count(),
        "attivita_senza_responsabile": tasks.filter(assigned_to__isnull=True).count(),
        "incontri": project.meetings.count(),
        "vrf": _vrf_status_detail(project, TaskImpostazioni.get_singleton()),
        "vrf_da_fare": project.vrf_status == "PENDING",
    }


# ── «Attività e incontro»: il terzo passo del kickoff in una pagina ──────────

DURATE_INCONTRO = [(30, "30 minuti"), (45, "45 minuti"), (60, "1 ora"), (90, "1 ora e mezza"), (120, "2 ore")]


def _punto_odg(indice: int, titolo: str) -> dict:
    """Punto di discussione libero, nella stessa forma che salva la convocazione."""
    return {
        "id": f"punto-{indice}", "titolo": titolo[:200], "nota": "", "task_id": None, "task_label": "",
        "issue_id": None, "action_id": None, "source": "", "locked": False,
        "responsabile_id": None, "responsabile_label": "", "durata_minuti": None,
        "tempo_effettivo_minuti": None, "custom_fields": [], "done": False,
        "crea_attivita": False, "scadenza": "",
    }


def _punti_proposti(project) -> list[dict]:
    """Punti che il portale propone per l'incontro: le tappe del Percorso ancora da sistemare."""
    from ..services.tappe import agenda_items as tappe_agenda

    return tappe_agenda(project)


def _ordine_dal_post(post) -> list[dict]:
    """L'ordine del giorno come lo ha composto l'utente: attività, punti proposti, punti liberi."""
    try:
        voci = json.loads(post.get("odg_ordine") or "[]")
    except (TypeError, ValueError):
        return []
    return [v for v in voci if isinstance(v, dict)][:80] if isinstance(voci, list) else []


def _agenda(project, ordine: list[dict], righe, tasks) -> list[dict]:
    """Ordine del giorno dell'incontro, nell'ordine scelto.

    ``{"att": chiave}`` = un'attività della pagina (da confermare in riunione),
    ``{"pre": n}`` = l'n-esimo punto proposto, ``{"punto": titolo}`` = punto libero.
    Un'attività segnata «All'ODG» che non compare nell'ordine va in coda.
    """
    from ..services.kickoff_avvio import agenda_da_attivita

    per_chiave = {r.chiave: t for r, t in zip(righe, tasks, strict=False) if r.chiave and r.odg}
    punti_attivita, _ = agenda_da_attivita(project, ",".join(str(t.pk) for t in per_chiave.values())) if per_chiave else ([], [])
    per_task = {p["task_id"]: {**_punto_odg(0, p["titolo"]), **p} for p in punti_attivita}
    proposti = _punti_proposti(project)
    agenda, usate = [], set()
    for voce in ordine:
        if "att" in voce:
            task = per_chiave.get(str(voce["att"]))
            if task is not None and task.pk not in usate and task.pk in per_task:
                agenda.append(per_task[task.pk])
                usate.add(task.pk)
        elif "pre" in voce:
            try:
                agenda.append(proposti[int(voce["pre"])])
            except (IndexError, TypeError, ValueError):
                continue
        elif str(voce.get("punto") or "").strip():
            agenda.append(_punto_odg(len(agenda) + 1, str(voce["punto"]).strip()))
    agenda += [p for task_id, p in per_task.items() if task_id not in usate]
    return agenda


def _contesto_avvio(request, project, *, post=None, errori=None) -> dict:
    """Quello che serve alla pagina; con un POST rifiutato ripropone ciò che l'utente ha scritto."""
    from django.utils import timezone

    from ..models import MeetingAgendaTemplate, MeetingRoom

    utenti = list(task_active_users_queryset())
    team = set(project.team_user_ids)
    # Nome e cognome, senza l'indirizzo: qui le persone compaiono in etichette e righe strette.
    persone = [
        {"id": u.pk, "nome": (u.get_full_name() or u.get_username()).strip(), "team": u.pk in team}
        for u in utenti
    ]
    proposti = _punti_proposti(project)

    righe = []
    if post is not None:
        campi = [post.getlist(n) for n in ("att_chiave", "att_titolo", "att_resp", "att_scadenza", "att_note", "att_odg", "att_dopo")]
        for i in range(len(campi[1])):
            chiave, titolo, resp, scad, nota, odg, dopo = [(c[i] if i < len(c) else "") for c in campi]
            if titolo.strip() or resp or scad or nota.strip():
                righe.append({"chiave": chiave or f"r{i + 1}", "titolo": titolo, "resp": resp, "scadenza": scad,
                              "nota": nota, "odg": odg == "1", "dopo": dopo})
    while len(righe) < 3:
        righe.append({"chiave": f"n{len(righe) + 1}", "titolo": "", "resp": "", "scadenza": "", "nota": "", "odg": True, "dopo": ""})

    if post is not None:
        ordine = _ordine_dal_post(post)
        con_incontro = post.get("incontro") == "1"
        incontro = {k: post.get(f"inc_{k}", "") for k in ("data", "ora", "durata", "sala")}
        partecipanti = {int(v) for v in post.getlist("inc_part") if v.isdigit()}
        invio, convocazione = post.get("invio") or "subito", bool(post.get("invia_convocazione"))
    else:
        # Entrano da sole solo le tappe già impostate (con un'attività: assegnate, in
        # corso, in ritardo). Quelle ancora da assegnare si aggiungono con un clic.
        ordine = [{"pre": i} for i, p in enumerate(proposti) if p.get("task_id")]
        con_incontro = True
        incontro = {"data": timezone.localdate().isoformat(), "ora": "", "durata": "", "sala": ""}
        partecipanti = set(team)
        invio, convocazione = "subito", True

    esistenti = list(
        project.tasks.exclude(status__in=[TaskStatus.CANCELED, TaskStatus.DONE])
        .select_related("assigned_to").order_by("id")
    )
    dati = {
        "persone": persone,
        "proposti": [p["titolo"] for p in proposti],
        "ordine": ordine,
        "modelli": [
            {"nome": m.nome, "punti": [str(i.get("titolo") or "").strip() for i in (m.items or []) if isinstance(i, dict) and str(i.get("titolo") or "").strip()]}
            for m in MeetingAgendaTemplate.objects.filter(is_active=True).order_by("order_index", "nome")
        ],
        "io": request.user.pk,
    }
    return {
        **_tasks_shell_context(request, active="overview", project=project),
        "page_title": f"Attività e incontro - {project.name}",
        "project": project,
        **_stato(project),
        "ka_righe": righe,
        "ka_persone": persone,
        "ka_con_incontro": con_incontro,
        "ka_incontro": incontro,
        "ka_partecipanti": [p for p in persone if p["id"] in partecipanti],
        "ka_sale": list(MeetingRoom.objects.filter(attiva=True).order_by("ordine", "nome")),
        "ka_durate": DURATE_INCONTRO,
        "ka_invio": invio,
        "ka_convocazione": convocazione,
        "ka_esistenti": esistenti,
        "ka_errori": errori or [],
        # Per lo <script>: niente «</» che chiuda il tag in anticipo.
        "ka_dati_json": json.dumps(dati).replace("</", "<\\/"),
    }


@task_permissions_required("tasks_view")
def project_pianifica(request, project_id: int):
    """Passo 3 del kickoff: attività, incontro e ordine del giorno in una pagina.

    Le attività si scrivono a righe (cosa, chi, entro quando, nota) e si possono
    collegare («viene dopo»). L'incontro è facoltativo; l'ordine del giorno può
    usare le attività («All'ODG») oppure no. Alla fine si sceglie quando avvisare
    i responsabili: subito, o con la minuta dell'incontro, che riporta le
    attività assegnate. Niente parte prima della conferma.
    """
    from ..services.kickoff_avvio import (
        collega_attivita,
        crea_attivita,
        notifica_assegnazioni,
        righe_dal_post,
        rimanda_avviso_alla_minuta,
    )
    from ..services.meeting_tasks import kickoff_bloccato_vrf

    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return redirect("tasks:project_overview", project_id=project.id)
    if request.method != "POST":
        return render(request, "tasks/project_pianifica.html", _contesto_avvio(request, project))

    from ..access import has_task_permission

    if not has_task_permission(request, "tasks_create"):
        return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)

    righe = righe_dal_post(request.POST)
    con_incontro = request.POST.get("incontro") == "1"
    ordine = _ordine_dal_post(request.POST)
    aspetta_minuta = con_incontro and request.POST.get("invio") == "minuta"
    errori = []
    if righe and kickoff_bloccato_vrf(project):
        messages.error(request, "Kickoff bloccato per VRF mancante: compila la scheda VRF per pianificare le attività.")
        return redirect("tasks:project_vrf_compile", project_id=project.id)
    if not righe and not con_incontro:
        errori.append("Scrivi almeno un'attività, oppure convoca un incontro.")

    form = None
    if con_incontro:
        from ..forms import KickoffMeetingForm
        from ..models import MeetingStatus
        from .meetings import _outlook_pronto

        partecipanti = {v for v in request.POST.getlist("inc_part") if v.isdigit()}
        # Chi ha un'attività viene convocato: in riunione la conferma.
        partecipanti |= {str(r.responsabile.pk) for r in righe if r.responsabile is not None}
        dati = {
            "titolo": "", "luogo": "", "stato": MeetingStatus.PIANIFICATO,
            "data": request.POST.get("inc_data", ""), "ora": request.POST.get("inc_ora", ""),
            "durata_minuti": request.POST.get("inc_durata", ""), "sala": request.POST.get("inc_sala", ""),
            "partecipanti_utenti": sorted(partecipanti), "agenda_items_raw": "[]",
        }
        if _outlook_pronto():
            dati["sync_outlook"] = "on"
        if request.POST.get("invia_convocazione"):
            dati["invia_convocazione"] = "on"
        form = KickoffMeetingForm(dati)
        if not form.is_valid():
            etichette = {"data": "Data dell'incontro", "ora": "Ora", "sala": "Sala", "durata_minuti": "Durata"}
            for campo, messaggi in form.errors.items():
                errori.append(f"{etichette.get(campo, 'Incontro')}: {' '.join(messaggi)}")
    if errori:
        return render(
            request, "tasks/project_pianifica.html",
            _contesto_avvio(request, project, post=request.POST, errori=errori), status=400,
        )

    meeting = None
    with transaction.atomic():
        tasks = crea_attivita(project, righe, request.user)
        collegate = collega_attivita(righe, tasks)
        if form is not None:
            meeting = form.save(commit=False)
            meeting.project = project
            meeting.created_by = request.user
            meeting.agenda_items = _agenda(project, ordine, righe, tasks)
            meeting.save()
            form.save_m2m()
            if aspetta_minuta:
                rimanda_avviso_alla_minuta(tasks, meeting)
    if not aspetta_minuta:
        notifica_assegnazioni(tasks, actor=request.user)

    log_action(request, "kickoff_attivita_e_incontro", "tasks", {
        "project_id": project.id,
        "task_ids": [t.id for t in tasks],
        "meeting_id": meeting.pk if meeting else None,
        "collegamenti": collegate,
        "avviso": "con la minuta" if aspetta_minuta else "subito",
        "message": f"Kickoff #{project.id}: {len(tasks)} attività"
                   + (f" e incontro {meeting.numero}" if meeting else "")
                   + (" (avviso con la minuta)" if aspetta_minuta else ""),
    })
    if tasks:
        messages.success(
            request,
            f"{len(tasks)} attività salvate. " + (
                "I responsabili le riceveranno con la minuta dell'incontro." if aspetta_minuta
                else "I responsabili sono stati avvisati."
            ),
        )
    if meeting is None:
        return redirect("tasks:project_overview", project_id=project.id)

    from .meetings import _send_invite_if_requested, _sync_meeting_outlook

    _sync_meeting_outlook(request, meeting)
    messages.success(request, f"Incontro {meeting.numero} creato con {len(meeting.agenda_items or [])} punti all'ordine del giorno.")
    _send_invite_if_requested(request, form, meeting)
    return redirect("tasks:project_meeting_detail", project_id=project.id, meeting_id=meeting.pk)


def _righe_iniziali(post, utenti_per_id) -> list[dict]:
    righe = []
    if post is not None:
        titoli, resp, scad = post.getlist("att_titolo"), post.getlist("att_resp"), post.getlist("att_scadenza")
        for i, titolo in enumerate(titoli):
            r = resp[i] if i < len(resp) else ""
            d = scad[i] if i < len(scad) else ""
            if (titolo or "").strip() or r or d:
                righe.append({"titolo": titolo, "resp": r if r in utenti_per_id else "",
                              "resp_label": utenti_per_id.get(r, ""), "scadenza": d})
    while len(righe) < 3:
        righe.append({"titolo": "", "resp": "", "resp_label": "", "scadenza": ""})
    return righe


@task_permissions_required("tasks_view", "tasks_create")
def project_attivita_pianifica(request, project_id: int):
    """Pianificazione rapida: una riga per attività (cosa, chi, entro quando).

    Responsabile e scadenza sono facoltativi: la scadenza spesso non si sa.
    «Salva e pianifica l'incontro» porta alla convocazione con queste attività
    nell'ordine del giorno, da confermare in riunione.
    """
    from ..services.kickoff_avvio import crea_attivita, notifica_assegnazioni, righe_dal_post
    from ..services.meeting_tasks import kickoff_bloccato_vrf

    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)
    if kickoff_bloccato_vrf(project):
        messages.error(request, "Kickoff bloccato per VRF mancante: compila la scheda VRF per pianificare le attività.")
        return redirect("tasks:project_vrf_compile", project_id=project.id)

    utenti = [{"id": u.pk, "label": etichetta_utente(u)} for u in task_active_users_queryset()]
    utenti_per_id = {str(u["id"]): u["label"] for u in utenti}

    if request.method == "POST":
        righe = righe_dal_post(request.POST)
        poi_incontro = request.POST.get("poi") == "incontro"
        if not righe and not poi_incontro:
            messages.error(request, "Scrivi almeno un'attività.")
        else:
            with transaction.atomic():
                tasks = crea_attivita(project, righe, request.user)
            notifica_assegnazioni(tasks, actor=request.user)
            log_action(request, "kickoff_attivita_pianificate", "tasks", {
                "project_id": project.id,
                "task_ids": [t.id for t in tasks],
                "message": f"{len(tasks)} attività pianificate nel kickoff #{project.id}",
            })
            if tasks:
                messages.success(request, f"{len(tasks)} attività pianificate.")
            if poi_incontro:
                ids = ",".join(str(t.id) for t in tasks)
                url = reverse("tasks:project_meeting_create", kwargs={"project_id": project.id})
                return redirect(f"{url}?attivita={ids or 'aperte'}")
            return redirect("tasks:project_overview", project_id=project.id)

    esistenti = list(
        project.tasks.exclude(status__in=[TaskStatus.CANCELED, TaskStatus.DONE])
        .select_related("assigned_to").order_by("id")
    )
    return render(
        request,
        "tasks/project_attivita_pianifica.html",
        {
            **_tasks_shell_context(request, active="overview", project=project),
            "page_title": f"Pianifica attività - {project.name}",
            "project": project,
            "att_utenti": utenti,
            # Per lo <script>: niente «</» che chiuda il tag in anticipo.
            "att_utenti_json": json.dumps(utenti).replace("</", "<\\/"),
            "att_righe": _righe_iniziali(request.POST if request.method == "POST" else None, utenti_per_id),
            "attivita_esistenti": esistenti,
            "vrf_da_fare": project.vrf_status == "PENDING",
        },
    )
