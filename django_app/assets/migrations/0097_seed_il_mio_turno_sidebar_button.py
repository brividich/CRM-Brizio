from django.db import migrations


def seed_il_mio_turno_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.get_or_create(
        code="il_mio_turno",
        defaults={
            "section": "MAIN",
            "label": "Il mio turno",
            "target_url": "django:assets:il_mio_turno",
            "is_subitem": False,
            "sort_order": 5,
            "is_visible": True,
        },
    )


def unseed_il_mio_turno_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="il_mio_turno").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0096_maintenancecheckliststep_is_mandatory_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_il_mio_turno_sidebar_button,
            unseed_il_mio_turno_sidebar_button,
        ),
    ]
