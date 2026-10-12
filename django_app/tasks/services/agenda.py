"""Ordine del giorno degli incontri: voci riportate, suggerimenti, modelli."""
from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from django.db.models import Q


from ..models import (
    KickoffMeeting,
    MeetingActionStatus,
    MeetingAgendaTemplate,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
    Project,
)

logger = logging.getLogger(__name__)


def _parse_agenda_template_items(raw: str) -> list[dict]:
    """Un punto per riga, «Titolo | durata» per indicare i minuti stimati."""
    items: list[dict] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        titolo, _, durata_raw = line.partition("|")
        titolo = titolo.strip()[:200]
        if not titolo:
            continue
        try:
            durata = int(durata_raw.strip())
            if durata <= 0 or durata > 480:
                durata = None
        except (TypeError, ValueError):
            durata = None
        items.append({"titolo": titolo, "nota": "", "durata_minuti": durata})
    return items


def _parse_optional_date(value: str):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _issue_display_owner(issue: MeetingIssue) -> str:
    if issue.assigned_to_id:
        return issue.assigned_to.get_full_name() or issue.assigned_to.username
    return ""


def _meeting_issue_agenda_item(issue: MeetingIssue) -> dict:
    custom_fields = [{"label": "Stato", "value": issue.get_status_display()}]
    owner = _issue_display_owner(issue)
    if owner:
        custom_fields.append({"label": "Responsabile", "value": owner})
    if issue.due_date:
        custom_fields.append({"label": "Scadenza", "value": issue.due_date.strftime("%d-%m-%Y")})
    if issue.source_meeting_id:
        custom_fields.append({"label": "Origine", "value": f"Incontro {issue.source_meeting.numero}"})
    return {
        "id": f"issue-{issue.pk}",
        "titolo": f"Problema aperto: {issue.title}",
        "nota": issue.description,
        "task_id": issue.linked_task_id,
        "task_label": issue.linked_task.title if issue.linked_task_id else "",
        "issue_id": issue.pk,
        "source": "meeting_issue",
        "locked": True,
        "custom_fields": custom_fields,
        "done": issue.is_resolved,
    }


def _open_meeting_actions_for_project(project: Project):
    return (
        project.meeting_actions
        .filter(status=MeetingActionStatus.OPEN)
        .select_related("source_meeting", "assigned_to", "linked_task")
        .order_by("due_date", "created_at", "id")
    )


def _meeting_action_agenda_item(action) -> dict:
    """Un'azione aperta entra nell'agenda del prossimo incontro, come i problemi."""
    custom_fields = [{"label": "Stato", "value": action.get_status_display()}]
    if action.assigned_to_id:
        owner = action.assigned_to.get_full_name() or action.assigned_to.username
        custom_fields.append({"label": "Responsabile", "value": owner})
    if action.due_date:
        custom_fields.append({"label": "Scadenza", "value": action.due_date.strftime("%d-%m-%Y")})
    if action.source_meeting_id:
        custom_fields.append({"label": "Origine", "value": f"Incontro {action.source_meeting.numero}"})
    return {
        "id": f"action-{action.pk}",
        "titolo": f"Azione aperta: {action.title}",
        "nota": action.description,
        "task_id": action.linked_task_id,
        "task_label": action.linked_task.title if action.linked_task_id else "",
        "issue_id": None,
        "action_id": action.pk,
        "source": "meeting_action",
        "locked": True,
        "custom_fields": custom_fields,
        "done": action.is_done,
    }


