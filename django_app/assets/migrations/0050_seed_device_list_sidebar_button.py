from django.db import migrations


def seed(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.get_or_create(
        code="device_list",
        defaults={
            "section": "MAIN",
            "label": "Dispositivi IT",
            "target_url": "django:assets:device_list",
            "active_match": "/assets/dispositivi/",
            "is_subitem": False,
            "parent": None,
            "sort_order": 21,
            "is_visible": True,
        },
    )


def unseed(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="device_list").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0049_workmachine_photo"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
