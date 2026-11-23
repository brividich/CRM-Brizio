"""Voce di menu «P11TF12» accanto a «PART 145» (pagina del processo di foratura critica).

Idempotente: crea la voce solo se manca, non tocca quella esistente.
"""
from django.db import migrations


def aggiungi(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    vicina = AssetSidebarButton.objects.filter(code="part_145_list").first()
    AssetSidebarButton.objects.get_or_create(
        code="p11tf12",
        defaults={
            "section": vicina.section if vicina else "OPERATIONS",
            "parent": vicina.parent if vicina else None,
            "label": "P11TF12",
            "target_url": "django:assets:p11tf12",
            "active_match": "/assets/p11tf12/",
            "is_subitem": vicina.is_subitem if vicina else False,
            "sort_order": (vicina.sort_order + 1) if vicina else 71,
            "is_visible": True,
        },
    )


def togli(apps, schema_editor):
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code="p11tf12").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0171_indici_manutenzione"),
    ]

    operations = [
        migrations.RunPython(aggiungi, togli),
    ]
