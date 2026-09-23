"""«Catalogo attivita'» esce dal menu: e' la stessa lista dei Piani.

Catalogo e Piani mostravano lo stesso modello (``MaintenanceInterventionTemplate``)
in due pagine. La lista resta una, Piani; checklist e istruzioni si modificano
dalla scheda del piano. Il pulsante viene nascosto, non cancellato.

Reversibile.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code="maintenance_impostazioni").update(is_visible=False)


def indietro(apps, schema_editor):
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code="maintenance_impostazioni").update(is_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0108_sidebar_manutenzione_imposta"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