def _carry_over_agenda_items(project: Project) -> list[dict]:
    """Punti non trattati nell'ultimo incontro svolto, da riproporre nel prossimo.

    Rolling agenda: quello che non si e' fatto in tempo non deve sparire. I
    problemi aperti arrivano gia' per la loro strada (`_meeting_issue_agenda_item`),
    quindi qui si escludono per non duplicarli.
    """
    last = (
        project.meetings
        .filter(stato=MeetingStatus.SVOLTO)
        .order_by("-numero")
        .first()
    )
    if last is None:
        return []

    carried: list[dict] = []
    for index, item in enumerate(last.agenda_items or []):
        if not isinstance(item, dict) or item.get("done"):
            continue
        if item.get("issue_id") or item.get("source") == "meeting_issue":
            continue
        if item.get("action_id") or item.get("source") == "meeting_action":
            continue
        titolo = str(item.get("titolo", "")).strip()
        if not titolo:
            continue
        custom_fields = [
            field
            for field in (item.get("custom_fields") or [])
            if isinstance(field, dict) and field.get("label") != "Riportato da"
        ]
        custom_fields.append({"label": "Riportato da", "value": f"Incontro {last.numero}"})
        carried.append({
            "id": f"carry-{last.pk}-{item.get('id') or index}",
            "titolo": titolo,
            "nota": str(item.get("nota", "")).strip(),
            "task_id": item.get("task_id"),
            "task_label": str(item.get("task_label", "")).strip(),
            "issue_id": None,
            "source": "carry_over",
            "locked": False,
            "responsabile_id": item.get("responsabile_id"),
            "responsabile_label": str(item.get("responsabile_label", "")).strip(),
            "durata_minuti": item.get("durata_minuti"),
            "custom_fields": custom_fields,
            "done": False,
        })
    return carried


def _agenda_templates_payload() -> list[dict]:
    """Modelli ODG attivi, pronti per il selettore del form incontro."""
    return [
        {"nome": template.nome, "items": template.items or []}
        for template in MeetingAgendaTemplate.objects.filter(is_active=True)
    ]


# Quanti incontri passati si guardano per costruire i suggerimenti ODG: il
# JSON degli items si scandisce in Python (JSONField non e' aggregabile in SQL
# Server), quindi la finestra resta limitata per non pesare sul form.
AGENDA_SUGGESTIONS_SCAN_LIMIT = 400
AGENDA_SUGGESTIONS_MAX = 60


def _agenda_title_suggestions() -> list[dict]:
    """Titoli ODG gia' usati negli altri incontri, per suggerirli in fase di stesura.

    Ogni incontro riscriveva a mano punti che in azienda si ripetono («Stato
    avanzamento», «Non conformita' aperte»): qui si raccolgono i titoli
    dall'ordine del giorno degli incontri passati, di qualunque commessa, con
    la nota e la durata dell'uso piu' recente come precompilazione.

    Esclusi i punti generati automaticamente (problemi tracciati e azioni
    aperte): non sono testo scritto da qualcuno, e come suggerimento
    riproporrebbero il problema di un'altra commessa.
    """
    rows = (
        KickoffMeeting.objects
        .order_by("-id")
        .values_list("agenda_items", flat=True)[:AGENDA_SUGGESTIONS_SCAN_LIMIT]
    )
    suggestions: dict[str, dict] = {}
    for items in rows:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("issue_id") or item.get("action_id"):
                continue
            titolo = str(item.get("titolo", "")).strip()
            if not titolo:
                continue
            key = titolo.casefold()
            existing = suggestions.get(key)
            if existing is None:
                # I meeting arrivano dal piu' recente: la prima occorrenza e'
                # quella da cui prendere nota e durata.
                durata = item.get("durata_minuti")
                suggestions[key] = {
                    "titolo": titolo,
                    "nota": str(item.get("nota", "")).strip(),
                    "durata_minuti": durata if isinstance(durata, int) else None,
                    "usi": 1,
                }
            else:
                existing["usi"] += 1
    ordered = sorted(suggestions.values(), key=lambda s: (-s["usi"], s["titolo"].casefold()))
    return ordered[:AGENDA_SUGGESTIONS_MAX]


def _previous_meeting_agenda(project: Project, *, exclude_meeting_id: int | None = None) -> list[dict]:
    """Punti dell'ultimo incontro della commessa, per il «duplica ODG precedente».

    Esclude i punti agganciati a un problema tracciato: quelli arrivano gia'
    dal carry-over automatico e duplicarli creerebbe doppioni.
    """
    qs = project.meetings.order_by("-numero")
    if exclude_meeting_id:
        qs = qs.exclude(pk=exclude_meeting_id)
    last = qs.first()
    if last is None:
        return []
    items = []
    for item in last.agenda_items or []:
        if not isinstance(item, dict) or item.get("issue_id"):
            continue
        titolo = str(item.get("titolo", "")).strip()
        if not titolo:
            continue
        items.append({
            "titolo": titolo,
            "nota": str(item.get("nota", "")).strip(),
            "durata_minuti": item.get("durata_minuti"),
        })
    return items


