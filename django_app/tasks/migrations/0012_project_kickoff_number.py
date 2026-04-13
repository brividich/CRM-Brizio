from __future__ import annotations

from django.db import migrations, models


def assign_existing_kickoff_numbers(apps, schema_editor):
    Project = apps.get_model("tasks", "Project")
    for index, project in enumerate(Project.objects.order_by("id"), start=1):
        Project.objects.filter(pk=project.pk).update(kickoff_number=index)


def rename_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="tasks").update(
        label="KICK-OFF",
        description="KICK-OFF",
    )


def revert_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="tasks").update(
        label="VRF - Kick Off",
        description="VRF - Kick Off",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_fix_assets_nav_url"),
        ("tasks", "0011_project_vrf_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="kickoff_number",
            field=models.PositiveIntegerField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(assign_existing_kickoff_numbers, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="project",
            name="kickoff_number",
            field=models.PositiveIntegerField(blank=True, db_index=True, editable=False, null=True, unique=True),
        ),
        migrations.RunPython(rename_nav_item, reverse_code=revert_nav_item),
    ]
