"""
Migration 0045 - Nota routing assets.

Ora /assets/ e la dashboard KPI del modulo.
La lista inventario canonica vive su /assets/lista/.
Questa migration resta intenzionalmente no-op come segnaposto documentale.
"""

from django.db import migrations


def fix_assets_list_nav_url(apps, schema_editor):
    # Nessuna scrittura necessaria: la migration fissa solo nel DAG
    # il cambio di routing tra dashboard modulo e lista inventario.
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0044_onboarding_notifiche_jsonfield"),
    ]

    operations = [
        migrations.RunPython(fix_assets_list_nav_url, reverse_code=migrations.RunPython.noop),
    ]
