"""Voce «Imposta» in testa al ramo Configurazione della Manutenzione.

Il percorso guidato (``/assets/manutenzione/piani/imposta/``) dice a che punto e'
la configurazione e porta dove si sistema: e' la prima cosa da aprire in
Configurazione, e il ramo apre li'. Allineata a ``assets.maintenance_nav``.

Idempotente e reversibile.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    config = Button.objects.filter(code="maintenance_configurazione").first()
    if config is None:
        return
    for button in Button.objects.filter(parent=config).exclude(code="maintenance_imposta"):
        # Le voci esistenti scalano di uno: "Imposta" va per prima.
        Button.objects.filter(pk=button.pk).update(sort_order=(button.sort_order or 0) + 5)
    Button.objects.update_or_create(
        code="maintenance_imposta",
        defaults={
            "section": config.section,
            "parent": config,
            "label": "Imposta",
            "target_url": "django:assets:maintenance_setup",
            "active_match": "/assets/manutenzione/piani/imposta/",
            "is_subitem": True,
            "sort_order": 5,
            "is_visible": True,
        },
    )
    Button.objects.filter(pk=config.pk).update(target_url="django:assets:maintenance_setup")


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    config = Button.objects.filter(code="maintenance_configurazione").first()
    Button.objects.filter(code="maintenance_imposta").delete()
    if config is None:
        return
    for button in Button.objects.filter(parent=config):
        Button.objects.filter(pk=button.pk).update(sort_order=max((button.sort_order or 0) - 5, 0))
    Button.objects.filter(pk=config.pk).update(target_url="django:assets:maintenance_plan_list")


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0107_sidebar_manutenzione_kpi"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
