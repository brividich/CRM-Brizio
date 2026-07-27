"""Data migration: la voce topbar "Registro OFI" punta al modulo standalone.

Il registro OFI è ora montato al top-level ``/ofi-registro/`` (namespace
``registro_ofi``) invece che sotto ``gestione_specifiche``. Aggiorna il
``route_name`` della voce di navigazione già creata in 0069. Idempotente.
"""
from django.db import migrations

NEW_ROUTE = "registro_ofi:lista"
OLD_ROUTE = "gestione_specifiche:ofi_registro"


def forwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="ofi_registro").update(route_name=NEW_ROUTE)


def backwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="ofi_registro").update(route_name=OLD_ROUTE)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0069_ofi_registro_nav"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
