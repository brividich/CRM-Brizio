"""Ristruttura la sidebar manutenzione in 3 voci:
- Hub manutenzione (ex-pannello) → /assets/manutenzione/
- Scadenzario → /assets/manutenzione/scadenzario/
- Impostazioni → /assets/manutenzione/impostazioni/

Rimuove le voci sconnesse (prossime, contratti, verifiche periodiche separate,
template, regole come sotto-voci di impostazioni, scadenze amministrative).
"""
from django.db import migrations


CODES_TO_REMOVE = [
    "manut_schedule",
    "contratti",
    "impostazioni",
    "impost_template",
    "impost_regole",
    "scadenze",
    "manut_per_main",
    "dev_manut_per",
    "manut_hub",
]


def forwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    # Rimuove le voci obsolete
    AssetSidebarButton.objects.filter(code__in=CODES_TO_REMOVE).delete()

    # Aggiorna la voce hub esistente
    AssetSidebarButton.objects.filter(code="manut_per_main").delete()

    existing = AssetSidebarButton.objects.filter(code="maintenance_hub").first()
    if existing:
        existing.label = "Hub manutenzione"
        existing.target_url = "django:assets:maintenance_hub"
        existing.active_match = "/assets/manutenzione/"
        existing.is_subitem = False
        existing.parent = None
        existing.sort_order = 55
        existing.is_visible = True
        existing.save()
    else:
        AssetSidebarButton.objects.create(
            code="maintenance_hub",
            section="MAIN",
            label="Hub manutenzione",
            target_url="django:assets:maintenance_hub",
            active_match="/assets/manutenzione/",
            is_subitem=False,
            parent=None,
            sort_order=55,
            is_visible=True,
        )

    # Voce Scadenzario
    if not AssetSidebarButton.objects.filter(code="maintenance_scadenzario").exists():
        AssetSidebarButton.objects.create(
            code="maintenance_scadenzario",
            section="MAIN",
            label="Scadenzario",
            target_url="django:assets:maintenance_scadenzario",
            active_match="/assets/manutenzione/scadenzario/",
            is_subitem=False,
            parent=None,
            sort_order=56,
            is_visible=True,
        )

    # Voce Impostazioni manutenzione
    if not AssetSidebarButton.objects.filter(code="maintenance_impostazioni").exists():
        AssetSidebarButton.objects.create(
            code="maintenance_impostazioni",
            section="MAIN",
            label="Impostazioni",
            target_url="django:assets:maintenance_impostazioni",
            active_match="/assets/manutenzione/impostazioni/",
            is_subitem=False,
            parent=None,
            sort_order=57,
            is_visible=True,
        )


def backwards(apps, schema_editor):
    # Non ripristinabile in modo affidabile
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0073_seed_category_novicrom"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
