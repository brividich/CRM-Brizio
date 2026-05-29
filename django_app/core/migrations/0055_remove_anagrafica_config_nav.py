from django.db import migrations


def deactivate_anagrafica_config_nav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(
        route_name="admin_portale:anagrafica_config"
    ).update(is_visible=False, is_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0054_add_user_table_preference"),
    ]

    operations = [
        migrations.RunPython(
            deactivate_anagrafica_config_nav,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
