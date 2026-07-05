"""
Migration 0060 — Voce admin_subnav 'Documenti & Collegamenti' (gestione bacheca home).
Punta a /admin-portale/bacheca/ per gestire categorie, voci e visibilità per ruolo.
"""
from django.db import migrations

CODE = "admin-bacheca"
ITEM = dict(
    label="Documenti & Collegamenti",
    section="admin_subnav",
    group="configurazione",
    order=158,  # tra "Branding" (155) e "Checklist" (160)
    route_name="admin_portale:bacheca",
    active_patterns="admin_portale:bacheca",
    description="Bacheca home: gestisci documenti, collegamenti e scorciatoie mostrati agli utenti, con visibilità per ruolo.",
    icon="folder",
    is_visible=True,
    is_enabled=True,
)


def add_nav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(code=CODE, defaults=ITEM)


def remove_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0059_hublinkcategory_hublink_hublinkroleaccess"),
    ]

    operations = [
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
