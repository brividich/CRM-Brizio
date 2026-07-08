"""Migration 0065 — Voce 'Gestione notifiche' nel gruppo 'sistema' dell'admin_subnav.

Punta a /admin-portale/notifiche-config/: interruttore admin globale per accendere/
spegnere le categorie di notifica per tutti gli utenti.
"""
from django.db import migrations

CODE = "admin-notifiche-config"
ITEM = dict(
    label="Gestione notifiche",
    section="admin_subnav",
    group="sistema",
    order=173,  # subito dopo "Log notifiche" (172)
    route_name="admin_portale:notifiche_config",
    active_patterns="admin_portale:notifiche_config",
    description="Gestione notifiche: accendi/spegni per tutti gli utenti ciascuna categoria di notifica (admin globale).",
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
        ("core", "0064_admin_subnav_notifiche_log"),
    ]

    operations = [
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
