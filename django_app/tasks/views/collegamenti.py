"""Riquadro «Collegamenti» dell'attività e registro della commessa che ne deriva."""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from ..access import (
    _detail_queryset,
    can_manage_project,
    can_manage_task,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..models import ProjectTechRef, Task
from ..services import collegamenti as svc
from ..services import programmi_fasi
from ..services.tappe import dettaglio_macchina

RISORSE = (svc.MACCHINA, svc.ATTREZZATURA, svc.UTENSILE)
PROGRAMMI = (svc.CAM, svc.CMM, svc.FAI)


def _errore(motivo: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "reason": motivo}, status=status)


def permessi(request, task: Task) -> dict:
    """Chi può collegare cosa. Le regole sono quelle di prima, una per famiglia:

    - macchina, attrezzatura, utensili: chi gestisce l'attività o la commessa, l'incaricato, il team
      (come «Assegna» e gli utensili del vecchio Percorso);
    - programmi e FAI: chi gestisce e l'incaricato (come il vecchio riquadro del programma);
    - incontro: chi gestisce la commessa (come «+ Punto» dell'ordine del giorno).
    """
    project = task.project if task.project_id else None
    if project is None:
        return {"risorse": False, "programmi": False, "incontro": False, "qualcosa": False}
    gestisce_commessa = can_manage_project(request, project)
    gestisce = gestisce_commessa or can_manage_task(request, task)
    incaricato = bool(task.assigned_to_id) and task.assigned_to_id == request.user.pk
    esito = {
        "risorse": gestisce or incaricato or request.user.pk in project.team_user_ids,
        "programmi": gestisce or incaricato,
        "incontro": gestisce_commessa,
    }
    esito["qualcosa"] = any(esito.values())
    return esito


def _puo(perm: dict, tipo: str) -> bool:
    if tipo in RISORSE:
        return perm["risorse"]
    if tipo in PROGRAMMI:
        return perm["programmi"]
    return perm["incontro"]


def _con_nomi(request) -> bool:
    try:
        from anagrafica.services.struttura_macchina import puo_vedere_nomi

        return bool(puo_vedere_nomi(request))
    except Exception:
        return False


def collegamenti_context(request, task: Task, *, apri: str = "") -> dict:
    """Contesto del riquadro per un'attività che esiste già."""
    if not task.project_id:
        return {"col": None}
    perm = permessi(request, task)
    dati = svc.riquadro(task)
    for voce in dati["voci"]:
        voce["puo"] = (
            _puo(perm, voce["tipo"]) and not voce.get("vuoto")
            and (voce["tipo"] != svc.INCONTRO or voce.get("pianificato"))
        )
        voce["puo_compilare"] = perm["programmi"]
        ref = voce.get("ref")
        # Codice e cartella si correggono qui; il FAI con la scheda si corregge dalla scheda.
        voce["modificabile"] = bool(voce["puo"] and ref is not None and getattr(ref, "fai_record", None) is None)
        if voce["tipo"] == svc.FAI and ref is not None and getattr(ref, "fai_record", None) is None:
            # La scheda FAI parte da ciò che la procedura prevede per questo P/N.
            from ..services.fai import esito_progetto

            esito = esito_progetto(task.project)
            if esito and esito.causale:
                voce["url"] += f"&causale={esito.causale}"
    dati["tipi"] = [t for t in dati["tipi"] if _puo(perm, t["codice"])]
    dati.update(
        task=task,
        puo=perm["qualcosa"],
        url_azione=reverse("tasks:collegamenti_azione", args=[task.pk]),
        url_cerca=reverse("tasks:collegamenti_cerca", args=[task.project_id]),
        apri=apri if apri in svc.INFO else "",
        macchina=dettaglio_macchina(task, con_nomi=_con_nomi(request)) if any(v["tipo"] == svc.MACCHINA for v in dati["voci"]) else None,
    )
    return {"col": dati}


def collegamenti_context_nuova(request, project) -> dict:
    """Nel form «+ Attività» l'attività non c'è ancora: i collegamenti scelti si applicano al salvataggio."""
    if project is None:
        return {"col": None}
    gestisce = can_manage_project(request, project)
    tipi = [
        {"codice": tipo, "nome": svc.INFO[tipo]["nome"], "serve": False}
        for tipo in svc.TIPI if tipo != svc.INCONTRO or gestisce
    ]
    return {"col": {
        "task": None, "voci": [], "manca": [], "manca_testo": "", "tipi": tipi, "puo": True, "in_attesa": True,
        "url_azione": "", "url_cerca": reverse("tasks:collegamenti_cerca", args=[project.pk]), "apri": "", "macchina": None,
    }}


def applica_dal_form(request, task: Task) -> list[str]:
    """Dopo «Salva» di una nuova attività: collega quello che era stato scelto nel riquadro."""
    try:
        voci = json.loads(request.POST.get("collegamenti_json") or "[]")
    except ValueError:
        return []
    if not voci or not task.project_id:
        return []
    return svc.applica_in_attesa(
        task, voci, request.user, progetti_visibili=scoped_projects_queryset(request),
        incontro=can_manage_project(request, task.project),
    )


