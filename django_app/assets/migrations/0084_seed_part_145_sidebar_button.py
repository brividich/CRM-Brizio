from django.db import migrations


def seed_part_145_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.get_or_create(
        code="part_145_list",
        defaults={
            "section": "OPERATIONS",
            "label": "PART 145",
            "target_url": "django:assets:part_145_list",
            "active_match": "/assets/part-145/",
            "is_subitem": False,
            "sort_order": 70,
            "is_visible": True,
        },
    )


def unseed_part_145_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="part_145_list").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0083_asset_part_145"),
    ]

    operations = [
        migrations.RunPython(
            seed_part_145_sidebar_button,
            unseed_part_145_sidebar_button,
        ),
    ]
