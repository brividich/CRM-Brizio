from django.db import migrations


def forwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    updates = {
        "dev_manut_per": {
            "label": "Manutenzione periodica IT",
            "target_url": "django:assets:periodic_verifications?scope=it",
            "active_match": "",
        },
        "manut_per_main": {
            "label": "Manutenzione periodica produzione",
            "target_url": "django:assets:periodic_verifications?scope=production",
            "active_match": "",
        },
        "periodic_verifications": {
            "label": "Manutenzione periodica produzione",
            "target_url": "django:assets:periodic_verifications?scope=production",
            "active_match": "",
        },
    }
    for code, values in updates.items():
        AssetSidebarButton.objects.filter(code=code).update(**values)


def backwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__in=["dev_manut_per", "manut_per_main", "periodic_verifications"]).update(
        label="Manutenzione periodica",
        target_url="django:assets:periodic_verifications",
        active_match="/assets/manutenzione/verifiche/",
    )
    AssetSidebarButton.objects.filter(code="dev_manut_per").update(active_match="")


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0054_split_report_sidebar_scope"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
