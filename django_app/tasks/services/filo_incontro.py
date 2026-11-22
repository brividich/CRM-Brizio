"""Filo dell'incontro: chi lega punti, problemi, azioni e decisioni di un incontro.

Un problema, un'azione o una decisione nascono mentre si parla di un punto
dell'ordine del giorno (`punto` = id stabile del punto). Da qui conduzione,
dettaglio ed esito mostrano le stesse voci sotto il punto da cui vengono,
e la barra delle fasi porta da convocazione a minuta senza perdersi.
"""
from __future__ import annotations

from django.urls import reverse

from ..models import (
    KickoffMeeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingIssue,
    MeetingStatus,
)


def _nome(user) -> str:
    if user is None:
        return ""
    return user.get_full_name() or user.username


def punti_index(items) -> dict[str, dict]:
    """id punto -> {"num", "titolo"}: numerazione come a video (dall'1)."""
    return {
        str(item.get("id")): {"num": index, "titolo": str(item.get("titolo") or "")}
        for index, item in enumerate((i for i in (items or []) if isinstance(i, dict)), start=1)
        if item.get("id")
    }


def voce_issue(issue: MeetingIssue, punti: dict, project_id: int, meeting_id: int) -> dict:
    punto = punti.get(issue.punto or "")
    return {
        "kind": "issue",
        "label": "Problema",
        "id": issue.pk,
        "titolo": issue.title,
        "chiusa": issue.is_resolved,
        "stato": "Risolto" if issue.is_resolved else "Aperto",
        "chi": _nome(issue.assigned_to),
        "scadenza": issue.due_date,
        "punto": issue.punto,
        "punto_num": punto["num"] if punto else None,
        "punto_titolo": punto["titolo"] if punto else "",
        "nota": issue.resolution_note,
        "assigned_to_id": issue.assigned_to_id,
        "url": reverse("tasks:project_meeting_issue_status", args=[project_id, meeting_id, issue.pk]),
    }


def voce_action(action: MeetingActionItem, punti: dict, project_id: int, meeting_id: int) -> dict:
    punto = punti.get(action.punto or "")
    return {
        "kind": "action",
        "label": "Attività d'incontro",
        "id": action.pk,
        "titolo": action.title,
        "chiusa": action.is_done,
        "stato": action.get_status_display(),
        "chi": _nome(action.assigned_to),
        "scadenza": action.due_date,
        "scaduta": action.is_overdue,
        "punto": action.punto,
        "punto_num": punto["num"] if punto else None,
        "punto_titolo": punto["titolo"] if punto else "",
        "assigned_to_id": action.assigned_to_id,
        "url": reverse("tasks:project_meeting_action_status", args=[project_id, meeting_id, action.pk]),
    }


def voce_decision(decision: MeetingDecision, punti: dict) -> dict:
    punto = punti.get(decision.punto or "")
    return {
        "kind": "decision",
        "label": "Decisione",
        "id": decision.pk,
        "titolo": decision.testo,
        "chiusa": False,
        "stato": f"Impatto {decision.get_impatto_display().lower()}",
        "chi": _nome(decision.decisa_da),
        "scadenza": None,
        "punto": decision.punto,
        "punto_num": punto["num"] if punto else None,
        "punto_titolo": punto["titolo"] if punto else "",
    }


def emersi(meeting: KickoffMeeting, items=None) -> dict:
    """Quello che e' nato in questo incontro, diviso per tipo e per punto.

    Ritorna {"issues", "actions", "decisions", "per_punto": {id: [voci]}, "totale"}.
    """
    items = meeting.agenda_items if items is None else items
    punti = punti_index(items)
    pid, mid = meeting.project_id, meeting.pk
    issues = [
        voce_issue(i, punti, pid, mid)
        for i in meeting.issues_created.select_related("assigned_to").order_by("created_at", "id")
    ]
    actions = [
        voce_action(a, punti, pid, mid)
        for a in meeting.actions_raised.select_related("assigned_to").order_by("created_at", "id")
    ]
    decisions = [
        voce_decision(d, punti)
        for d in meeting.decisions.select_related("decisa_da").order_by("created_at", "id")
    ]
    per_punto: dict[str, list[dict]] = {}
    for voce in issues + actions + decisions:
        if voce["punto_num"]:
            per_punto.setdefault(voce["punto"], []).append(voce)
    return {
        "issues": issues,
        "actions": actions,
        "decisions": decisions,
        "per_punto": per_punto,
        "totale": len(issues) + len(actions) + len(decisions),
    }


