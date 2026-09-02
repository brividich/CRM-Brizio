from django.db import migrations
from django.db.models import Count


_BATCH_SIZE = 500


def _normalize_part_number(value):
    return " ".join(str(value or "").strip().upper().split())


def _normalize_client_name(value):
    return " ".join(str(value or "").strip().split())


def _flush_updates(Project, pending):
    if not pending:
        return 0
    Project.objects.bulk_update(
        pending,
        ["part_number", "client_name"],
        batch_size=_BATCH_SIZE,
    )
    updated = len(pending)
    pending.clear()
    return updated


def normalize_project_identity(apps, schema_editor):
    Project = apps.get_model("tasks", "Project")
    pending = []
    updated = 0

    queryset = Project.objects.only("id", "part_number", "client_name").order_by("id")
    for project in queryset.iterator(chunk_size=_BATCH_SIZE):
        part_number = _normalize_part_number(project.part_number)
        client_name = _normalize_client_name(project.client_name)
        if part_number == project.part_number and client_name == project.client_name:
            continue
        project.part_number = part_number
        project.client_name = client_name
        pending.append(project)
        if len(pending) >= _BATCH_SIZE:
            updated += _flush_updates(Project, pending)
    updated += _flush_updates(Project, pending)

    print(f"[tasks 0035] Identita' commesse normalizzate: {updated}")

    collisions = (
        Project.objects.exclude(part_number="")
        .values("part_number", "revisione", "versione")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .order_by("part_number", "revisione", "versione")
    )
    collision_count = 0
    for collision in collisions.iterator(chunk_size=_BATCH_SIZE):
        ids = list(
            Project.objects.filter(
                part_number=collision["part_number"],
                revisione=collision["revisione"],
                versione=collision["versione"],
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        collision_count += 1
        print(
            "[tasks 0035] Collisione identita' "
            f"P/N={collision['part_number']!r}, revisione={collision['revisione']!r}, "
            f"versione={collision['versione']!r}, project_ids={ids}"
        )
    print(f"[tasks 0035] Collisioni da verificare manualmente: {collision_count}")


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0034_kickoffmeeting_stato"),
    ]

    operations = [
        migrations.RunPython(normalize_project_identity, migrations.RunPython.noop),
    ]
