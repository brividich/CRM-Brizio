from django.db import migrations

CODE = "tasks-sub-report-fai"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults={
            "label": "Report FAI",
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": "tasks:fai_report",
            "order": 26,
            "required_permission_code": "tasks.kickoff.projects",
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0110_tasks_subnav_programmi")]
    operations = [migrations.RunPython(seed, unseed)]
