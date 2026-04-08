"""
Migration 0042 — Aggiunge voce 'Branding' nel gruppo 'configurazione' dell'admin_subnav.
La voce punta a /admin-portale/branding/ per la gestione del favicon del portale.
"""
from django.db import migrations

CODE = "admin-branding"
ITEM = dict(
    label="Branding",
    section="admin_subnav",
    group="configurazione",
    order=155,  # tra "Login" (150) e "Checklist" (160)
    route_name="admin_portale:branding_config",
    active_patterns="admin_portale:branding_config",
    description="Branding: gestisci il favicon e l'identità visiva globale del portale (scheda browser, icona).",
    is_visible=True,
    is_enabled=True,
)


def add_branding_nav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults=ITEM,
    )


def remove_branding_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_pulsante_descrizione"),
    ]

    operations = [
        migrations.RunPython(add_branding_nav, reverse_code=remove_branding_nav),
    ]
