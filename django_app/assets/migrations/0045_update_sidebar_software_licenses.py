from django.db import migrations


def _update_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="software_licenses").update(
        label="Licenze software",
        target_url="django:assets:software_license_list",
        active_match="/assets/licenze/",
    )


def _noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0044_software_license"),
    ]

    operations = [
        migrations.RunPython(_update_sidebar_button, _noop_reverse),
    ]