def voci_collegate(meeting: KickoffMeeting, items) -> dict[str, dict]:
    """Punti che riportano un problema o un'azione aperti: id punto -> voce viva.

    In conduzione e nel dettaglio il punto «Problema aperto: …» mostra stato,
    responsabile e il pulsante per chiuderlo, invece di un testo fermo.
    """
    issue_ids = {int(i["issue_id"]) for i in items if isinstance(i, dict) and i.get("issue_id")}
    action_ids = {int(i["action_id"]) for i in items if isinstance(i, dict) and i.get("action_id")}
    if not issue_ids and not action_ids:
        return {}
    punti = punti_index(items)
    pid, mid = meeting.project_id, meeting.pk
    issues = {
        i.pk: voce_issue(i, punti, pid, mid)
        for i in MeetingIssue.objects.filter(project_id=pid, pk__in=issue_ids).select_related("assigned_to", "source_meeting")
    }
    actions = {
        a.pk: voce_action(a, punti, pid, mid)
        for a in MeetingActionItem.objects.filter(project_id=pid, pk__in=action_ids).select_related("assigned_to", "source_meeting")
    }
    out: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        voce = None
        if item.get("issue_id"):
            voce = issues.get(int(item["issue_id"]))
        elif item.get("action_id"):
            voce = actions.get(int(item["action_id"]))
        if voce:
            out[str(item.get("id"))] = voce
    return out


def punti_con_filo(meeting: KickoffMeeting, items, *, emersi_data: dict | None = None) -> list[dict]:
    """Punti dell'ordine del giorno arricchiti con la voce collegata e quello che e' emerso lì."""
    emersi_data = emersi_data or emersi(meeting, items)
    collegate = voci_collegate(meeting, items)
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id"))
        out.append({
            **item,
            "collegata": collegate.get(key),
            "emersi": emersi_data["per_punto"].get(key, []),
        })
    return out


FASI = (
    ("prima", "Prima"),
    ("durante", "Durante"),
    ("dopo", "Dopo"),
)
# Le pagine chiamavano le fasi con i nomi di prima (quattro): restano validi.
_FASE_DI = {"convocazione": "prima", "conduzione": "durante", "esito": "dopo", "minuta": "dopo"}


def fasi_incontro(meeting: KickoffMeeting, *, attiva: str, can_manage: bool) -> list[dict]:
    """Le tre fasi di un incontro (prima, durante, dopo) con stato e collegamento.

    È la barra in testa a scheda, convocazione, conduzione ed esito: l'incontro è
    una cosa sola che cambia stato, le pagine sono i suoi tre momenti.
    """
    pid, mid = meeting.project_id, meeting.pk
    attiva = _FASE_DI.get(attiva, attiva)
    svolto = meeting.stato == MeetingStatus.SVOLTO
    annullato = meeting.stato == MeetingStatus.ANNULLATO
    convocato = bool(meeting.convocazione_inviata or meeting.outlook_event_id)
    chiusa = bool(meeting.minuta_chiusa)
    scheda = reverse("tasks:project_meeting_detail", args=[pid, mid])
    if svolto:
        nota_dopo = ("Minuta inviata" if meeting.minuta_inviata else "Minuta approvata") if chiusa else "Minuta da approvare"
        url_dopo = scheda
    else:
        nota_dopo = "Esito e minuta"
        url_dopo = reverse("tasks:project_meeting_minutes", args=[pid, mid]) if can_manage else None
    fasi = {
        "prima": {
            "fatta": convocato or svolto,
            "nota": "Convocazione inviata" if convocato else ("Ordine del giorno" if svolto else "Convocazione da inviare"),
            # A incontro svolto la scheda è il «dopo»: il «prima» resta come traccia.
            "url": None if svolto else scheda,
        },
        "durante": {
            "fatta": svolto,
            "nota": "Svolto" if svolto else ("Oggi" if meeting.data and meeting.data == _oggi() else "Conduzione"),
            "url": reverse("tasks:project_meeting_run", args=[pid, mid]) if can_manage and not svolto else None,
        },
        "dopo": {
            "fatta": chiusa and meeting.minuta_inviata,
            "nota": nota_dopo,
            "url": url_dopo,
        },
    }
    return [
        {"key": key, "label": label, "attiva": key == attiva, **fasi[key]}
        for key, label in FASI
    ] if not annullato else []


