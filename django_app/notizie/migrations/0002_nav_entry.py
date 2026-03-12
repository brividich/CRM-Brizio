from __future__ import annotations

from django.db import migrations


def add_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code="notizie",
        defaults={
            "label": "Notizie",
            "section": "topbar",
            "order": 50,
            "route_name": "notizie_lista",
            "url_path": "",
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "description": "Notizie e comunicazioni aziendali",
        },
    )


def remove_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="notizie").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notizie", "0001_initial"),
        ("core", "0010_alter_anagraficarisposta_id_alter_anagraficavoce_id_and_more"),
    ]

    operations = [
        migrations.RunPython(add_nav_item, reverse_code=remove_nav_item),
    ]
