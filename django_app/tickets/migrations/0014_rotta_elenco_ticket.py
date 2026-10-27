"""Sezione «Ticket» (/tickets/elenco/): stesso cancello di «I miei ticket».

La vista decide chi vede cosa (ruolo «vedere» team/tutti); qui serve solo che la
rotta nuova abbia un binding, altrimenti con ACL_STRICT_CANONICAL sarebbe negata.
"""
from django.db import migrations

NOTA = "[TICKETS_0014] stessa pagina di tickets:dashboard"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    dashboard = Binding.objects.filter(route_name="tickets:dashboard", path_pattern="", is_active=True).first()
    if dashboard is None or Binding.objects.filter(route_name="tickets:elenco", path_pattern="").exists():
        return
    Binding.objects.create(
        route_name="tickets:elenco", path_pattern="", match_strategy=dashboard.match_strategy,
        permission_id=dashboard.permission_id, source_app="tickets", note=NOTA,
        priority=dashboard.priority, is_active=True,
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name="tickets:elenco", note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("tickets", "0013_sharepoint_sync_man"), ("core", "0098_impostazioni_solo_pagina_impostazioni")]
    operations = [migrations.RunPython(avanti, indietro)]