def _oggi():
    from django.utils import timezone

    return timezone.localdate()


def _aperti_precedenti(meeting: KickoffMeeting):
    """Problemi e attività d'incontro ancora aperti della commessa, non nati in questo incontro.

    Conta l'incontro d'origine, non il numero: un incontro pianificato per primo può
    tenersi dopo un altro, e quello che lì è rimasto aperto va comunque riportato.
    """
    from .agenda import _open_meeting_actions_for_project, _open_meeting_issues_for_project

    def precedente(obj) -> bool:
        return obj.source_meeting_id != meeting.pk

    project = meeting.project
    issues = [i for i in _open_meeting_issues_for_project(project) if precedente(i)]
    actions = [a for a in _open_meeting_actions_for_project(project) if precedente(a)]
    return issues, actions


def _ids_in_odg(items, chiave: str) -> set[int]:
    out: set[int] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            valore = int(item.get(chiave) or 0)
        except (TypeError, ValueError):
            valore = 0
        if valore:
            out.add(valore)
    return out


def dagli_incontri_precedenti(meeting: KickoffMeeting, items=None) -> list[dict]:
    """Quello che è rimasto aperto dagli incontri precedenti, da portare all'ordine del giorno.

    Ogni voce dice se è già un punto di questo incontro (`in_odg`): la scheda mostra
    solo quelle che mancano, così «Aggiungi all'ordine del giorno» non crea doppioni.
    """
    items = meeting.agenda_items if items is None else items
    issues, actions = _aperti_precedenti(meeting)
    issue_ids = _ids_in_odg(items, "issue_id")
    action_ids = _ids_in_odg(items, "action_id")
    voci = [
        {
            "tipo": "issue", "label": "Problema", "id": i.pk, "titolo": i.title,
            "chi": _nome(i.assigned_to), "scadenza": i.due_date, "scaduta": False,
            "origine": i.source_meeting.numero if i.source_meeting_id else None,
            "in_odg": i.pk in issue_ids,
        }
        for i in issues
    ]
    voci += [
        {
            "tipo": "action", "label": "Attività d'incontro", "id": a.pk, "titolo": a.title,
            "chi": _nome(a.assigned_to), "scadenza": a.due_date, "scaduta": a.is_overdue,
            "origine": a.source_meeting.numero if a.source_meeting_id else None,
            "in_odg": a.pk in action_ids,
        }
        for a in actions
    ]
    return voci


def punto_da_precedente(meeting: KickoffMeeting, tipo: str, voce_id: int) -> tuple[dict | None, bool]:
    """Il punto da aggiungere per una voce aperta degli incontri precedenti.

    Ritorna (punto, gia_presente); (None, False) se la voce non è fra quelle riportabili.
    """
    from .agenda import _meeting_action_agenda_item, _meeting_issue_agenda_item

    issues, actions = _aperti_precedenti(meeting)
    items = meeting.agenda_items
    if tipo == "issue":
        obj = next((i for i in issues if i.pk == voce_id), None)
        if obj is None:
            return None, False
        return _meeting_issue_agenda_item(obj), obj.pk in _ids_in_odg(items, "issue_id")
    if tipo == "action":
        obj = next((a for a in actions if a.pk == voce_id), None)
        if obj is None:
            return None, False
        return _meeting_action_agenda_item(obj), obj.pk in _ids_in_odg(items, "action_id")
    return None, False
