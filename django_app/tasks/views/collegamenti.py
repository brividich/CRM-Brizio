"""Riquadro «Collegamenti» dell'attività e registro della commessa che ne deriva."""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit import log_action

from ..access import (
    _detail_queryset,
    can_manage_project,
    can_manage_task,
    scoped_projects_queryset,
    scoped_tasks_queryset,
    task_permissions_required,
)
from ..models import ProjectTechRef, Task, TaskStatus, TechRefKind
from ..services import collegamenti as svc
from ..services import programmi_fasi
from ..services.tappe import _finestra, disponibilita_macchina

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


def _visibili(request) -> set[int]:
    """Attività che chi guarda può vedere: negli avvisi di conflitto le altre restano senza titolo."""
    if not hasattr(request, "_kc_visibili"):
        request._kc_visibili = set(scoped_tasks_queryset(request).values_list("id", flat=True))
    return request._kc_visibili


def collegamenti_context(request, task: Task, *, apri: str = "") -> dict:
    """Contesto del riquadro per un'attività che esiste già."""
    if not task.project_id:
        return {"col": None}
    perm = permessi(request, task)
    dati = svc.riquadro(task, visibili=_visibili(request))
    con_nomi = _con_nomi(request)
    for voce in dati["voci"]:
        if voce["tipo"] == svc.MACCHINA and "conflitti" in voce:
            # Abilitati e assenze nel periodo: gli impegni sono già l'avviso della riga.
            voce["operatori"] = disponibilita_macchina(voce["asset"], *_finestra(task), con_nomi=con_nomi)
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
        "url_azione": "", "url_cerca": reverse("tasks:collegamenti_cerca", args=[project.pk]), "apri": "",
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
    messaggio = avviso = ""

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
                if tipo == svc.MACCHINA:
                    # Solo avviso: la macchina resta collegata anche se nel periodo è già impegnata.
                    inizio, fine = _finestra(task)
                    avviso = svc.avviso_macchina(
                        svc.conflitti_macchina(voce["asset"], inizio, fine, escludi_task_id=task.pk, visibili=_visibili(request)),
                        inizio, fine,
                    )
                    messaggio = f"Macchina {voce['codice']} collegata"
                    if avviso:
                        avviso = f"Macchina {voce['codice']} collegata, ma nel periodo è già impegnata. {avviso}"
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
    return JsonResponse({"ok": True, "html": _html(request, task), "messaggio": "" if avviso else messaggio, "avviso": avviso})


# --- Registro della commessa («Programmi e FAI») ------------------------------

def registro_context(request, project) -> dict:
    """«Programmi e FAI» come registro costruito dalle attività. Chi non ha il diritto vede senza comandi."""
    from ..services.fai import esito_progetto

    gestisce = can_manage_project(request, project)
    puo_creare = gestisce or request.user.pk in project.team_user_ids
    esito = esito_progetto(project)
    dati = svc.registro(project, visibili=_visibili(request))
    for riga in dati["righe"]:
        ref = riga.get("ref")
        task = riga["task"]
        # La fase la cambia chi gestisce o chi ha il programma (regola di sempre).
        riga["puo_fase"] = bool(riga["fasi"]) and (
            gestisce or (ref is not None and ref.assigned_to_id == request.user.pk)
            or (task is not None and task.assigned_to_id == request.user.pk)
        )
        riga["puo_togliere"] = gestisce
        riga["puo_eliminare"] = gestisce and task is None and getattr(ref, "fai_record", None) is None
        # FAI: dalla riga si apre la scheda, o la si compila se non c'è ancora.
        riga["scheda_url"], riga["scheda_label"] = "", ""
        if riga["tipo"] == svc.FAI and riga["url"]:
            if getattr(ref, "fai_record", None) is not None:
                riga["scheda_url"], riga["scheda_label"] = riga["url"], "Apri"
            elif puo_creare:
                causale = f"&causale={esito.causale}" if esito and esito.causale else ""
                riga["scheda_url"], riga["scheda_label"] = riga["url"] + causale, "Compila"
    aperte = [t for t in dati["attivita"] if t.status != TaskStatus.DONE]
    ha_fai = any(r["tipo"] == svc.FAI for r in dati["righe"])
    return {
        "project": project,
        "reg": dati,
        "reg_gestisce": gestisce,
        "reg_attivita": aperte or dati["attivita"],
        "reg_ha_fai": ha_fai,
        "reg_url": reverse("tasks:collegamenti_registro", args=[project.pk]),
        "fai_esito": esito,
        "fai_puo_creare": puo_creare,
        # Il FAI assegnato e non ancora compilato si completa, non se ne apre un altro.
        "fai_ref_libera": next((r["ref"] for r in dati["righe"] if r["tipo"] == svc.FAI and getattr(r["ref"], "fai_record", None) is None), None),
        # Se poi qualcuno apre comunque un FAI, vale il FAI.
        "fai_non_richiesto": project.fai_non_richiesto_il is not None and not ha_fai,
    }


