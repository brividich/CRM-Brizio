"""Voce di menu admin «Azioni rapide della home» (admin_portale:home_azioni_rapide)."""

from django.db import migrations

NAV_CODE = "admin-home-azioni-rapide"
NAV_ITEM = dict(
    label="Azioni rapide della home",
    section="admin_subnav",
    group="configurazione",
    order=160,  # dopo «Cataloghi Sapere» (159)
    route_name="admin_portale:home_azioni_rapide",
    active_patterns="admin_portale:home_azioni_rapide",
    description="Scorciatoie della home per tutti, per ruolo o per singole persone, anche in blocco.",
    icon="zap",
    is_visible=True,
    is_enabled=True,
)


def add_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.get_or_create(code=NAV_CODE, defaults=NAV_ITEM)


def remove_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0107_sapere_cataloghi_copertine"),
    ]

    operations = [
        migrations.RunPython(add_nav, remove_nav),
    ]