def _project_tasks_for_picker(project: Project) -> list[dict]:
    """Attivita' del kickoff selezionabili nei picker agenda/problemi.

    Nessun troncamento: una lista tagliata a N faceva sparire in silenzio le
    attivita' oltre la soglia dal menu «collega a un'attivita'».
    """
    return list(project.tasks.values("id", "title", "status").order_by("title"))


def _open_meeting_issues_for_project(project: Project):
    return (
        project.meeting_issues
        .filter(status=MeetingIssueStatus.OPEN)
        .select_related("source_meeting", "assigned_to", "linked_task")
        .order_by("due_date", "created_at", "id")
    )


def _meeting_issue_ids_from_agenda(meeting: KickoffMeeting) -> list[int]:
    ids: list[int] = []
    for item in meeting.agenda_items or []:
        if not isinstance(item, dict):
            continue
        try:
            issue_id = int(item.get("issue_id") or 0)
        except (TypeError, ValueError):
            issue_id = 0
        if issue_id:
            ids.append(issue_id)
    return ids


def _set_meeting_agenda_issue_done(meeting: KickoffMeeting, issue_id: int, done: bool) -> None:
    agenda_items = meeting.agenda_items or []
    if not isinstance(agenda_items, list):
        return
    changed = False
    for item in agenda_items:
        if not isinstance(item, dict):
            continue
        try:
            item_issue_id = int(item.get("issue_id") or 0)
        except (TypeError, ValueError):
            item_issue_id = 0
        if item_issue_id == issue_id and bool(item.get("done", False)) != done:
            item["done"] = done
            changed = True
    if changed:
        meeting.agenda_items = agenda_items
        meeting.save(update_fields=["agenda_items", "updated_at"])


def _meeting_issues_for_form(project: Project, meeting: KickoffMeeting | None = None):
    qs = project.meeting_issues.select_related(
        "source_meeting",
        "resolution_meeting",
        "assigned_to",
        "linked_task",
        "resolved_by",
    )
    if meeting is None:
        return qs.filter(status=MeetingIssueStatus.OPEN).order_by("due_date", "created_at", "id")
    return qs.filter(
        Q(status=MeetingIssueStatus.OPEN)
        | Q(source_meeting=meeting)
        | Q(resolution_meeting=meeting)
        | Q(pk__in=_meeting_issue_ids_from_agenda(meeting))
    ).distinct().order_by("status", "due_date", "created_at", "id")


def _meeting_actions_for_form(project: Project, meeting: KickoffMeeting | None = None):
    """Azioni da mostrare nella pagina esito: le aperte + quelle nate qui."""
    qs = project.meeting_actions.select_related("source_meeting", "assigned_to", "linked_task")
    if meeting is None:
        return qs.filter(status=MeetingActionStatus.OPEN)
    return qs.filter(
        Q(status=MeetingActionStatus.OPEN) | Q(source_meeting=meeting)
    ).distinct()


def _meeting_public_url(meeting: KickoffMeeting) -> str:
    from ..minute_email import meeting_url

    return meeting_url(meeting)


def _ensure_unique_agenda_item_ids(meeting: KickoffMeeting) -> list[dict]:
    """Ripara gli id duplicati o mancanti dei punti, e restituisce i punti.

    Gli id nascevano da `Date.now()`: due punti aggiunti nello stesso
    millisecondo condividevano l'id, e in conduzione nota, spunta e tempo
    finivano sempre sul primo dei due. Gli incontri gia' salvati si sistemano
    qui, alla prima apertura della conduzione.
    """
    items = [item for item in (meeting.agenda_items or []) if isinstance(item, dict)]
    seen: set[str] = set()
    changed = False
    for index, item in enumerate(items):
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen:
            item_id = f"{item_id or 'item'}-{index}-{uuid4().hex[:6]}"
            item["id"] = item_id
            changed = True
        seen.add(item_id)
    if changed:
        meeting.agenda_items = items
        meeting.save(update_fields=["agenda_items", "updated_at"])
    return items
