from django.db import migrations


def seed_maintenance_operations_sidebar_buttons(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    rows = [
        {
            "code": "software_licenses",
            "section": "MAIN",
            "label": "Interventi",
            "target_url": "django:assets:wo_list",
            "active_match": "/assets/workorders/",
            "sort_order": 63,
        },
        {
            "code": "maintenance_schedule",
            "section": "OPERATIONS",
            "label": "Prossime manutenzioni",
            "target_url": "django:assets:maintenance_schedule",
            "active_match": "/assets/manutenzione/prossime/",
            "sort_order": 66,
        },
        {
            "code": "assistance_contracts",
            "section": "OPERATIONS",
            "label": "Contratti assistenza",
            "target_url": "django:assets:assistance_contract_list",
            "active_match": "/assets/manutenzione/contratti/",
            "sort_order": 67,
        },
        {
            "code": "lifecycle_tracking",
            "section": "ANALYTICS",
            "label": "Report manutenzione",
            "target_url": "django:assets:reports",
            "active_match": "/assets/reports/",
            "sort_order": 70,
        },
        {
            "code": "compliance_reports",
            "section": "ANALYTICS",
            "label": "Scadenzario operativo",
            "target_url": "django:assets:maintenance_schedule",
            "active_match": "/assets/manutenzione/prossime/",
            "sort_order": 80,
        },
    ]

    for item in rows:
        button, _created = AssetSidebarButton.objects.get_or_create(
            code=item["code"],
            defaults={
                "section": item["section"],
                "label": item["label"],
                "target_url": item["target_url"],
                "active_match": item["active_match"],
                "is_subitem": False,
                "sort_order": item["sort_order"],
                "is_visible": True,
            },
        )
        updates = []
        if button.section != item["section"]:
            button.section = item["section"]
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


def unseed_maintenance_operations_sidebar_buttons(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__in=["maintenance_schedule", "assistance_contracts"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0036_maintenancerule_warning_days_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_maintenance_operations_sidebar_buttons,
            unseed_maintenance_operations_sidebar_buttons,
        ),
    ]
