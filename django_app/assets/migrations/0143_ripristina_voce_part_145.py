"""Ripristina la voce di menu «PART 145» dove e' sparita.

In produzione la 0084 risulta applicata ma la riga ``part_145_list`` non c'e' piu'
(cancellata dopo da un rebuild o dall'editor del menu): la pagina esisteva, la voce no.
Idempotente: crea la voce solo se manca, non tocca quella esistente.
"""
from django.db import migrations


def ripristina(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.get_or_create(
        code="part_145_list",
        defaults={
            "section": "OPERATIONS",
            "parent": None,
            "label": "PART 145",
            "target_url": "django:assets:part_145_list",
            "active_match": "/assets/part-145/",
            "is_subitem": False,
            "sort_order": 70,
            "is_visible": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0142_ricambi_acl_menu"),
    ]

    operations = [
        migrations.RunPython(ripristina, migrations.RunPython.noop),
    ]
