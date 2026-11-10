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
        "label": "Azione",
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
    ("convocazione", "Convocazione"),
    ("conduzione", "Conduzione"),
    ("esito", "Esito"),
    ("minuta", "Minuta"),
)


def fasi_incontro(meeting: KickoffMeeting, *, attiva: str, can_manage: bool) -> list[dict]:
    """Le quattro fasi di un incontro con stato e collegamento: la barra in testa alle pagine."""
    pid, mid = meeting.project_id, meeting.pk
    svolto = meeting.stato == MeetingStatus.SVOLTO
    annullato = meeting.stato == MeetingStatus.ANNULLATO
    convocato = bool(meeting.convocazione_inviata or meeting.outlook_event_id)
    chiusa = bool(meeting.minuta_chiusa)
    fasi = {
        "convocazione": {
            "fatta": convocato or svolto,
            "nota": "Inviata" if convocato else ("—" if svolto else "Da inviare"),
            "url": reverse("tasks:project_meeting_detail", args=[pid, mid]),
        },
        "conduzione": {
            "fatta": svolto,
            "nota": "Svolta" if svolto else ("Oggi" if meeting.data and meeting.data == _oggi() else "In riunione"),
            "url": reverse("tasks:project_meeting_run", args=[pid, mid]) if can_manage and not svolto and not annullato else None,
        },
        "esito": {
            "fatta": svolto,
            "nota": "Registrato" if svolto else "Dopo l'incontro",
            "url": reverse("tasks:project_meeting_minutes", args=[pid, mid]) if can_manage and not chiusa and not annullato else None,
        },
        "minuta": {
            "fatta": chiusa and meeting.minuta_inviata,
            "nota": ("Inviata" if meeting.minuta_inviata else "Approvata") if chiusa else ("Da approvare" if svolto else "—"),
            "url": reverse("tasks:project_meeting_detail", args=[pid, mid]) + "#documenti",
        },
    }
    return [
        {"key": key, "label": label, "attiva": key == attiva, **fasi[key]}
        for key, label in FASI
    ] if not annullato else []


def _oggi():
    from django.utils import timezone

    return timezone.localdate()
