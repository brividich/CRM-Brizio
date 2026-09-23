"""«Officina» e «Segnala guasto» entrano nel ramo Manutenzione.

La Dashboard officina (``/assets/work-machines/dashboard/``) e la segnalazione
rapida di un guasto (``/assets/segnala/``) erano raggiungibili solo dall'elenco
asset: fuori dal menu della manutenzione, di cui fanno parte. Allineata a
``assets.maintenance_nav``.

Idempotente e reversibile.
"""
from django.db import migrations

VOCI = (
    ("maintenance_officina", "Officina", "django:assets:work_machine_dashboard", "/assets/work-machines/dashboard/", 55),
    ("maintenance_segnala", "Segnala guasto", "django:assets:asset_quick_report", "/assets/segnala/", 80),
)


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    hub = Button.objects.filter(code="maintenance_hub").first()
    if hub is None:
        return
    for code, label, target, match, order in VOCI:
        Button.objects.update_or_create(
            code=code,
            defaults={
                "section": hub.section,
                "parent": hub,
                "label": label,
                "target_url": target,
                "active_match": match,
                "is_subitem": True,
                "sort_order": order,
                "is_visible": True,
            },
        )


def indietro(apps, schema_editor):
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code__in=[v[0] for v in VOCI]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0109_sidebar_manutenzione_catalogo_in_piani"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
