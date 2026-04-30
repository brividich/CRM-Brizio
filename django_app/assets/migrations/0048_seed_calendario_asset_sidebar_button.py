from django.db import migrations


def seed_calendario_asset_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    parent = AssetSidebarButton.objects.filter(code="work_machines").first()
    AssetSidebarButton.objects.get_or_create(
        code="calendario_asset",
        defaults={
            "section": parent.section if parent else "MAIN",
            "label": "Calendario asset",
            "target_url": "django:assets:calendario_asset",
            "active_match": "/assets/calendario/",
            "is_subitem": True,
            "parent": parent,
            "sort_order": 59,
            "is_visible": True,
        },
    )


def unseed_calendario_asset_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="calendario_asset").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0047_alter_assetdetailsectionlayout_code"),
    ]

    operations = [
        migrations.RunPython(
            seed_calendario_asset_sidebar_button,
            unseed_calendario_asset_sidebar_button,
        ),
    ]
