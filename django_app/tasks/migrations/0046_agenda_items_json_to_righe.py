"""Copia i punti ODG dal JSON `KickoffMeeting.agenda_items` alle righe MeetingAgendaItem.

- l'ordine dei punti si conserva (`ordine` = posizione nel JSON);
- id vuoti o ripetuti ricevono un id nuovo, come gia' faceva la conduzione;
- i collegamenti ad attivita', problemi, azioni e responsabile che puntano a
  record non piu' esistenti si azzerano (il vincolo FK li rifiuterebbe);
- reversibile: all'indietro ricostruisce il JSON dalle righe.
"""
from uuid import uuid4

from django.conf import settings
from django.db import migrations

ID_MAX = 255


def _int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _source(item):
    # Se il collegamento a problema/azione si perde, l'origine resta riconoscibile.
    source = str(item.get("source") or "").strip()[:40]
    if not source and _int(item.get("issue_id")):
        return "meeting_issue"
    if not source and _int(item.get("action_id")):
        return "meeting_action"
    return source


def json_to_rows(apps, schema_editor):
    KickoffMeeting = apps.get_model("tasks", "KickoffMeeting")
    MeetingAgendaItem = apps.get_model("tasks", "MeetingAgendaItem")
    Task = apps.get_model("tasks", "Task")
    MeetingIssue = apps.get_model("tasks", "MeetingIssue")
    MeetingActionItem = apps.get_model("tasks", "MeetingActionItem")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    existing = {
        "task_id": set(Task.objects.values_list("pk", flat=True)),
        "issue_id": set(MeetingIssue.objects.values_list("pk", flat=True)),
        "action_id": set(MeetingActionItem.objects.values_list("pk", flat=True)),
        "responsabile_id": set(User.objects.values_list("pk", flat=True)),
    }

    def ref(item, key):
        value = _int(item.get(key))
        return value if value in existing[key] else None

    rows = []
    for meeting_id, items in KickoffMeeting.objects.values_list("pk", "agenda_items").iterator():
        if not isinstance(items, list):
            continue
        seen = set()
        for index, item in enumerate(i for i in items if isinstance(i, dict)):
            item_id = str(item.get("id") or "").strip()[:ID_MAX]
            if not item_id or item_id in seen:
                item_id = f"item-{index}-{uuid4().hex[:8]}"
            seen.add(item_id)
            custom_fields = item.get("custom_fields")
            rows.append(MeetingAgendaItem(
                meeting_id=meeting_id,
                ordine=index,
                item_id=item_id,
                titolo=str(item.get("titolo") or "").strip()[:240],
                nota=str(item.get("nota") or ""),
                source=_source(item),
                locked=bool(item.get("locked", False)),
                done=bool(item.get("done", False)),
                task_id=ref(item, "task_id"),
                task_label=str(item.get("task_label") or "").strip()[:200],
                issue_id=ref(item, "issue_id"),
                action_id=ref(item, "action_id"),
                responsabile_id=ref(item, "responsabile_id"),
                responsabile_label=str(item.get("responsabile_label") or "").strip()[:150],
                durata_minuti=_int(item.get("durata_minuti")),
                tempo_effettivo_minuti=_int(item.get("tempo_effettivo_minuti")),
                custom_fields=custom_fields if isinstance(custom_fields, list) else [],
            ))
    MeetingAgendaItem.objects.bulk_create(rows, batch_size=200)


def rows_to_json(apps, schema_editor):
    KickoffMeeting = apps.get_model("tasks", "KickoffMeeting")
    MeetingAgendaItem = apps.get_model("tasks", "MeetingAgendaItem")
    by_meeting = {}
    for row in MeetingAgendaItem.objects.order_by("meeting_id", "ordine", "id").iterator():
        by_meeting.setdefault(row.meeting_id, []).append({
            "id": row.item_id,
            "titolo": row.titolo,
            "nota": row.nota,
            "task_id": row.task_id,
            "task_label": row.task_label,
            "issue_id": row.issue_id,
            "action_id": row.action_id,
            "source": row.source,
            "locked": row.locked,
            "responsabile_id": row.responsabile_id,
            "responsabile_label": row.responsabile_label,
            "durata_minuti": row.durata_minuti,
            "tempo_effettivo_minuti": row.tempo_effettivo_minuti,
            "custom_fields": row.custom_fields or [],
            "done": row.done,
        })
    for meeting_id, items in by_meeting.items():
        KickoffMeeting.objects.filter(pk=meeting_id).update(agenda_items=items)
    MeetingAgendaItem.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0045_meetingagendaitem"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(json_to_rows, rows_to_json),
    ]
