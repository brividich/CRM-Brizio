from django.db import migrations


DEFAULT_LAYOUT_CATEGORY = "Officina"


def seed_sidebar_parents_and_layout_categories(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    PlantLayout = apps.get_model("assets", "PlantLayout")

    parent_map = {
        "servers": "hardware",
        "workstations": "hardware",
        "networking": "hardware",
        "work_machines_dashboard": "work_machines",
        "periodic_verifications": "work_machines",
        "plant_layout_map": "work_machines",
    }

    rows_by_code = {
        row.code: row
        for row in AssetSidebarButton.objects.filter(code__in=set(parent_map.keys()) | set(parent_map.values()))
    }
    for child_code, parent_code in parent_map.items():
        child = rows_by_code.get(child_code)
        parent = rows_by_code.get(parent_code)
        if child is None or parent is None:
            continue
        child.parent = parent
        child.section = parent.section
        child.is_subitem = True
        child.save(update_fields=["parent", "section", "is_subitem", "updated_at"])

    PlantLayout.objects.filter(category="").update(category=DEFAULT_LAYOUT_CATEGORY)


def unseed_sidebar_parents_and_layout_categories(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(
        code__in=[
            "servers",
            "workstations",
            "networking",
            "work_machines_dashboard",
            "periodic_verifications",
            "plant_layout_map",
        ]
    ).update(parent=None)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0018_alter_plantlayout_options_assetsidebarbutton_parent_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_sidebar_parents_and_layout_categories,
            unseed_sidebar_parents_and_layout_categories,
        ),
    ]
