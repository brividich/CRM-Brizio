from django.db import migrations

# Voce «Accessi bloccati» nella barra di admin-portale, gruppo «accessi»
# (fra «Accessi negati», 25, e «Postazioni condivise», 27).
NAV_CODE = "admin-accessi-bloccati"
NAV_ITEM = dict(
    label="Accessi bloccati",
    section="admin_subnav",
    parent_code="admin-portale",
    group="accessi",
    order=26,
    route_name="admin_portale:accessi_bloccati",
    active_patterns="admin_portale:accessi_bloccati",
    description="Login bloccati per troppe password sbagliate, con «Sblocca».",
    is_visible=True,
    is_enabled=True,
)


def add_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.get_or_create(code=NAV_CODE, defaults=NAV_ITEM)


def remove_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0102_impostazioni_tutte_le_pagine"),
    ]

    operations = [
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
