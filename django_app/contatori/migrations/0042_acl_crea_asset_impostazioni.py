"""Binding ACL v2 di «Crea asset dall'apparato» e della pagina «Impostazioni SNMP» (gestione).

Stessa regola della 0025/0030/0032/0036/0039/0040/0041: binding solo se manca, nulla con
un binding a prefisso su /contatori/.
"""
from django.db import migrations

GESTIONE = "contatori.gestione.manage"
ROUTE_GESTIONE = ["apparato_crea_asset", "impostazioni"]
VIEW = "contatori.modulo.view"
NOTA = "[CONTATORI_0042] binding crea asset e impostazioni"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code__in=[GESTIONE, VIEW]).count() == 2:
        return  # la 0025 crea i permessi: senza, nessun binding orfano
    if Binding.objects.filter(is_active=True, match_strategy="prefix",
                              path_pattern__in=["/contatori/", "/contatori"]).exists():
        return
    for nome in ROUTE_GESTIONE:
        route = f"contatori:{nome}"
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                               permission_id=GESTIONE, source_app="contatori", priority=80,
                               is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0041_acl_letture_gestisci"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
