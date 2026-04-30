from django.db import migrations


def forwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(
        code__in=["dev_reports", "prod_reports", "dev_manut_per", "manut_per_main", "periodic_verifications"]
    ).update(active_match="")


def backwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__in=["dev_reports", "dev_manut_per"]).update(active_match="scope=it")
    AssetSidebarButton.objects.filter(
        code__in=["prod_reports", "manut_per_main", "periodic_verifications"]
    ).update(active_match="scope=production")


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0055_split_periodic_verification_sidebar_scope"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
