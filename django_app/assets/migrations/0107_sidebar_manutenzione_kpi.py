"""Voce «Report» del ramo Manutenzione diventa «KPI».

La pagina KPI (``/assets/manutenzione/quadro/kpi/``) legge le stesse occorrenze
della Panoramica; il vecchio «Report» calcolava la compliance sul motore a regole
ritirato. I report storici (budget, export, PDF) restano raggiungibili dalla
pagina KPI. Allineata a ``assets.maintenance_nav``.

Idempotente e reversibile.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    Button.objects.filter(code="report_asset").update(
        label="KPI",
        target_url="django:assets:maintenance_kpi",
        active_match="/assets/manutenzione/quadro/kpi/",
    )


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    Button.objects.filter(code="report_asset").update(
        label="Report",
        target_url="django:assets:reports?scope=production",
        active_match="/assets/reports/",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0106_sidebar_manutenzione_menu_unico"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
