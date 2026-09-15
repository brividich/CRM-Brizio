"""Migration 0074 — Voce 'Accessi negati' nel gruppo 'accessi' dell'admin_subnav.

Punta a /admin-portale/accessi-negati/: elenco dei 403 ricevuti dagli utenti, da
cui consentire o confermare il diniego sul ruolo o sulla singola persona.
"""
from django.db import migrations

CODE = "admin-accessi-negati"
ITEM = dict(
    label="Accessi negati",
    section="admin_subnav",
    parent_code="admin-portale",
    group="accessi",
    order=25,  # subito dopo "Utenti" (20)
    route_name="admin_portale:accessi_negati",
    active_patterns="admin_portale:accessi_negati",
    description="Accessi negati: chi ha ricevuto «Accesso negato» e su quale pagina. Da qui consenti o confermi il diniego, sul ruolo o sulla singola persona.",
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
        ("core", "0073_acl_denial_event"),
    ]

    operations = [
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