def registro_html(request, project) -> str:
    return render_to_string("tasks/_registro_collegamenti_body.html", registro_context(request, project), request=request)


@require_http_methods(["GET", "POST"])
@task_permissions_required("tasks_view", api=True)
def collegamenti_registro(request, project_id: int):
    """GET: il registro aggiornato. POST: fase del programma, togli, collega o elimina una voce senza attività."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "html": registro_html(request, project)})
    gestisce = can_manage_project(request, project)
    post = request.POST
    azione = (post.get("action") or "").strip()
    chiave = (post.get("chiave") or "").strip()
    nega = _errore("Solo chi gestisce la commessa può farlo.", 403)

    def attivita():
        if not (post.get("task") or "").isdigit():
            return None
        return Task.objects.filter(pk=int(post["task"]), project=project).exclude(status=TaskStatus.CANCELED).first()

    try:
        if azione == "fase":
            ident = int(chiave[4:]) if chiave.startswith("ref:") and chiave[4:].isdigit() else 0
            ref = ProjectTechRef.objects.filter(pk=ident, project=project).select_related("task").first()
            if ref is None:
                return _errore("Programma non trovato in questa commessa.", 404)
            incaricato = ref.assigned_to_id == request.user.pk or (ref.task_id and ref.task.assigned_to_id == request.user.pk)
            if not (gestisce or incaricato):
                return _errore("Il programma lo aggiorna chi ne è responsabile o il capocommessa.", 403)
            try:
                programmi_fasi.avanza(ref, request.user, (post.get("valore") or "").strip())
            except programmi_fasi.PassaggioNonValido as exc:
                return JsonResponse({"ok": False, "reason": str(exc), "html": registro_html(request, project)}, status=400)
            messaggio = f"{ref.get_kind_display()} {ref.etichetta_breve}: {ref.get_fase_display().lower()}"
        elif azione in ("togli", "orfano"):
            if not gestisce:
                return nega
            task = attivita()
            if task is None:
                return _errore("Attività non trovata in questa commessa.", 404)
            if azione == "togli":
                tolto = svc.scollega(task, chiave, request.user)
                messaggio = f"{svc.INFO[tolto['tipo']]['nome']} {tolto['codice']} scollegato".replace("  ", " ")
            else:
                voce = svc.collega_orfano(task, chiave, request.user)
                messaggio = f"{voce['nome']} {voce['codice']} collegato a «{task.title}»"
        elif azione == "elimina":
            if not gestisce:
                return nega
            tolto = svc.elimina_orfano(project, chiave)
            messaggio = f"{svc.INFO[tolto['tipo']]['nome']} {tolto['codice']} tolto dalla commessa".replace("  ", " ")
        elif azione == "fai_non_richiesto":
            if not gestisce:
                return nega
            non_richiesto = post.get("valore") == "1"
            if non_richiesto and project.tech_refs.filter(kind=TechRefKind.FAI).exists():
                return _errore("Questa commessa ha già un FAI: toglilo prima.")
            project.fai_non_richiesto_il = timezone.now() if non_richiesto else None
            project.fai_non_richiesto_da = request.user if non_richiesto else None
            project.save(update_fields=["fai_non_richiesto_il", "fai_non_richiesto_da"])
            messaggio = "FAI non richiesto per questo kickoff" if non_richiesto else "FAI di nuovo richiesto"
        else:
            return _errore("Azione non valida.")
    except svc.CollegamentoNonValido as exc:
        return _errore(str(exc))

    log_action(request, f"kickoff_registro_{azione}", "tasks", {"project_id": project.pk, "chiave": chiave})
    project.refresh_from_db()
    return JsonResponse({"ok": True, "html": registro_html(request, project), "messaggio": messaggio})
