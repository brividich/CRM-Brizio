"""Percorso del kickoff: pannello delle attività base in commessa e negli incontri."""
from __future__ import annotations

from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..models import KickoffMeeting, TappaKickoff
from ..services import tappe as svc
from ..services.meeting_tasks import KickoffBloccatoVRF
from ._shared import _utenti_riga_rapida


def _fornitori():
    try:
        from anagrafica.models import Fornitore

        return list(Fornitore.objects.filter(is_active=True).order_by("ragione_sociale").values_list("ragione_sociale", flat=True))
    except Exception:
        return []


def _processi():
    try:
        from anagrafica.models_mpq import ProcessoQualificato

        return list(
            ProcessoQualificato.objects.filter(stato=ProcessoQualificato.STATO_ATTIVO)
            .order_by("nome").values_list("nome", flat=True).distinct()
        )
    except Exception:
        return []


def _con_nomi(request) -> bool:
    try:
        from anagrafica.services.struttura_macchina import puo_vedere_nomi

        return bool(puo_vedere_nomi(request))
    except Exception:
        return False


def _utensili_catalogo():
    from ..models import Utensile

    return list(Utensile.objects.filter(attivo=True).order_by("codice")[:500])


def tappe_context(request, project, meeting=None) -> dict:
    gestisce = can_manage_project(request, project)
    dati = svc.percorso(project, con_nomi=_con_nomi(request), utente=request.user)
    serve = {r["key"] for r in dati["righe"] if r["puo_aggiungere"]}
    return {
        "project": project,
        "tappe": dati,
        "tappe_meeting": meeting,
        "tappe_puo_assegnare": gestisce or request.user.pk in project.team_user_ids,
        "tappe_puo_escludere": gestisce,
        "tappe_puo_fissare_piano": gestisce,
        "tappe_utenti": _utenti_riga_rapida(project),
        "tappe_macchine": list(svc.macchine_disponibili()) if TappaKickoff.MACCHINA in serve else [],
        "tappe_fornitori": _fornitori() if TappaKickoff.TERZISTA in serve else [],
        "tappe_processi": _processi() if TappaKickoff.PROCESSI in serve else [],
        "tappe_outlook": svc.outlook_disponibile(),
        "tappe_utensili_catalogo": _utensili_catalogo() if TappaKickoff.UTENSILI in {r["key"] for r in dati["righe"]} else [],
        "tappe_oggi": timezone.localdate(),
    }


def _data(valore):
    testo = (valore or "").strip()
    return date.fromisoformat(testo) if testo else None


def _errore(motivo: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "reason": motivo}, status=status)


