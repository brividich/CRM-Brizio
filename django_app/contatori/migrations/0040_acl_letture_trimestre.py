"""Binding ACL v2 di inserimento delle letture di un trimestre per tutte le MFC (gestione).

Stessa regola della 0025/0030/0032/0036/0039: binding solo se manca, nulla con un binding a
prefisso su /contatori/.
"""
from django.db import migrations

GESTIONE = "contatori.gestione.manage"
ROUTE_GESTIONE = ["letture_trimestre"]
ROUTE_VIEW = []
VIEW = "contatori.modulo.view"
NOTA = "[CONTATORI_0040] binding letture del trimestre"


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if not Permesso.objects.filter(code__in=[GESTIONE, VIEW]).count() == 2:
        return  # la 0025 crea i permessi: senza, nessun binding orfano
    if Binding.objects.filter(is_active=True, match_strategy="prefix",
                              path_pattern__in=["/contatori/", "/contatori"]).exists():
        return
    for nomi, code in ((ROUTE_VIEW, VIEW), (ROUTE_GESTIONE, GESTIONE)):
        for nome in nomi:
            route = f"contatori:{nome}"
            if Binding.objects.filter(route_name=route).exists():
                continue
            Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact",
                                   permission_id=code, source_app="contatori", priority=80,
                                   is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0039_acl_fatture_registro_letture"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
