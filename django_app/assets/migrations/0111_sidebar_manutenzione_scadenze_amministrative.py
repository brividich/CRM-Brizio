"""«Scadenze amministrative» entra nel ramo Manutenzione.

Le scadenze amministrative (``/assets/scadenze/``) sono un registro separato dai
piani di manutenzione, ma la loro pagina non era nel menu. Allineata a
``assets.maintenance_nav``.

Idempotente e reversibile.
"""
from django.db import migrations

VOCE = (
    "maintenance_amministrative",
    "Scadenze amministrative",
    "django:assets:asset_administrative_deadline_list",
    "/assets/scadenze/",
    45,
)


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    hub = Button.objects.filter(code="maintenance_hub").first()
    if hub is None:
        return
    code, label, target, match, order = VOCE
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
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code=VOCE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0110_sidebar_manutenzione_officina_segnala"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
