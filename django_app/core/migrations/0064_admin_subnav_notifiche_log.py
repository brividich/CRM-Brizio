"""Migration 0064 — Voce 'Log notifiche' nel gruppo 'sistema' dell'admin_subnav.

Punta a /admin-portale/notifiche-log/ per il log amministrativo (cross-utente)
delle notifiche in-app: verifica cosa parte davvero e a chi.
"""
from django.db import migrations

CODE = "admin-notifiche-log"
ITEM = dict(
    label="Log notifiche",
    section="admin_subnav",
    group="sistema",
    order=172,  # tra "Audit Log" (170) e "Health Check" (180)
    route_name="admin_portale:notifiche_log",
    active_patterns="admin_portale:notifiche_log",
    description="Log notifiche: tutte le notifiche in-app inviate agli utenti — filtra per tipo, utente, stato; conteggi per tipo; export CSV.",
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
        ("core", "0063_tasks_calendario_subnav"),
    ]

    operations = [
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
