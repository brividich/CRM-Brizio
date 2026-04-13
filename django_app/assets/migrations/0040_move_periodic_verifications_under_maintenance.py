from django.db import migrations


def move_periodic_verifications_under_maintenance(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    maintenance_hub, _created = AssetSidebarButton.objects.get_or_create(
        code="manutenzione_hub",
        defaults={
            "section": "MAIN",
            "label": "Manutenzione",
            "target_url": "django:assets:maintenance_template_list",
            "active_match": "/assets/manutenzione/",
            "is_subitem": False,
            "sort_order": 54,
            "is_visible": True,
        },
    )
    periodic_button, _created = AssetSidebarButton.objects.get_or_create(
        code="periodic_verifications",
        defaults={
            "section": "MAIN",
            "label": "Manutenzione periodica",
            "target_url": "django:assets:periodic_verifications",
            "active_match": "/assets/manutenzione/verifiche/",
            "parent": maintenance_hub,
            "is_subitem": True,
            "sort_order": 57,
            "is_visible": True,
        },
    )
    periodic_updates = []
    if periodic_button.section != "MAIN":
        periodic_button.section = "MAIN"
        periodic_updates.append("section")
    if periodic_button.label != "Manutenzione periodica":
        periodic_button.label = "Manutenzione periodica"
        periodic_updates.append("label")
    if periodic_button.target_url != "django:assets:periodic_verifications":
        periodic_button.target_url = "django:assets:periodic_verifications"
        periodic_updates.append("target_url")
    if periodic_button.active_match != "/assets/manutenzione/verifiche/":
        periodic_button.active_match = "/assets/manutenzione/verifiche/"
        periodic_updates.append("active_match")
    if periodic_button.parent_id != maintenance_hub.id:
        periodic_button.parent = maintenance_hub
        periodic_updates.append("parent")
    if not periodic_button.is_subitem:
        periodic_button.is_subitem = True
        periodic_updates.append("is_subitem")
    if periodic_button.sort_order != 57:
        periodic_button.sort_order = 57
        periodic_updates.append("sort_order")
    if not periodic_button.is_visible:
        periodic_button.is_visible = True
        periodic_updates.append("is_visible")
    if periodic_updates:
        periodic_button.save(update_fields=[*periodic_updates, "updated_at"])

    report_button = AssetSidebarButton.objects.filter(code="lifecycle_tracking").first()
    if report_button is not None:
        report_updates = []
        if report_button.parent_id != maintenance_hub.id:
            report_button.parent = maintenance_hub
            report_updates.append("parent")
        if report_button.section != "MAIN":
            report_button.section = "MAIN"
            report_updates.append("section")
        if not report_button.is_subitem:
            report_button.is_subitem = True
            report_updates.append("is_subitem")
        if report_button.sort_order != 58:
            report_button.sort_order = 58
            report_updates.append("sort_order")
        if report_updates:
            report_button.save(update_fields=[*report_updates, "updated_at"])


def move_periodic_verifications_back_to_work_machines(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    work_machines = AssetSidebarButton.objects.filter(code="work_machines").first()
    periodic_button = AssetSidebarButton.objects.filter(code="periodic_verifications").first()
    if periodic_button is not None:
        periodic_updates = []
        if periodic_button.section != "MAIN":
            periodic_button.section = "MAIN"
            periodic_updates.append("section")
        if periodic_button.label != "Verifiche periodiche":
            periodic_button.label = "Verifiche periodiche"
            periodic_updates.append("label")
        if periodic_button.target_url != "django:assets:periodic_verifications":
            periodic_button.target_url = "django:assets:periodic_verifications"
            periodic_updates.append("target_url")
        if periodic_button.active_match != "/assets/verifiche-periodiche/":
            periodic_button.active_match = "/assets/verifiche-periodiche/"
            periodic_updates.append("active_match")
        if work_machines is not None and periodic_button.parent_id != work_machines.id:
            periodic_button.parent = work_machines
            periodic_updates.append("parent")
        if not periodic_button.is_subitem:
            periodic_button.is_subitem = True
            periodic_updates.append("is_subitem")
        if periodic_button.sort_order != 56:
            periodic_button.sort_order = 56
            periodic_updates.append("sort_order")
        if periodic_updates:
            periodic_button.save(update_fields=[*periodic_updates, "updated_at"])

    report_button = AssetSidebarButton.objects.filter(code="lifecycle_tracking").first()
    if report_button is not None and report_button.sort_order != 57:
        report_button.sort_order = 57
        report_button.save(update_fields=["sort_order", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0039_assetcalendarevent_generic_sources"),
    ]

    operations = [
        migrations.RunPython(
            move_periodic_verifications_under_maintenance,
            move_periodic_verifications_back_to_work_machines,
        ),
    ]
