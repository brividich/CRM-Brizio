"""Sidebar asset guidata dall'albero categorie.

Sostituisce i gruppi sidebar basati su asset_type ("Dispositivi IT" e
"Asset produzione" con le sotto-voci ?asset_type=...) con un gruppo per ogni
categoria radice e una voce per ogni sotto-categoria, che aprono l'inventario
filtrato per categoria.
"""
from django.db import migrations

from assets.services.sidebar_categories import rebuild_category_sidebar


def seed(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    rebuild_category_sidebar(AssetCategory, AssetSidebarButton)


def unseed(apps, schema_editor):
    # I pulsanti categoria vengono rimossi; lo stato precedente (basato su
    # asset_type) non e' ripristinabile in modo affidabile.
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code__startswith="catnav-").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0066_assetmaintenancebudget"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
