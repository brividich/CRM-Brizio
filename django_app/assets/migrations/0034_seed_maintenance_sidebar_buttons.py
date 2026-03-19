from django.db import migrations


def seed_maintenance_sidebar_buttons(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    rows = [
        {
            "code": "maintenance_templates",
            "label": "Template manutenzione",
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "/assets/manutenzione/templates/",
            "sort_order": 54,
        },
        {
            "code": "maintenance_rules",
            "label": "Regole manutenzione",
            "target_url": "django:assets:maintenance_rule_list",
            "active_match": "/assets/manutenzione/regole/",
            "sort_order": 55,
        },
    ]

    for item in rows:
        button, _created = AssetSidebarButton.objects.get_or_create(
            code=item["code"],
            defaults={
                "section": "MAIN",
                "label": item["label"],
                "target_url": item["target_url"],
                "active_match": item["active_match"],
                "is_subitem": False,
                "sort_order": item["sort_order"],
                "is_visible": True,
            },
        )
        updates = []
        if button.section != "MAIN":
            button.section = "MAIN"
            updates.append("section")
        if button.label != item["label"]:
            button.label = item["label"]
            updates.append("label")
        if button.target_url != item["target_url"]:
            button.target_url = item["target_url"]
            updates.append("target_url")
        if button.active_match != item["active_match"]:
            button.active_match = item["active_match"]
            updates.append("active_match")
        if button.parent_id is not None:
            button.parent = None
            updates.append("parent")
        if button.is_subitem:
            button.is_subitem = False
            updates.append("is_subitem")
        if button.sort_order != item["sort_order"]:
            button.sort_order = item["sort_order"]
            updates.append("sort_order")
        if not button.is_visible:
            button.is_visible = True
            updates.append("is_visible")
        if updates:
            button.save(update_fields=[*updates, "updated_at"])


def unseed_maintenance_sidebar_buttons(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__in=["maintenance_templates", "maintenance_rules"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0033_maintenanceinterventiontemplate_maintenancerule"),
    ]

    operations = [
        migrations.RunPython(
            seed_maintenance_sidebar_buttons,
            unseed_maintenance_sidebar_buttons,
        ),
    ]
