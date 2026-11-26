"""Archivio della reportistica: conservazione dei file e «Rigenera».

- ``ReportGenerato.contenuto_eliminato_il``: quando il file con dati personali e' stato
  cancellato per la conservazione (la riga resta).
- Binding ACL v2 della route «Rigenera» (``anagrafica.reportistica.view``): con
  ACL_STRICT_CANONICAL una route senza binding e' negata, il bootstrap runtime gira solo
  a cache scaduta. Create-only, come ``0132``.
"""
from django.db import migrations, models

VIEW = "anagrafica.reportistica.view"
ROUTE = {"anagrafica:reportistica_archivio_rigenera": VIEW}
NOTA = "[REP_0258] binding rigenera dall'archivio"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for route, code in ROUTE.items():
        if not Permesso.objects.filter(code=code).exists():
            continue  # reportistica non ancora inizializzata: ci pensera' il bootstrap
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact", permission_id=code,
                               source_app="anagrafica", priority=80, is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=list(ROUTE), note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0257_corso_unico_allinea_sessioni_online"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportgenerato",
            name="contenuto_eliminato_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(avanti, indietro),
    ]
