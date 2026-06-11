"""Sidebar manutenzione: nodo unico dopo il consolidamento delle dashboard.

Le tre dashboard (hub / to-do / scadenzario) sono confluite nella pagina unica
a tab `maintenance_hub`. La sidebar diventa:

    Manutenzione                → /assets/manutenzione/
      ├─ Da fare                → /assets/manutenzione/?tab=da_fare
      ├─ Scadenzario            → /assets/manutenzione/?tab=scadenzario
      └─ Impostazioni           → /assets/manutenzione/impostazioni/

La voce top-level "Scadenzario" separata viene rimossa (ora è una tab).
"""
from django.db import migrations


def forwards(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    # Nodo principale: ex "Hub manutenzione" → "Manutenzione"
    hub = AssetSidebarButton.objects.filter(code="maintenance_hub").first()
    if hub:
        hub.label = "Manutenzione"
        hub.target_url = "django:assets:maintenance_hub"
        hub.active_match = "/assets/manutenzione/"
        hub.is_subitem = False
        hub.parent = None
        hub.sort_order = 55
        hub.is_visible = True
        hub.save()
    else:
        hub = AssetSidebarButton.objects.create(
            code="maintenance_hub",
            section="MAIN",
            label="Manutenzione",
            target_url="django:assets:maintenance_hub",
            active_match="/assets/manutenzione/",
            is_subitem=False,
            parent=None,
            sort_order=55,
            is_visible=True,
        )

    # Sottovoce "Da fare"
    AssetSidebarButton.objects.update_or_create(
        code="maintenance_da_fare",
        defaults=dict(
            section="MAIN",
            label="Da fare",
            target_url="/assets/manutenzione/?tab=da_fare",
            active_match="tab=da_fare",
            is_subitem=True,
            parent=hub,
            sort_order=56,
            is_visible=True,
        ),
    )

    # La vecchia voce top-level "Scadenzario" diventa sottovoce dell'hub
    scad = AssetSidebarButton.objects.filter(code="maintenance_scadenzario").first()
    if scad:
        scad.label = "Scadenzario"
        scad.target_url = "/assets/manutenzione/?tab=scadenzario"
        scad.active_match = "tab=scadenzario"
        scad.is_subitem = True
        scad.parent = hub
        scad.sort_order = 57
        scad.is_visible = True
        scad.save()
    else:
        AssetSidebarButton.objects.create(
            code="maintenance_scadenzario",
            section="MAIN",
            label="Scadenzario",
            target_url="/assets/manutenzione/?tab=scadenzario",
            active_match="tab=scadenzario",
            is_subitem=True,
            parent=hub,
            sort_order=57,
            is_visible=True,
        )

    # Impostazioni diventa sottovoce dell'hub
    imp = AssetSidebarButton.objects.filter(code="maintenance_impostazioni").first()
    if imp:
        imp.label = "Impostazioni"
        imp.target_url = "django:assets:maintenance_impostazioni"
        imp.active_match = "/assets/manutenzione/impostazioni/"
        imp.is_subitem = True
        imp.parent = hub
        imp.sort_order = 58
        imp.is_visible = True
        imp.save()


def backwards(apps, schema_editor):
    # Non ripristinabile in modo affidabile (vedi 0074).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0075_asset_production_date_asset_purchase_date"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