@require_POST
@task_permissions_required("tasks_view", api=True)
def tappa_azione(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    gestisce = can_manage_project(request, project)
    post = request.POST
    key = (post.get("tappa") or "").strip()
    azione = (post.get("action") or "").strip()
    if key not in TappaKickoff.values:
        return _errore("Tappa non valida.")
    meeting = None
    if (post.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(post["meeting_id"]), project=project).first()

    try:
        if azione == "assegna":
            if not (gestisce or request.user.pk in project.team_user_ids):
                return _errore("Solo chi fa parte del team può assegnare le tappe.", 403)
            assegnato = None
            if (post.get("assigned_to") or "").strip():
                from ..forms import task_active_users_queryset

                raw = post["assigned_to"].strip()
                assegnato = task_active_users_queryset().filter(pk=int(raw)).first() if raw.isdigit() else None
                if assegnato is None:
                    return _errore("Responsabile non valido.")
            try:
                due = _data(post.get("due_date"))
                inizio = _data(post.get("start_date"))
            except ValueError:
                return _errore("Data non valida.")
            asset = None
            if key == TappaKickoff.MACCHINA and (post.get("asset") or "").isdigit():
                asset = svc.macchine_disponibili().filter(pk=int(post["asset"])).first()
            task = svc.assegna(
                project, key, request.user, assigned_to=assegnato, due_date=due, start_date=inizio, asset=asset,
                testo=(post.get("testo") or "").strip(), meeting=meeting,
                outlook=post.get("outlook") == "1" and svc.outlook_disponibile(), request=request,
                attrezzatura=(post.get("attrezzatura") or "").strip() or None,
            )
            log_action(request, "kickoff_tappa_assegna", "tasks", {"project_id": project.pk, "tappa": key, "task_id": task.pk})
        elif azione in ("escludi", "ripristina"):
            if not gestisce:
                return _errore("Solo chi gestisce la commessa può deciderlo.", 403)
            svc.escludi(project, key, valore=azione == "escludi")
            log_action(request, f"kickoff_tappa_{azione}", "tasks", {"project_id": project.pk, "tappa": key})
        else:
            return _errore("Azione non valida.")
    except KickoffBloccatoVRF:
        return _errore("Kickoff bloccato: manca la VRF.", 409)
    except svc.TappaNonValida as exc:
        return _errore(str(exc))

    project.refresh_from_db()
    html = render_to_string("tasks/_tappe_body.html", tappe_context(request, project, meeting), request=request)
    return JsonResponse({"ok": True, "html": html})


@require_GET
@task_permissions_required("tasks_view", api=True)
def tappa_anteprima(request, project_id: int):
    """Mentre si compila la tappa: assenze del responsabile e disponibilità della macchina nel periodo."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not (can_manage_project(request, project) or request.user.pk in project.team_user_ids):
        return _errore("Solo chi fa parte del team può assegnare le tappe.", 403)
    try:
        inizio, fine = svc.periodo(_data(request.GET.get("start_date")), _data(request.GET.get("due_date")))
    except ValueError:
        return JsonResponse({"ok": True, "html": ""})
    persona = assenze = None
    raw = (request.GET.get("assigned_to") or "").strip()
    if raw.isdigit():
        from ..forms import task_active_users_queryset

        persona = task_active_users_queryset().filter(pk=int(raw)).first()
        assenze = svc.assenze_persona(persona, inizio, fine) if persona else None
        impegni_persona = svc.carico([persona.pk], inizio, fine).get(persona.pk, 0) if persona else 0
    macchina = None
    if request.GET.get("tappa") == TappaKickoff.MACCHINA and (request.GET.get("asset") or "").isdigit():
        asset = svc.macchine_disponibili().filter(pk=int(request.GET["asset"])).first()
        if asset is not None:
            macchina = svc.disponibilita_macchina(asset, inizio, fine, con_nomi=_con_nomi(request))
    html = render_to_string("tasks/_tappe_anteprima.html", {
        "inizio": inizio, "fine": fine, "persona": persona, "assenze": assenze, "m": macchina,
        "impegni_persona": impegni_persona if raw.isdigit() else 0,
    }, request=request)
    return JsonResponse({"ok": True, "html": html})


@require_POST
@task_permissions_required("tasks_view", api=True)
def utensili_azione(request, project_id: int):
    """Utensili della commessa: aggiungi, cambia stato, togli. Risponde con il Percorso aggiornato."""
    from ..models import ProjectUtensile, UtensileStato

    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not (can_manage_project(request, project) or request.user.pk in project.team_user_ids):
        return _errore("Solo chi fa parte del team aggiorna gli utensili.", 403)
    azione = (request.POST.get("action") or "").strip()
    meeting = None
    if (request.POST.get("meeting_id") or "").isdigit():
        meeting = KickoffMeeting.objects.filter(pk=int(request.POST["meeting_id"]), project=project).first()
    try:
        if azione == "aggiungi":
            raw_q = (request.POST.get("quantita") or "1").strip()
            svc.aggiungi_utensile(
                project, request.user, request.POST.get("utensile", ""),
                quantita=int(raw_q) if raw_q.isdigit() else 1, entro=_data(request.POST.get("entro")),
            )
        elif azione in ("stato", "togli"):
            riga = ProjectUtensile.objects.filter(pk=int(request.POST.get("riga") or 0), project=project).first()
            if riga is None:
                return _errore("Utensile non trovato.", 404)
            if azione == "togli":
                riga.delete()
            else:
                stato = (request.POST.get("stato") or "").strip()
                if stato not in UtensileStato.values:
                    return _errore("Stato non valido.")
                riga.stato = stato
                riga.save(update_fields=["stato", "updated_at"])
        else:
            return _errore("Azione non valida.")
    except (svc.TappaNonValida, ValueError) as exc:
        return _errore(str(exc) or "Dati non validi.")
    log_action(request, f"kickoff_utensili_{azione}", "tasks", {"project_id": project.pk})
    html = render_to_string("tasks/_tappe_body.html", tappe_context(request, project, meeting), request=request)
    return JsonResponse({"ok": True, "html": html})
