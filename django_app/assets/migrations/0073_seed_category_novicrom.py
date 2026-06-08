from django.db import migrations


def seed_category_novicrom(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    AssetCategory.objects.get_or_create(
        code="novicrom",
        defaults={
            "label": "Novicrom",
            "base_asset_type": "OTHER",
            "description": "Beni e attrezzature aziendali Novicrom.",
            "sort_order": 10,
            "is_active": True,
        },
    )


def remove_category_novicrom(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    AssetCategory.objects.filter(code="novicrom").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0072_asset_internal_number"),
    ]

    operations = [
        migrations.RunPython(seed_category_novicrom, remove_category_novicrom),
    ]