def _html(request, task: Task) -> str:
    return render_to_string("tasks/_collegamenti_body.html", collegamenti_context(request, task), request=request)


@require_GET
@task_permissions_required("tasks_view", api=True)
def collegamenti_cerca(request, project_id: int):
    """Cerca nel catalogo (o fra macchine e incontri) quello che si può collegare a un'attività della commessa."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    tipo = (request.GET.get("tipo") or "").strip()
    task = None
    if (request.GET.get("task") or "").isdigit():
        task = _detail_queryset(request).filter(pk=int(request.GET["task"]), project=project).first()
    try:
        esito = svc.cerca(
            project, tipo, request.GET.get("q", "")[:200], task=task,
            progetti_visibili=scoped_projects_queryset(request),
        )
    except svc.CollegamentoNonValido as exc:
        return _errore(str(exc))
    return JsonResponse({"ok": True, **esito})


@require_POST
@task_permissions_required("tasks_view", api=True)
def collegamenti_azione(request, task_id: int):
    """Collega, aggiungi e collega, scollega, fase e codice del programma. Risponde con il riquadro aggiornato."""
    task = get_object_or_404(_detail_queryset(request), pk=task_id)
    if not task.project_id:
        return _errore("I collegamenti valgono per le attività di una commessa.")
    perm = permessi(request, task)
    post = request.POST
    azione = (post.get("action") or "").strip()
    tipo = (post.get("tipo") or "").strip()
    chiave = (post.get("chiave") or "").strip()
    visibili = scoped_projects_queryset(request)
    nega = _errore("Non puoi cambiare questo collegamento.", 403)
    messaggio = ""

    try:
        if azione in ("collega", "aggiungi"):
            if tipo not in svc.INFO:
                return _errore("Tipo di collegamento non valido.")
            if not _puo(perm, tipo):
                return nega
            if azione == "collega":
                voce = svc.collega(task, tipo, post.get("id"), request.user, progetti_visibili=visibili)
                messaggio = (
                    f"Attività all'ordine del giorno dell'incontro {voce['codice']}" if tipo == svc.INCONTRO
                    else f"{voce['nome']} {voce['codice']} collegato"
                )
            else:
                voce, nuovo = svc.aggiungi(task, tipo, post.get("testo", "")[:400], request.user, progetti_visibili=visibili)
                if not nuovo:
                    messaggio = f"{voce['nome']} {voce['codice']} collegato"
                elif svc.INFO[tipo]["catalogo"]:
                    messaggio = f"{voce['nome']} {voce['codice']} in catalogo e collegato"
                else:
                    messaggio = f"FAI {voce['codice']} aperto"
        elif azione == "scollega":
            prefisso = chiave.partition(":")[0]
            tipo_voce = {"mac": svc.MACCHINA, "att": svc.ATTREZZATURA, "ut": svc.UTENSILE, "ref": svc.CAM, "odg": svc.INCONTRO}.get(prefisso)
            if tipo_voce is None:
                return _errore("Collegamento non valido.")
            if not _puo(perm, tipo_voce):
                return nega
            tolto = svc.scollega(task, chiave, request.user)
            messaggio = (
                f"Tolta dall'ordine del giorno dell'incontro {tolto['codice']}" if tolto["tipo"] == svc.INCONTRO
                else f"{svc.INFO[tolto['tipo']]['nome']} {tolto['codice']} scollegato".replace("  ", " ")
            )
        elif azione in ("fase", "aggiorna"):
            if not perm["programmi"]:
                return nega
            ref = ProjectTechRef.objects.filter(pk=int(chiave[4:]) if chiave.startswith("ref:") and chiave[4:].isdigit() else 0, task=task).first()
            if ref is None:
                return _errore("Collegamento non trovato.", 404)
            if azione == "fase":
                try:
                    programmi_fasi.avanza(ref, request.user, (post.get("valore") or "").strip())
                except programmi_fasi.PassaggioNonValido as exc:
                    return _errore(str(exc))
                messaggio = f"{ref.get_kind_display()} {ref.etichetta_breve}: {ref.get_fase_display().lower()}"
            else:
                if getattr(ref, "fai_record", None) is not None:
                    return _errore("Questo FAI ha la sua scheda: si corregge da lì.")
                svc.aggiorna_programma(ref, request.user, codice=post.get("code", ""), percorso=post.get("path", ""))
                messaggio = f"{ref.get_kind_display()} salvato"
        else:
            return _errore("Azione non valida.")
    except svc.CollegamentoNonValido as exc:
        return _errore(str(exc))

    log_action(request, f"kickoff_collegamento_{azione}", "tasks", {
        "task_id": task.pk, "project_id": task.project_id, "tipo": tipo, "chiave": chiave,
    })
    task = _detail_queryset(request).filter(pk=task.pk).first() or task
    return JsonResponse({"ok": True, "html": _html(request, task), "messaggio": messaggio})
