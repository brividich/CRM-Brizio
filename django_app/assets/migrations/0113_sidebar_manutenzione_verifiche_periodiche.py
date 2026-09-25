"""«Verifiche periodiche» entra nel ramo Manutenzione, dopo «Scadenze amministrative».

Verifiche sugli impianti (``/assets/manutenzione/verifiche-impianti/``), allineata a
``assets.maintenance_nav``. Distinta dalla vecchia «Manutenzioni periodiche».

Idempotente e reversibile.
"""
from django.db import migrations

VOCE = (
    "maintenance_verifiche",
    "Verifiche periodiche",
    "django:assets:periodic_check_list",
    "/assets/manutenzione/verifiche-impianti/",
    47,
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
        ("assets", "0112_verifiche_periodiche_impianti"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
