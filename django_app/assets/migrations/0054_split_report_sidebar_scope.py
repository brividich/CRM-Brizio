from django.db import migrations


def forwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    updates = {
        "dev_reports": {
            "label": "Report dispositivi IT",
            "target_url": "django:assets:reports?scope=it",
            "active_match": "",
        },
        "prod_reports": {
            "label": "Report asset produzione",
            "target_url": "django:assets:reports?scope=production",
            "active_match": "",
        },
    }
    for code, values in updates.items():
        AssetSidebarButton.objects.filter(code=code).update(**values)


def backwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__in=["dev_reports", "prod_reports"]).update(
        label="Report manutenzione",
        target_url="django:assets:reports",
        active_match="",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0053_alter_assetcategory_base_asset_type_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
